"""MemoryManager：把短期 + 长期记忆组合起来用。

工作流（以一次对话轮为例）：

    1. user 输入 → manager.recall(query=user_text) 从长期记忆取相关内容
    2. 把 recall 结果以 system 消息形式注入到当前 messages 前面
    3. 调 LLM 拿到 assistant 回复
    4. manager.observe(user_text, assistant_text) 把这一轮写进短期记忆，
       同时按规则决定要不要把"重要的事实"写进长期记忆

这一文件**不绑定具体 LLM**，调用方自己决定怎么把 messages 喂给模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .embedding import Embedder, HashEmbedder
from .long_term import LongTermMemory
from .short_term import ShortTermMemory


@dataclass
class MemoryManager:
    """统一的记忆门面。

    Args:
        embedder: 长期记忆使用的 embedder；默认 HashEmbedder（零依赖）
        short_term: 自定义短期记忆配置；默认 max_messages=20, token_budget=2000
        long_term: 自定义长期记忆配置；默认 capacity=1000, 不过期
        recall_top_k: 每轮自动召回的条数
        recall_threshold: 召回的最低相似度门槛，过滤无关结果

    使用：
        mm = MemoryManager()
        mm.short_term.add_system("你是技术助手")
        ctx = mm.build_context("我用什么编辑器？")  # 自动召回长期记忆并拼成 messages
        # ... call LLM with ctx ...
        mm.observe(user="我用什么编辑器？", assistant="你之前说用 Cursor。")
        mm.remember_fact("用户用 Cursor 编辑器")  # 显式写入长期记忆
    """

    embedder: Embedder = field(default_factory=HashEmbedder)
    short_term: ShortTermMemory = field(default_factory=ShortTermMemory)
    long_term: LongTermMemory | None = None
    recall_top_k: int = 3
    recall_threshold: float = 0.2

    def __post_init__(self) -> None:
        if self.long_term is None:
            self.long_term = LongTermMemory(embedder=self.embedder)

    # ------------------------------------------------------------------ #
    # 读：组装一次 LLM 调用所需的 messages
    # ------------------------------------------------------------------ #
    def build_context(self, user_input: str | None = None) -> list[dict[str, str]]:
        """组装 messages：system + 召回 + 短期历史。

        如果传了 user_input，会自动用它做长期记忆的检索 query。
        注意此方法**不会**把 user_input 自己加进短期历史——调用方自己决定何时加。
        """
        messages = self.short_term.as_messages()

        if user_input:
            recalled = self.recall(user_input)
            if recalled:
                # 把召回内容以一条 system 消息注入到 system 后面、对话前面
                ctx_block = "[长期记忆召回]\n" + "\n".join(
                    f"- {hit.record.text}（相关度 {hit.score:.2f}）" for hit in recalled
                )
                # 找到最后一条 system 的位置，插在它后面
                insert_at = 0
                for i, m in enumerate(messages):
                    if m["role"] == "system":
                        insert_at = i + 1
                messages.insert(insert_at, {"role": "system", "content": ctx_block})
        return messages

    def recall(self, query: str) -> list:
        assert self.long_term is not None
        return self.long_term.recall(
            query, top_k=self.recall_top_k, score_threshold=self.recall_threshold
        )

    # ------------------------------------------------------------------ #
    # 写：观察一轮对话 / 显式记一条
    # ------------------------------------------------------------------ #
    def observe(self, user: str, assistant: str) -> None:
        """把一轮对话写进短期记忆。"""
        self.short_term.add_user(user)
        self.short_term.add_assistant(assistant)

    def remember_fact(self, text: str, meta: dict | None = None) -> str:
        """把一条值得长期保留的事实写入长期记忆。"""
        assert self.long_term is not None
        return self.long_term.remember(text, meta=meta)

    def forget_fact(self, record_id: str) -> bool:
        assert self.long_term is not None
        return self.long_term.forget(record_id)
