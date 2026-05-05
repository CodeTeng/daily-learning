"""Agent 用到的工具箱与执行轨迹辅助类型。

这里**只包含真实可执行的工具**和数据结构，不包含任何 LLM 模拟逻辑。

工具的实现都遵守一条原则：**失败要可观察，不要抛异常**。
工具的返回值会被作为 OBSERVATION 喂回 LLM，模型据此决定下一步——
所以工具失败也要返回字符串，让模型能看到"这条路走不通"，而不是把整个 Agent 弄崩。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


# --------------------------------------------------------------------------- #
# 类型别名
# --------------------------------------------------------------------------- #

Tool = Callable[..., str]


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #

def tool_search(query: str) -> str:
    """玩具级搜索：在内置词典里按关键字找一段简介。

    真实场景里这一步会接 RAG / 搜索引擎 / 内部 API。
    """
    knowledge = {
        "python": "Python 是一种解释型、动态类型、强类型的高级编程语言。",
        "agent": "AI Agent = LLM + 工具 + 记忆 + 目标驱动的循环。",
        "gil": "CPython 的 GIL 让同一进程内同一时刻只有一个线程执行字节码。",
    }
    for k, v in knowledge.items():
        if k in query.lower():
            return v
    return "（未检索到相关资料）"


def tool_calc(expression: str) -> str:
    """安全地计算一个简单算术表达式。

    SECURITY: 不使用 eval。手写一个最小词法 + 递归下降，仅支持 + - * / () 和数字。
    解析或计算失败时**返回错误字符串**（不抛异常），让 Agent 能从 OBSERVATION
    里感知失败并尝试纠正。
    """
    try:
        tokens = _tokenize(expression)
        if not tokens:
            return "（calc 错误：表达式为空）"
        pos = [0]

        def parse_expr() -> float:
            value = parse_term()
            while pos[0] < len(tokens) and tokens[pos[0]] in ("+", "-"):
                op = tokens[pos[0]]
                pos[0] += 1
                rhs = parse_term()
                value = value + rhs if op == "+" else value - rhs
            return value

        def parse_term() -> float:
            value = parse_factor()
            while pos[0] < len(tokens) and tokens[pos[0]] in ("*", "/"):
                op = tokens[pos[0]]
                pos[0] += 1
                rhs = parse_factor()
                value = value * rhs if op == "*" else value / rhs
            return value

        def parse_factor() -> float:
            if pos[0] >= len(tokens):
                raise ValueError("意外的表达式结尾")
            tok = tokens[pos[0]]
            if tok == "(":
                pos[0] += 1
                v = parse_expr()
                if pos[0] >= len(tokens) or tokens[pos[0]] != ")":
                    raise ValueError("缺少右括号")
                pos[0] += 1
                return v
            pos[0] += 1
            return float(tok)

        result = parse_expr()
        if pos[0] != len(tokens):
            return f"（calc 错误：多余字符 {tokens[pos[0]:]}）"
        if result.is_integer():
            return str(int(result))
        return f"{result:.4f}".rstrip("0").rstrip(".")
    except (ValueError, ZeroDivisionError) as e:
        return f"（calc 错误：{e}）"


def _tokenize(expr: str) -> list[str]:
    return re.findall(r"\d+\.?\d*|[+\-*/()]", expr)


def tool_translate(text: str) -> str:
    """玩具级英→中翻译，仅作占位，真实场景请接翻译 API 或让 LLM 自己翻。"""
    table = {
        "hello": "你好",
        "world": "世界",
        "python": "Python",
        "agent": "智能体",
    }
    words = re.findall(r"[A-Za-z]+|[^A-Za-z]+", text)
    return "".join(table.get(w.lower()) or w for w in words)


DEFAULT_TOOLBOX: dict[str, Tool] = {
    "search": tool_search,
    "calc": tool_calc,
    "translate": tool_translate,
}


# --------------------------------------------------------------------------- #
# 执行轨迹与工具调度
# --------------------------------------------------------------------------- #

@dataclass
class TraceEntry:
    """统一的执行轨迹条目，方便 demo 打印 + 测试断言。"""

    kind: str  # "llm" | "tool" | "final"
    payload: Any


def call_tool(toolbox: dict[str, Tool], name: str, arg: str) -> str:
    if name not in toolbox:
        return f"（无此工具：{name}）"
    return toolbox[name](arg)
