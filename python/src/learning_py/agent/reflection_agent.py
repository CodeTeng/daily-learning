"""Reflection：先生成一版，自己批改，再重写，直到满意或达到上限。

最小循环：

    draft = LLM.draft(task)
    while not ok and i < max:
        feedback = LLM.reflect(draft)
        if feedback == "OK":
            break
        draft = LLM.draft(task, feedback)

适合"一次产出不容易对、但有明确改进方向"的任务：写文档、写代码、做翻译。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .tools import TraceEntry


class _LLMLike(Protocol):
    call_count: int

    def complete(self, prompt: str) -> str: ...


@dataclass
class ReflectionAgent:
    llm: _LLMLike
    max_rounds: int = 3

    def run(self, task: str) -> tuple[str, list[TraceEntry]]:
        trace: list[TraceEntry] = []
        feedback = ""
        draft = ""

        for _ in range(self.max_rounds):
            # 1) 写/改草稿
            draft_prompt = (
                "[DRAFT] 请根据任务输出一份**完整的最终答案**（不要解释你做了什么，只给答案本身）。\n"
                f"任务：{task}\n"
                f"上一轮评审反馈：{feedback or '（首轮，没有反馈）'}\n"
                "DRAFT:"
            )
            draft = self.llm.complete(draft_prompt)
            trace.append(TraceEntry("llm", draft))

            # 2) 自我反思
            reflect_prompt = (
                "[REFLECT] 你是一个严格的评审员。请检查下面的草稿是否完整满足任务要求。\n"
                "- 如果完全合格，**只回复一行**：`REFLECTION: OK`\n"
                "- 否则简要指出最关键的一条问题，开头是 `REFLECTION:`。\n\n"
                f"草稿：\n{draft}"
            )
            feedback = self.llm.complete(reflect_prompt)
            trace.append(TraceEntry("llm", feedback))

            if "OK" in feedback:
                break

        trace.append(TraceEntry("final", draft))
        return draft, trace
