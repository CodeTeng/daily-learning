"""ReAct：Reasoning + Acting。

每一步循环里，LLM 输出：
    THOUGHT: ...    （想法）
    ACTION: tool(arg)  或  FINAL: ...

外层框架解析这一步：
- 如果是 ACTION，去调工具，把"观察结果"喂回 LLM
- 如果是 FINAL，结束

特点：**思考一步 / 行动一步 / 观察一步**，紧耦合循环。
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
    """任何提供 `complete(prompt) -> str` 的对象都可以当 LLM。"""

    call_count: int

    def complete(self, prompt: str) -> str: ...


@dataclass
class ReActAgent:
    llm: _LLMLike
    toolbox: dict[str, Tool] = field(default_factory=lambda: dict(DEFAULT_TOOLBOX))
    max_steps: int = 6

    def run(self, task: str) -> tuple[str, list[TraceEntry]]:
        trace: list[TraceEntry] = []
        # scratchpad 累积"思考-行动-观察"历史，下一轮喂给 LLM
        scratchpad = ""

        for _ in range(self.max_steps):
            prompt = self._build_prompt(task, scratchpad)
            output = self.llm.complete(prompt)
            trace.append(TraceEntry("llm", output))

            if _has_final(output):
                final = _extract_final(output)
                trace.append(TraceEntry("final", final))
                return final, trace

            action = _parse_action(output)
            if action is None:
                # 模型既没给 FINAL 也没给可解析的 ACTION，强制退出
                trace.append(TraceEntry("final", "（无法解析模型输出）"))
                return "（无法解析模型输出）", trace

            tool_name, arg = action
            obs = call_tool(self.toolbox, tool_name, arg)
            trace.append(TraceEntry("tool", f"{tool_name}({arg}) -> {obs}"))

            scratchpad += f"{output}\nOBSERVATION: {obs}\n"

        trace.append(TraceEntry("final", "（达到最大步数仍未完成）"))
        return "（达到最大步数仍未完成）", trace

    def _build_prompt(self, task: str, scratchpad: str) -> str:
        tools_desc = "\n".join(f"- {name}(arg): 工具" for name in self.toolbox)
        return (
            "[ReAct] 你是一个会使用工具的 Agent，每轮严格按以下两种格式之一回答，**不要输出额外文字**：\n"
            "格式 A（需要工具）：\n"
            "  THOUGHT: <你的想法>\n"
            "  ACTION: <tool_name>(<argument>)\n"
            "格式 B（已经能给出最终答案）：\n"
            "  THOUGHT: <你的想法>\n"
            "  FINAL: <最终答案>\n\n"
            f"可用工具：\n{tools_desc}\n\n"
            f"任务：{task}\n\n"
            f"历史（上一轮的 ACTION 与 OBSERVATION）：\n{scratchpad or '（空）'}\n"
            "现在请输出你的下一步："
        )


# --------------------------------------------------------------------------- #
# 输出解析：尽量宽松，兼容真实 LLM 可能加的 markdown / 大小写 / 中文冒号
# --------------------------------------------------------------------------- #

# 允许：ACTION: search(x) / **Action**: search(x) / Action：search(x)
# 关键点：参数里可能有嵌套括号（如 calc((1+2)*3)），所以不能简单用 [^)]*。
# 这里用一个最简单的"括号配平"扫描。
_ACTION_HEAD_RE = re.compile(
    r"\**\s*action\s*\**\s*[:：]\s*([a-zA-Z_]+)\s*\(",
    re.IGNORECASE,
)
_FINAL_RE = re.compile(r"\**\s*final\s*\**\s*[:：]\s*(.+)", re.IGNORECASE | re.DOTALL)


def _has_final(text: str) -> bool:
    return _FINAL_RE.search(text) is not None


def _extract_final(text: str) -> str:
    m = _FINAL_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _parse_action(text: str) -> tuple[str, str] | None:
    """从模型输出里抠出 (tool_name, arg)。

    支持嵌套括号的参数（如 `calc((1+2)*3)`），通过括号配平扫描。
    """
    m = _ACTION_HEAD_RE.search(text)
    if not m:
        return None
    tool_name = m.group(1)
    start = m.end()  # 紧跟在 "(" 之后
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return None
    arg = text[start:i].strip().strip("\"'")
    return tool_name, arg
