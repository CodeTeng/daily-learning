"""短期记忆：对话历史 + 容量控制 + 压缩。

设计要点：

1. **消息流**就是 OpenAI Chat 风格的 `[{role, content}]`，便于直接喂给 LLM。
2. **容量控制**有两种策略：
   - 按**条数**滑窗（FIFO，最简单）
   - 按**估算 token** 预算（更接近真实成本）
3. **压缩**：超出预算时把最早的若干轮交给 LLM 总结成一段 system 摘要，
   再继续保留最近的几轮——这是工业界 Agent 处理长会话最常见的手段。

关键约束：
- system 消息（人格、规则）永远保留在最前面，不会被驱逐。
- 压缩出的 summary 同样以 system 消息形式注入到 system 之后。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str

    def as_openai(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def estimate_tokens(text: str) -> int:
    """玩具级 token 估算：中文 1 字 ≈ 1.5 token，英文 1 单词 ≈ 1.3 token。

    真实工程里请用 `tiktoken` 精确计数，这里只是给出"接近真实"的数量级。
    """
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - chinese_chars
    # 粗略估算：中文每字 1.5 token；剩下按"约 4 字符 = 1 token"
    return int(chinese_chars * 1.5 + max(other, 1) / 4 + 1)


@dataclass
class ShortTermMemory:
    """滑窗 + token 预算 + 可选摘要压缩。

    使用：
        stm = ShortTermMemory(max_messages=20, token_budget=2000)
        stm.add_system("你是技术助手")
        stm.add_user("你好")
        stm.add_assistant("你好，请问？")
        msgs = stm.as_messages()  # 喂给 LLM
    """

    max_messages: int = 50
    # 不含 system 的 token 上限；超出就触发压缩或 FIFO 驱逐
    token_budget: int = 2000

    # 压缩函数：传入若干旧消息，返回一段总结字符串。
    # 默认为 None，表示不压缩、直接 FIFO 驱逐最早的非系统消息。
    summarizer: Callable[[list[Message]], str] | None = None

    _messages: list[Message] = field(default_factory=list)
    _summary: str = ""  # 已压缩历史的累积摘要

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add_system(self, content: str) -> None:
        # system 永远放在第一条；如已有则替换
        msg = Message(role="system", content=content)
        if self._messages and self._messages[0].role == "system":
            self._messages[0] = msg
        else:
            self._messages.insert(0, msg)

    def add_user(self, content: str) -> None:
        self._messages.append(Message(role="user", content=content))
        self._enforce_limits()

    def add_assistant(self, content: str) -> None:
        self._messages.append(Message(role="assistant", content=content))
        self._enforce_limits()

    def add_tool_observation(self, content: str) -> None:
        self._messages.append(Message(role="tool", content=content))
        self._enforce_limits()

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def as_messages(self) -> list[dict[str, str]]:
        """返回 OpenAI 兼容的消息列表（system → 摘要 → 最近若干轮）。"""
        out: list[dict[str, str]] = []
        for m in self._messages:
            if m.role == "system":
                out.append(m.as_openai())
        if self._summary:
            out.append({"role": "system", "content": f"[历史摘要]\n{self._summary}"})
        for m in self._messages:
            if m.role != "system":
                out.append(m.as_openai())
        return out

    def total_tokens(self) -> int:
        n = sum(estimate_tokens(m.content) for m in self._messages if m.role != "system")
        if self._summary:
            n += estimate_tokens(self._summary)
        return n

    def message_count(self) -> int:
        return sum(1 for m in self._messages if m.role != "system")

    @property
    def summary(self) -> str:
        return self._summary

    def clear(self) -> None:
        self._messages = [m for m in self._messages if m.role == "system"]
        self._summary = ""

    # ------------------------------------------------------------------ #
    # 容量控制
    # ------------------------------------------------------------------ #
    def _enforce_limits(self) -> None:
        # 策略 1：消息条数硬上限（FIFO）
        while self.message_count() > self.max_messages:
            self._evict_or_summarize_one_round()

        # 策略 2：token 预算
        while self.total_tokens() > self.token_budget and self.message_count() > 2:
            self._evict_or_summarize_one_round()

    def _evict_or_summarize_one_round(self) -> None:
        """驱逐最早的一轮（user→assistant 算一轮）非系统消息。

        如果配置了 summarizer，会把被驱逐的消息总结进 self._summary，
        否则直接丢掉。
        """
        # 找到第一条非 system 消息的下标
        start = next((i for i, m in enumerate(self._messages) if m.role != "system"), None)
        if start is None:
            return

        # 一次驱逐 2 条（约 1 轮 user+assistant），不够就驱逐 1 条
        end = min(start + 2, len(self._messages))
        evicted = self._messages[start:end]
        self._messages = self._messages[:start] + self._messages[end:]

        if self.summarizer is not None and evicted:
            new_summary = self.summarizer(evicted)
            self._summary = (
                f"{self._summary}\n{new_summary}".strip()
                if self._summary
                else new_summary
            )
