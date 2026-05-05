"""Multi-Agent：多个角色化 Agent 协作。

经典三角色组合：

- **Researcher**（资料员）：负责查资料
- **Writer**（写作者）：负责把资料整合成成品
- **Critic**（评审员）：判断成品是否合格，不合格就给修改意见

Coordinator（也叫 Orchestrator）按"研究 → 写作 → 评审 → 不合格则回到写作"的
顺序调度，直到 Critic 说 APPROVE。

这是「Reflection 的多模型版」：把"写"和"批"分给两个专门的 Agent，
角色越分明，越不容易自我洗脑（自己写自己批容易护短）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .tools import TraceEntry


class _LLMLike(Protocol):
    call_count: int

    def complete(self, prompt: str) -> str: ...


@dataclass
class MultiAgentSystem:
    """单进程内运行多个角色，每个角色持有一个独立的 LLM 实例。"""

    researcher: _LLMLike
    writer: _LLMLike
    critic: _LLMLike
    max_rounds: int = 3

    def run(self, topic: str) -> tuple[str, list[TraceEntry]]:
        trace: list[TraceEntry] = []

        # 1) Researcher 出资料
        research = self.researcher.complete(
            "[role:researcher] 你是资料员，请用 1-2 句话给出关于以下主题的关键事实。\n"
            f"主题：{topic}"
        )
        trace.append(TraceEntry("llm", f"[Researcher] {research}"))

        article = ""
        feedback = ""
        for _ in range(self.max_rounds):
            # 2) Writer 写文章
            article = self.writer.complete(
                "[role:writer] 你是写作者。请基于资料写一段 2-4 句话的科普文。\n"
                "如果有评审反馈，请严格按反馈修改。\n\n"
                f"主题：{topic}\n"
                f"资料：{research}\n"
                f"上一轮评审反馈：{feedback or '（首轮）'}\n"
                "ARTICLE:"
            )
            trace.append(TraceEntry("llm", f"[Writer] {article}"))

            # 3) Critic 评审
            feedback = self.critic.complete(
                "[role:critic] 你是评审员。检查文章是否准确、完整、可读。\n"
                "- 合格则只回复一行：`CRITIC: APPROVE`\n"
                "- 否则用 `CRITIC: ` 开头给出最关键的一条修改意见。\n\n"
                f"文章：\n{article}"
            )
            trace.append(TraceEntry("llm", f"[Critic] {feedback}"))

            if "APPROVE" in feedback:
                break

        trace.append(TraceEntry("final", article))
        return article, trace
