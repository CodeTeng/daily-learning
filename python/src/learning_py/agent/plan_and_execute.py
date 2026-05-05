"""Plan-and-Execute：先规划，后执行。

两个阶段：

1. **Planner**（一次 LLM 调用）：把任务拆成一个有序的 step 列表
2. **Executor**（按列表顺序执行）：每一步要么调工具，要么收尾

和 ReAct 的关键区别：**Plan 在最开始一次性产出**，执行阶段不再每步都让 LLM
重新思考。优点是稳定、可缓存、便于人工审核计划；缺点是中途遇到意外不会
自动调整方向（除非加 Re-Plan 机制）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .tools import (
    DEFAULT_TOOLBOX,
    Tool,
    TraceEntry,
    call_tool,
)


class _LLMLike(Protocol):
    call_count: int

    def complete(self, prompt: str) -> str: ...


@dataclass
class PlanAndExecuteAgent:
    llm: _LLMLike
    toolbox: dict[str, Tool] = field(default_factory=lambda: dict(DEFAULT_TOOLBOX))

    def run(self, task: str) -> tuple[str, list[TraceEntry]]:
        trace: list[TraceEntry] = []

        # ---- 1. Plan ----
        plan_prompt = self._build_plan_prompt(task)
        plan_output = self.llm.complete(plan_prompt)
        trace.append(TraceEntry("llm", plan_output))
        steps = _parse_plan(plan_output)
        trace.append(TraceEntry("final", f"PLAN={steps}"))  # 调试用

        # ---- 2. Execute ----
        observations: list[str] = []
        for step in steps:
            if step == "finalize":
                summary = "；".join(observations)
                final = f"任务完成：{summary}"
                trace.append(TraceEntry("final", final))
                return final, trace

            tool_name, arg = step
            obs = call_tool(self.toolbox, tool_name, arg)
            trace.append(TraceEntry("tool", f"{tool_name}({arg}) -> {obs}"))
            observations.append(obs)

        # 计划没显式 finalize，也走兜底
        final = "；".join(observations) or "（计划为空）"
        trace.append(TraceEntry("final", final))
        return final, trace

    def _build_plan_prompt(self, task: str) -> str:
        tools_desc = "\n".join(f"- {name}(arg)" for name in self.toolbox)
        return (
            "[PLAN] 你是一个任务规划器。请把用户任务拆成有序的步骤列表，**只输出列表本身，不要解释**。\n"
            "格式严格如下（每行一步，编号从 1 开始）：\n"
            "  1. tool_name(argument)\n"
            "  2. tool_name(argument)\n"
            "  3. finalize\n"
            "最后一步必须是 `finalize`，表示根据前面所有 OBSERVATION 总结答案。\n\n"
            f"可用工具：\n{tools_desc}\n\n"
            f"任务：{task}\n\n"
            "PLAN:"
        )


_STEP_RE = re.compile(r"^\s*\d+\.\s*(.+)$")
_CALL_HEAD_RE = re.compile(r"([a-zA-Z_]+)\s*\(")

# 一步要么是 `(tool_name, arg)` 元组，要么是字面量 "finalize"
PlanStep = tuple[str, str] | str


def _parse_plan(text: str) -> list[PlanStep]:
    """把 Planner 的输出解析成 step 列表。

    支持两种 step 形态：
    - `tool(arg)` -> `("tool", "arg")`，arg 内允许嵌套括号（如 calc((1+2)*3)）
    - `finalize`  -> `"finalize"`
    """
    steps: list[PlanStep] = []
    for line in text.splitlines():
        m = _STEP_RE.match(line)
        if not m:
            continue
        body = m.group(1).strip().strip("`*")  # 去掉 markdown 装饰
        if body.lower().startswith("finalize"):
            steps.append("finalize")
            continue
        cm = _CALL_HEAD_RE.search(body)
        if not cm:
            continue
        # 用括号配平扫描，正确解析嵌套括号的参数
        tool_name = cm.group(1)
        start = cm.end()
        depth = 1
        i = start
        while i < len(body) and depth > 0:
            c = body[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            continue
        arg = body[start:i].strip().strip("\"'")
        steps.append((tool_name, arg))
    return steps
