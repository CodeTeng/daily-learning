# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUntypedBaseClass=false, reportUnannotatedClassAttribute=false, reportUnusedCallResult=false, reportMissingTypeStubs=false
"""工具注册表 + 参数解析 + 安全执行。

对应"工具调用"四步骤里的后两步：**参数解析** 和 **执行与结果返回**。

关键工程问题：

- LLM 吐出来的是 **JSON 字符串**，不是 Python 对象。要先解析、再按类型校验、
  再补默认值、再才能喂给函数 —— 中间任何一步失败，都要**返回结构化错误
  给 LLM**，而不是崩掉整个 Agent。
- 执行阶段要有**超时、异常隔离、结果截断**三件套，不然一个死循环工具
  就能把整个 Agent 卡住。
- 工具结果必须**转成字符串**才能塞回下一轮上下文。对象要 json.dumps，
  dict/list 同理；结果过大要截断并告诉 LLM "已截断"。

参数解析改用 **Pydantic `TypeAdapter`** 来做：
- 类型校验和转换（"3" → 3）它天生会做，不用自己手写 coerce
- 校验失败的 error message 结构化，可以直接喂回给 LLM
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from learning_py.tool_calling.schema import (
    ToolDefinition,
    build_tool_definition,
)


# --------------------------------------------------------------------------- #
# 1. 调用与结果的数据结构（Pydantic 模型）
# --------------------------------------------------------------------------- #

class ToolCall(BaseModel):
    """LLM 请求调用某个工具时产生的一条记录。

    OpenAI 的 tool_call 里 `arguments` 是 JSON 字符串（model 直接吐的），
    这里保留原始字符串，解析交给 `ToolRegistry` 统一做。
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="本次调用的唯一 id，用于和结果配对")
    name: str = Field(..., description="工具名")
    arguments: str = Field(default="{}", description="JSON 字符串形式的参数")


class ToolResult(BaseModel):
    """工具执行完的结果。无论成功失败都用这个结构回传给 LLM。"""

    call_id: str
    name: str
    ok: bool
    content: str = Field(default="", description="结果文本（JSON 化后截断）")
    error: str | None = None

    def to_openai_message(self) -> dict[str, Any]:
        """转成 OpenAI messages 里 role=tool 的那条消息。"""
        return {
            "role": "tool",
            "tool_call_id": self.call_id,
            "name": self.name,
            "content": self.content if self.ok else f"[ERROR] {self.error}",
        }


# --------------------------------------------------------------------------- #
# 2. 错误类型
# --------------------------------------------------------------------------- #

class ToolNotFoundError(Exception):
    pass


class ToolArgumentError(Exception):
    """参数解析/校验失败。对 LLM 是"可重试"的错误：它下一轮会修正。"""


# --------------------------------------------------------------------------- #
# 3. 工具注册表
# --------------------------------------------------------------------------- #

