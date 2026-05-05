"""Agent 模块的纯逻辑单测。

策略：删掉假 LLM 后，端到端 Agent 测试**需要真实 LLM**（成本高、不确定），
不适合放在 CI。本文件只覆盖与 LLM 无关的纯逻辑：

- 工具实现（calc 解析、错误处理）
- LLM 输出解析器（ACTION / FINAL / PLAN，兼容 markdown / 引号 / 嵌套括号）

端到端验证请运行：
    uv run python -m learning_py.agent.demo
"""

from __future__ import annotations

from learning_py.agent.plan_and_execute import _parse_plan
from learning_py.agent.react_agent import _extract_final, _has_final, _parse_action
from learning_py.agent.tools import call_tool, tool_calc, tool_search, tool_translate


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #

def test_tool_calc_basic() -> None:
    assert tool_calc("1+2+3") == "6"
    assert tool_calc("(1+2)*3") == "9"
    assert tool_calc("10/4") == "2.5"


def test_tool_calc_nested_parens() -> None:
    assert tool_calc("(1+2+3)*4") == "24"
    assert tool_calc("((1+2)*3)+4") == "13"


def test_tool_calc_returns_error_string_on_failure() -> None:
    """工具失败必须**返回字符串**而不是抛异常，让 Agent 能从 OBSERVATION 感知失败。"""
    assert "错误" in tool_calc("(1+2")
    assert "错误" in tool_calc("1++2")
    assert "错误" in tool_calc("")


def test_tool_search_returns_known_or_fallback() -> None:
    assert "Python" in tool_search("python")
    assert "Agent" in tool_search("AGENT")
    assert "未检索到" in tool_search("不存在的关键字")


def test_tool_translate_handles_known_words() -> None:
    out = tool_translate("hello world")
    assert "你好" in out and "世界" in out


def test_call_tool_unknown_returns_message() -> None:
    out = call_tool({}, "no_such", "x")
    assert "无此工具" in out


# --------------------------------------------------------------------------- #
# ReAct 输出解析器：必须容忍真实 LLM 的 markdown / 引号 / 嵌套括号
# --------------------------------------------------------------------------- #

def test_parse_action_handles_quotes_and_markdown() -> None:
    # DeepSeek 实测会输出 `ACTION: search("xxx")` 或 `**ACTION**: ...`
    assert _parse_action('ACTION: search("Python 语言")') == ("search", "Python 语言")
    assert _parse_action("**Action**: calc('1+2')") == ("calc", "1+2")
    # 中文冒号
    assert _parse_action("ACTION：search(agent)") == ("search", "agent")


def test_parse_action_handles_nested_parens() -> None:
    """参数本身就含括号：calc((1+2)*3)。"""
    assert _parse_action("ACTION: calc((1+2)*3)") == ("calc", "(1+2)*3")
    assert _parse_action('ACTION: calc("(1+2+3)*4")') == ("calc", "(1+2+3)*4")


def test_parse_action_returns_none_for_garbage() -> None:
    assert _parse_action("just some text") is None
    assert _parse_action("ACTION: malformed_no_parens") is None


def test_has_final_and_extract_final() -> None:
    text = "THOUGHT: 想好了\nFINAL: 答案就是 42。"
    assert _has_final(text)
    assert _extract_final(text) == "答案就是 42。"

    assert not _has_final("THOUGHT: 还需要继续")


# --------------------------------------------------------------------------- #
# Plan-and-Execute 输出解析器
# --------------------------------------------------------------------------- #

def test_parse_plan_handles_nested_parens() -> None:
    plan_text = (
        "1. search(Python)\n"
        "2. calc((1+2+3)*4)\n"
        "3. finalize\n"
    )
    assert _parse_plan(plan_text) == [
        ("search", "Python"),
        ("calc", "(1+2+3)*4"),
        "finalize",
    ]


def test_parse_plan_strips_markdown_decoration() -> None:
    plan_text = (
        "1. **search(Python)**\n"
        "2. `calc(1+2)`\n"
        "3. finalize\n"
    )
    assert _parse_plan(plan_text) == [
        ("search", "Python"),
        ("calc", "1+2"),
        "finalize",
    ]


def test_parse_plan_ignores_non_step_lines() -> None:
    plan_text = (
        "好的，下面是计划：\n"
        "1. search(Python)\n"
        "（最后一步收尾）\n"
        "2. finalize\n"
    )
    assert _parse_plan(plan_text) == [("search", "Python"), "finalize"]
