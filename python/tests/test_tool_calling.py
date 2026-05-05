"""tool_calling 模块的单元测试（Pydantic 版本）。

覆盖：schema 生成、参数解析、执行兜底、AgentLoop 主循环、危险工具确认。

注：本文件里的 `_ScriptedLLM` 是**单元测试专用 stub**（不是业务代码里的
mock），作用等同于 `unittest.mock.MagicMock`，用于在不调用真实 LLM 的前提下
验证主循环的行为。生产/demo 代码已全部接入真实 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from pydantic import BaseModel as _BaseModel

from learning_py.tool_calling.loop import (
    AgentLoop,
    ConfirmationRequired,
    LLMResponse,
    LoopEvent,
)
from learning_py.tool_calling.registry import (
    ToolArgumentError,
    ToolCall,
    ToolRegistry,
    requires_confirmation,
    tool_requires_confirmation,
)
from learning_py.tool_calling.schema import (
    build_tool_definition,
    parse_docstring,
)


# 测试专用的模块级 BaseModel，保证 get_type_hints 能找到
class _UserForTest(_BaseModel):
    id: int
    name: str


# --------------------------------------------------------------------------- #
# schema.py：通过 build_tool_definition 间接验证 Pydantic 生成的 schema
# --------------------------------------------------------------------------- #

class TestSchemaGeneration:
    def test_primitives(self) -> None:
        def fn(a: int, b: str, c: float, d: bool) -> None:
            """demo"""

        td = build_tool_definition(fn)
        props = td.parameters_schema["properties"]
        assert props["a"]["type"] == "integer"
        assert props["b"]["type"] == "string"
        assert props["c"]["type"] == "number"
        assert props["d"]["type"] == "boolean"

    def test_optional(self) -> None:
        def fn(x: int | None = None) -> None:
            """demo"""

        td = build_tool_definition(fn)
        prop = td.parameters_schema["properties"]["x"]
        # Pydantic 对 Optional 生成 anyOf，两个分支里一个是 integer、一个是 null
        assert "anyOf" in prop
        types_in_any_of = {sub.get("type") for sub in prop["anyOf"]}
        assert "integer" in types_in_any_of
        assert "null" in types_in_any_of

    def test_literal(self) -> None:
        def fn(unit: Literal["c", "f"]) -> None:
            """demo"""

        td = build_tool_definition(fn)
        prop = td.parameters_schema["properties"]["unit"]
        assert prop.get("enum") == ["c", "f"]

    def test_list(self) -> None:
        def fn(tags: list[str]) -> None:
            """demo"""

        td = build_tool_definition(fn)
        prop = td.parameters_schema["properties"]["tags"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "string"

    def test_title_is_stripped(self) -> None:
        # Pydantic 默认会给每个字段挂 title，我们的 _strip_pydantic_noise 会清掉
        def fn(city: str) -> None:
            """demo"""

        td = build_tool_definition(fn)
        assert "title" not in td.parameters_schema
        assert "title" not in td.parameters_schema["properties"]["city"]


class TestDocstring:
    def test_google_style(self) -> None:
        doc = """Do something.

        Args:
            x: the x value.
            y: the y value.

        Returns:
            whatever.
        """
        summary, params = parse_docstring(doc)
        assert summary == "Do something."
        assert params == {"x": "the x value.", "y": "the y value."}

    def test_sphinx_style(self) -> None:
        doc = """Do something.

        :param x: first param
        :param y: second param
        """
        summary, params = parse_docstring(doc)
        assert summary.startswith("Do something")
        assert params == {"x": "first param", "y": "second param"}

    def test_none_docstring(self) -> None:
        assert parse_docstring(None) == ("", {})


class TestBuildToolDefinition:
    def test_required_and_default(self) -> None:
        def fn(a: int, b: str = "hi") -> str:
            """A demo tool.

            Args:
                a: 必填整数
                b: 可选字符串
            """
            return f"{a}-{b}"

        td = build_tool_definition(fn)
        params = td.parameters_schema
        assert params["required"] == ["a"]
        assert params["properties"]["a"]["description"] == "必填整数"
        assert params["properties"]["b"]["default"] == "hi"
        assert td.description == "A demo tool."

    def test_openai_tool_schema(self) -> None:
        def add(a: int, b: int) -> int:
            """加法"""
            return a + b

        td = build_tool_definition(add)
        t = td.to_openai_tool()
        assert t["type"] == "function"
        assert t["function"]["name"] == "add"
        assert "properties" in t["function"]["parameters"]

    def test_var_args_ignored(self) -> None:
        def fn(a: int, *args: int, **kwargs: Any) -> int:
            return a

        td = build_tool_definition(fn)
        assert list(td.parameters_schema["properties"].keys()) == ["a"]

    def test_param_adapters_populated(self) -> None:
        def fn(a: int, b: str = "hi") -> str:
            """demo"""
            return f"{a}-{b}"

        td = build_tool_definition(fn)
        assert set(td.param_adapters.keys()) == {"a", "b"}


# --------------------------------------------------------------------------- #
# registry.py
# --------------------------------------------------------------------------- #

@pytest.fixture
def reg() -> ToolRegistry:
    r = ToolRegistry()

    @r.tool()
    def add(a: int, b: int = 1) -> int:
        """两数相加

        Args:
            a: 第一个数
            b: 第二个数
        """
        return a + b

    @r.tool()
    def echo(text: str) -> str:
        """原样返回"""
        return text

    return r


class TestParseArguments:
    def test_happy(self, reg: ToolRegistry) -> None:
        assert reg.parse_arguments("add", '{"a": 1, "b": 2}') == {"a": 1, "b": 2}

    def test_missing_required(self, reg: ToolRegistry) -> None:
        with pytest.raises(ToolArgumentError, match="必填"):
            reg.parse_arguments("add", '{"b": 2}')

    def test_invalid_json(self, reg: ToolRegistry) -> None:
        with pytest.raises(ToolArgumentError, match="JSON"):
            reg.parse_arguments("add", "not-json")

    def test_coerces_string_to_int(self, reg: ToolRegistry) -> None:
        # Pydantic 默认能把数字字符串转成 int（LLM 常见行为）
        assert reg.parse_arguments("add", '{"a": "3", "b": "4"}') == {"a": 3, "b": 4}

    def test_type_error_caught(self, reg: ToolRegistry) -> None:
        # 真正的类型错误（无法转换的字符串）应该被 Pydantic 拦截
        with pytest.raises(ToolArgumentError, match="类型错误"):
            reg.parse_arguments("add", '{"a": "not-a-number", "b": 1}')

    def test_drops_unknown_field(self, reg: ToolRegistry) -> None:
        result = reg.parse_arguments("add", '{"a": 1, "evil": 999}')
        assert "evil" not in result

    def test_empty_uses_defaults(self, reg: ToolRegistry) -> None:
        # add 有 a 必填 → 仍然报错
        with pytest.raises(ToolArgumentError):
            reg.parse_arguments("add", "")


class TestInvoke:
    def test_happy(self, reg: ToolRegistry) -> None:
        res = reg.invoke(ToolCall(id="1", name="add", arguments='{"a": 2, "b": 3}'))
        assert res.ok is True
        assert res.content == "5"

    def test_unknown_tool(self, reg: ToolRegistry) -> None:
        res = reg.invoke(ToolCall(id="1", name="nope", arguments="{}"))
        assert res.ok is False
        assert "未知工具" in (res.error or "")

    def test_bad_args(self, reg: ToolRegistry) -> None:
        res = reg.invoke(ToolCall(id="1", name="add", arguments="?"))
        assert res.ok is False

    def test_business_exception_caught(self) -> None:
        r = ToolRegistry()

        @r.tool()
        def boom() -> None:
            """总是炸"""
            raise RuntimeError("kaboom")

        res = r.invoke(ToolCall(id="1", name="boom", arguments="{}"))
        assert res.ok is False
        assert "kaboom" in (res.error or "")

    def test_result_to_message(self, reg: ToolRegistry) -> None:
        res = reg.invoke(ToolCall(id="42", name="echo", arguments='{"text": "hi"}'))
        msg = res.to_openai_message()
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "42"
        assert msg["content"] == "hi"

    def test_result_truncation(self) -> None:
        r = ToolRegistry(max_result_chars=20)

        @r.tool()
        def big() -> str:
            """返回超长字符串"""
            return "A" * 1000

        res = r.invoke(ToolCall(id="1", name="big", arguments="{}"))
        assert res.ok is True
        assert "截断" in res.content
        assert len(res.content) < 1000

    def test_timeout(self) -> None:
        import time as _t
        r = ToolRegistry(default_timeout=0.05)

        @r.tool()
        def slow() -> str:
            """会睡很久"""
            _t.sleep(0.2)
            return "ok"

        res = r.invoke(ToolCall(id="1", name="slow", arguments="{}"))
        assert res.ok is False
        assert "超过" in (res.error or "")

    def test_duplicate_tool_name(self) -> None:
        r = ToolRegistry()

        @r.tool()
        def add(a: int, b: int) -> int:  # noqa: ARG001
            """加"""
            return a + b

        with pytest.raises(ValueError):
            r.register(add)

    def test_result_serializes_basemodel(self) -> None:
        r = ToolRegistry()

        @r.tool()
        def get_user() -> _UserForTest:
            """取用户"""
            return _UserForTest(id=1, name="alice")

        res = r.invoke(ToolCall(id="1", name="get_user", arguments="{}"))
        assert res.ok is True
        assert '"name":"alice"' in res.content.replace(" ", "")


class TestConfirmationMarker:
    def test_marker_applied(self) -> None:
        @requires_confirmation
        def send() -> None:
            return None

        assert getattr(send, "__requires_confirmation__") is True

    def test_tool_requires_confirmation(self) -> None:
        r = ToolRegistry()

        @r.tool()
        @requires_confirmation
        def drop_db() -> str:
            """删库"""
            return "gone"

        assert tool_requires_confirmation(r.tools["drop_db"]) is True


# --------------------------------------------------------------------------- #
# loop.py：用测试专用 stub 验证主循环（不联网）
# --------------------------------------------------------------------------- #

@dataclass
class _ScriptedLLM:
    """测试专用 stub，等同 `unittest.mock.MagicMock(spec=LLMClient)`。"""

    script: list[LLMResponse]
    seen: list[list[dict[str, Any]]] = field(default_factory=list)
    _idx: int = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        self.seen.append([dict(m) for m in messages])
        if self._idx >= len(self.script):
            return LLMResponse(content="(ran out)")
        r = self.script[self._idx]
        self._idx += 1
        return r


class TestAgentLoop:
    def test_direct_answer_no_tools(self, reg: ToolRegistry) -> None:
        llm = _ScriptedLLM(script=[LLMResponse(content="hi there")])
        loop = AgentLoop(llm=llm, registry=reg)
        assert loop.run("hello") == "hi there"

    def test_single_tool_roundtrip(self, reg: ToolRegistry) -> None:
        llm = _ScriptedLLM(script=[
            LLMResponse(tool_calls=[
                ToolCall(id="c1", name="add", arguments='{"a": 2, "b": 3}'),
            ]),
            LLMResponse(content="答案是 5"),
        ])
        loop = AgentLoop(llm=llm, registry=reg)
        assert loop.run("2+3=?") == "答案是 5"
        # 第二轮 LLM 应该能看到 tool result
        second_round_messages = llm.seen[1]
        tool_msgs = [m for m in second_round_messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "5"

    def test_parallel_tool_calls(self, reg: ToolRegistry) -> None:
        llm = _ScriptedLLM(script=[
            LLMResponse(tool_calls=[
                ToolCall(id="c1", name="add", arguments='{"a": 1, "b": 2}'),
                ToolCall(id="c2", name="echo", arguments='{"text": "hi"}'),
            ]),
            LLMResponse(content="done"),
        ])
        events: list[LoopEvent] = []
        loop = AgentLoop(llm=llm, registry=reg, on_event=events.append)
        assert loop.run("go") == "done"
        results = [e for e in events if e.kind == "tool_result"]
        assert len(results) == 2

    def test_max_iterations(self, reg: ToolRegistry) -> None:
        endless = [
            LLMResponse(tool_calls=[
                ToolCall(id=f"c{i}", name="add", arguments='{"a":1,"b":1}'),
            ])
            for i in range(100)
        ]
        llm = _ScriptedLLM(script=endless)
        loop = AgentLoop(llm=llm, registry=reg, max_iterations=3)
        answer = loop.run("loop forever")
        assert "max_iterations" in answer

    def test_confirm_denied(self) -> None:
        r = ToolRegistry()

        @r.tool()
        @requires_confirmation
        def drop_db(db_name: str) -> str:
            """删库"""
            return f"{db_name} dropped"

        llm = _ScriptedLLM(script=[
            LLMResponse(tool_calls=[
                ToolCall(id="c1", name="drop_db", arguments='{"db_name":"prod"}'),
            ]),
            LLMResponse(content="好的我没执行"),
        ])
        loop = AgentLoop(llm=llm, registry=r, confirm=lambda _c: False)
        answer = loop.run("删库")
        assert answer == "好的我没执行"
        tool_msgs = [m for m in llm.seen[1] if m["role"] == "tool"]
        assert any("用户拒绝" in (m["content"] or "") for m in tool_msgs)

    def test_confirm_pending_raises(self) -> None:
        r = ToolRegistry()

        @r.tool()
        @requires_confirmation
        def send() -> str:
            """发邮件"""
            return "sent"

        llm = _ScriptedLLM(script=[
            LLMResponse(tool_calls=[
                ToolCall(id="c1", name="send", arguments="{}"),
            ]),
        ])
        loop = AgentLoop(llm=llm, registry=r, confirm=lambda _c: None)
        with pytest.raises(ConfirmationRequired) as exc:
            loop.run("send it")
        assert exc.value.call.name == "send"

    def test_reasoning_content_passed_back(self, reg: ToolRegistry) -> None:
        """DeepSeek / Claude Extended Thinking 要求 reasoning_content 必须回传。"""
        llm = _ScriptedLLM(script=[
            LLMResponse(
                tool_calls=[ToolCall(id="c1", name="add",
                                     arguments='{"a": 1, "b": 2}')],
                extra_assistant_fields={"reasoning_content": "我先用 add 工具算一下。"},
            ),
            LLMResponse(content="结果是 3"),
        ])
        loop = AgentLoop(llm=llm, registry=reg)
        assert loop.run("1+2") == "结果是 3"

        second_round = llm.seen[1]
        assistant_msg = next(m for m in second_round if m["role"] == "assistant")
        assert assistant_msg.get("reasoning_content") == "我先用 add 工具算一下。"


# --------------------------------------------------------------------------- #
# openai_client.LLMConfig：Pydantic 校验
# --------------------------------------------------------------------------- #

class TestLLMConfig:
    def test_valid(self) -> None:
        from learning_py.tool_calling.openai_client import LLMConfig

        c = LLMConfig(api_key="sk-x", model="gpt-4o-mini")
        assert c.api_key == "sk-x"
        assert c.base_url is None

    def test_base_url_normalized(self) -> None:
        from learning_py.tool_calling.openai_client import LLMConfig

        c = LLMConfig(api_key="k", model="m", base_url="https://x.com/  ")
        # 会被清理成不带尾斜杠的 url
        assert c.base_url == "https://x.com"

    def test_base_url_invalid(self) -> None:
        from pydantic import ValidationError
        from learning_py.tool_calling.openai_client import LLMConfig

        with pytest.raises(ValidationError):
            LLMConfig(api_key="k", model="m", base_url="ftp://x.com")

    def test_empty_api_key_rejected(self) -> None:
        from pydantic import ValidationError
        from learning_py.tool_calling.openai_client import LLMConfig

        with pytest.raises(ValidationError):
            LLMConfig(api_key="", model="m")