class ToolRegistry:
    """注册工具 + 生成 schema + 解析参数 + 调用执行。

    典型用法：

    >>> registry = ToolRegistry()
    >>> @registry.tool()
    ... def add(a: int, b: int) -> int:
    ...     '''把两个整数相加。'''
    ...     return a + b
    >>> registry.as_openai_tools()[0]["function"]["name"]
    'add'
    """

    def __init__(
        self,
        *,
        default_timeout: float = 10.0,
        max_result_chars: int = 4000,
    ) -> None:
        self.tools: dict[str, ToolDefinition] = {}
        self.default_timeout = default_timeout
        self.max_result_chars = max_result_chars

    # --- 注册 -----------------------------------------------------------

    def register(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> ToolDefinition:
        tool = build_tool_definition(fn, name=name, description=description)
        if tool.name in self.tools:
            raise ValueError(f"工具名重复：{tool.name}")
        self.tools[tool.name] = tool
        return tool

    def tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """装饰器形式，便于贴在业务函数上。"""

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(fn, name=name, description=description)
            return fn

        return deco

    # --- 导出 Schema ----------------------------------------------------

    def as_openai_tools(self) -> list[dict[str, Any]]:
        return [t.to_openai_tool() for t in self.tools.values()]

    def as_anthropic_tools(self) -> list[dict[str, Any]]:
        return [t.to_anthropic_tool() for t in self.tools.values()]

    # --- 参数解析（最容易出问题的地方） --------------------------------

    def parse_arguments(self, name: str, arguments: str) -> dict[str, Any]:
        """把 LLM 吐出的 JSON 字符串解析 + 用 Pydantic 校验类型 + 补默认值。

        内部流程：
        1) `json.loads`（非法 JSON → `ToolArgumentError`）
        2) 丢弃 schema 里没有的键（防止 LLM 塞奇怪字段导致 TypeError）
        3) 交给每个参数的 `TypeAdapter` 校验 + 转换
           （Pydantic 会把 `"3"` 自动转成 `3`，我们不用自己写 coerce 逻辑）
        4) 必填缺失或类型错 → 把 Pydantic 的错误聚合成人类可读的字符串
        """
        tool = self.tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"未知工具：{name}")

        # 1) JSON 解析
        try:
            raw: Any = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as e:
            raise ToolArgumentError(f"arguments 不是合法 JSON：{e}") from e

        if not isinstance(raw, dict):
            raise ToolArgumentError(
                f"arguments 必须是 JSON 对象，实际是 {type(raw).__name__}"
            )

        properties = tool.parameters_schema.get("properties", {})
        required: list[str] = list(tool.parameters_schema.get("required", []))

        # 2) 丢未知字段
        candidate: dict[str, Any] = {k: v for k, v in raw.items() if k in properties}

        # 3) 必填校验（放在类型校验前，给出更明确的错误信息）
        missing = [r for r in required if r not in candidate]
        if missing:
            raise ToolArgumentError(
                f"缺少必填参数：{', '.join(missing)}"
            )

        # 4) 用每个参数的 TypeAdapter 做类型校验 + 转换
        errors: list[str] = []
        validated: dict[str, Any] = {}
        for key, value in candidate.items():
            adapter = tool.param_adapters.get(key)
            if adapter is None:
                validated[key] = value
                continue
            try:
                validated[key] = adapter.validate_python(value)
            except ValidationError as e:
                # Pydantic 的 error 很详细，挑第一条的 msg 即可
                first = e.errors()[0]
                errors.append(f"{key}: {first.get('msg', 'validation error')}")

        if errors:
            raise ToolArgumentError("参数类型错误：" + "；".join(errors))

        return validated

    # --- 执行 -----------------------------------------------------------

    def invoke(
        self,
        call: ToolCall,
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        """执行一个工具调用，**永远返回 `ToolResult`，不会抛异常**。

        设计要点：
        - 把参数解析错误、执行异常、超时都统一包装成 `ToolResult(ok=False)`
        - 因为对 LLM 来讲，这些错误都是"下一轮可以修正"的信息
        """
        effective_timeout = self.default_timeout if timeout is None else timeout

        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error=f"未知工具：{call.name}",
            )

        # 1) 解析参数
        try:
            kwargs = self.parse_arguments(call.name, call.arguments)
        except ToolArgumentError as e:
            return ToolResult(
                call_id=call.id, name=call.name, ok=False, error=str(e),
            )

        # 2) 带超时执行
        try:
            result = _run_with_timeout(tool.fn, kwargs, timeout=effective_timeout)
        except TimeoutError as e:
            return ToolResult(
                call_id=call.id, name=call.name, ok=False, error=str(e),
            )
        except Exception as e:
            # 业务异常也转成结构化错误，让 LLM 看到后决定下一步
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error=f"{type(e).__name__}: {e}",
            )

        # 3) 结果 → 字符串 + 截断
        content = _result_to_text(result, self.max_result_chars)
        return ToolResult(
            call_id=call.id, name=call.name, ok=True, content=content,
        )


# --------------------------------------------------------------------------- #
# 4. 内部工具函数
# --------------------------------------------------------------------------- #

def _run_with_timeout(
    fn: Callable[..., Any],
    kwargs: dict[str, Any],
    *,
    timeout: float,
) -> Any:
    """用线程跑目标函数，超时抛 TimeoutError。

    注意：线程模式**不能真正杀掉** Python 代码，只能放弃等待。工具函数
    自己要有"协作式取消"的能力（比如 requests 的 timeout=）。这里的超时
    主要是"不让 Agent 主循环卡住"的兜底。
    """
    if timeout <= 0:
        return fn(**kwargs)

    holder: dict[str, Any] = {}

    def target() -> None:
        try:
            holder["result"] = fn(**kwargs)
        except BaseException as exc:  # 连带 KeyboardInterrupt 一起托住
            holder["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"工具执行超过 {timeout}s")
    exc = holder.get("exc")
    if exc is not None:
        assert isinstance(exc, BaseException)
        raise exc
    return holder.get("result")


def _result_to_text(result: Any, max_chars: int) -> str:
    """把任意返回值转成给 LLM 看的字符串。"""
    if result is None:
        text = "null"
    elif isinstance(result, str):
        text = result
    elif isinstance(result, BaseModel):
        text = result.model_dump_json()
    elif isinstance(result, (dict, list, tuple, int, float, bool)):
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
    else:
        text = str(result)

    if len(text) > max_chars:
        head = text[:max_chars]
        return (
            f"{head}\n...[结果被截断，原始长度 {len(text)} 字符，"
            f"当前上限 {max_chars}]"
        )
    return text


# --------------------------------------------------------------------------- #
# 5. 工具副作用标记（安全相关）
# --------------------------------------------------------------------------- #

def requires_confirmation(fn: Callable[..., Any]) -> Callable[..., Any]:
    """给带副作用的工具打标：删库、打款、发邮件 —— 线上必须人工确认。

    只是加一个 `__requires_confirmation__ = True` 属性，具体在 Agent loop
    里再决定"是否真的停下来问人"，见 `loop.py` 的 `AgentLoop`。
    """
    setattr(fn, "__requires_confirmation__", True)
    return fn


def tool_requires_confirmation(tool: ToolDefinition) -> bool:
    return bool(getattr(tool.fn, "__requires_confirmation__", False))


# 显式 re-export，让 IDE / 静态检查器看清对外 API
__all__ = [
    "ToolCall",
    "ToolResult",
    "ToolRegistry",
    "ToolNotFoundError",
    "ToolArgumentError",
    "requires_confirmation",
    "tool_requires_confirmation",
    "TypeAdapter",  # 给 schema.py 的 ToolDefinition 用
]
