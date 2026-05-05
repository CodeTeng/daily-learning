# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUntypedBaseClass=false, reportUnannotatedClassAttribute=false, reportUnusedCallResult=false, reportMissingTypeStubs=false
"""Tool Calling 主循环。

把 Function Calling 的完整链路拼起来：

    while 未完成:
        1) 把消息发给 LLM（带上 tools schema）
        2) LLM 可能直接给最终答复 → 结束
           也可能返回 1..N 个 tool_call
        3) 对每个 tool_call：解析参数 → 执行 → 结果封装
        4) 把 tool 结果塞回消息数组，进入下一轮

同时兼顾了生产里必须处理的：

- `max_iterations`：防止模型陷入"调工具 - 看结果 - 再调工具"的死循环
- `parallel tool calls`：一条 assistant 消息可能同时请求多个工具，要并行
- `requires_confirmation`：危险工具必须外部确认，loop 会暂停
- `审计日志`：每次 tool_call / tool_result 都记录，方便事后回放
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from learning_py.tool_calling.registry import (
    ToolCall,
    ToolRegistry,
    ToolResult,
    tool_requires_confirmation,
)


# --------------------------------------------------------------------------- #
# 1. LLM 客户端抽象（方便接不同家的 API）
# --------------------------------------------------------------------------- #

class LLMResponse(BaseModel):
    """一次模型返回的统一抽象。

    - `content`：可选，模型给用户看的文本
    - `tool_calls`：可选，模型想调用的工具列表
    - `extra_assistant_fields`：某些模型（如 DeepSeek V3 / Claude Extended Thinking）
      会附带额外字段（`reasoning_content` / `thinking`），**下一轮必须原样回传**，
      否则 API 会报 400。这里统一兜住。
    """

    # 允许任意额外字段进来，保持最大兼容性
    model_config = ConfigDict(arbitrary_types_allowed=True)

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    extra_assistant_fields: dict[str, Any] = Field(default_factory=dict)


class LLMClient(Protocol):
    """任何 LLM 客户端实现这个协议就能接进 AgentLoop。"""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...


# --------------------------------------------------------------------------- #
# 2. 循环事件：方便上层埋点 / 审计
# --------------------------------------------------------------------------- #

class LoopEvent(BaseModel):
    """主循环里每个关键节点都会发一个事件。

    - kind：llm_response / tool_call / tool_result / needs_confirm / done
    - data：具体负载，不同 kind 语义不同，故用任意 dict
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    data: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 3. 人工确认钩子
# --------------------------------------------------------------------------- #

class ConfirmationRequired(Exception):
    """遇到了需要人工确认的工具调用，loop 暂停并把待确认内容抛出来。"""

    def __init__(self, call: ToolCall, messages: list[dict[str, Any]]) -> None:
        super().__init__(f"工具 {call.name} 需要人工确认")
        self.call = call
        self.messages = messages


# --------------------------------------------------------------------------- #
# 4. 主循环
# --------------------------------------------------------------------------- #

def _no_op_event(_ev: LoopEvent) -> None:
    return None


def _default_confirm(_c: ToolCall) -> bool | None:
    return None


@dataclass
class AgentLoop:
    """最小可用的 Tool Calling 循环。

    使用：

    >>> registry = ToolRegistry()
    >>> @registry.tool()
    ... def add(a: int, b: int) -> int:
    ...     '''两数相加'''
    ...     return a + b

    >>> loop = AgentLoop(llm=MyLLMClient(), registry=registry)
    >>> result = loop.run("帮我算 3+5")
    """

    llm: LLMClient
    registry: ToolRegistry
    max_iterations: int = 8
    parallel_tools: bool = True
    on_event: Callable[[LoopEvent], None] = field(default=_no_op_event)
    # 外部可以预先批准或拒绝某次 tool_call（True=批准 / False=拒绝 / None=按默认策略）
    confirm: Callable[[ToolCall], bool | None] = field(default=_default_confirm)

    def run(
        self,
        user_input: str,
        *,
        system: str | None = None,
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if extra_messages:
            messages.extend(extra_messages)
        messages.append({"role": "user", "content": user_input})

        tools = self.registry.as_openai_tools()

        for _ in range(self.max_iterations):
            resp = self.llm.chat(messages=messages, tools=tools)
            self.on_event(LoopEvent(kind="llm_response", data={"response": resp}))

            # 1) 模型没再调工具 → 收敛，返回文本
            if not resp.tool_calls:
                content = resp.content or ""
                self.on_event(LoopEvent(kind="done", data={"content": content}))
                return content

            # 2) 把 assistant 的 tool_calls 消息先加进去（必须，否则下一轮不合法）
            messages.append(_assistant_tool_calls_message(resp))

            # 3) 危险工具的人工确认
            for call in resp.tool_calls:
                tool = self.registry.tools.get(call.name)
                if tool is None or not tool_requires_confirmation(tool):
                    continue
                decision = self.confirm(call)
                if decision is False:
                    # 被拒绝 → 作为 tool result 告诉模型，让它换方案
                    denial = ToolResult(
                        call_id=call.id, name=call.name, ok=False,
                        error="用户拒绝了该操作",
                    )
                    messages.append(denial.to_openai_message())
                    self.on_event(LoopEvent(kind="tool_result", data={"result": denial}))
                    continue
                if decision is None:
                    # 未批准也未拒绝 → 暂停循环，留给外层处理
                    self.on_event(LoopEvent(kind="needs_confirm", data={"call": call}))
                    raise ConfirmationRequired(call, messages)

            # 4) 真正执行工具（可并行）
            remaining = [
                c for c in resp.tool_calls
                if not _already_denied(messages, c.id)
            ]
            results = self._execute_calls(remaining)
            for r in results:
                messages.append(r.to_openai_message())
                self.on_event(LoopEvent(kind="tool_result", data={"result": r}))

        # 超过最大迭代次数，安全兜底
        self.on_event(LoopEvent(
            kind="done",
            data={"content": "[max_iterations 已达上限]"},
        ))
        return "[max_iterations 已达上限，Agent 未能收敛到最终答案]"

    # ----------------------------------------------------------------- #

    def _execute_calls(self, calls: list[ToolCall]) -> list[ToolResult]:
        if not calls:
            return []
        if not self.parallel_tools or len(calls) == 1:
            results: list[ToolResult] = []
            for c in calls:
                self.on_event(LoopEvent(kind="tool_call", data={"call": c}))
                results.append(self.registry.invoke(c))
            return results

        # 并行执行。**注意**：工具之间不能假设有顺序依赖，否则就该改成串行
        with ThreadPoolExecutor(max_workers=min(len(calls), 8)) as ex:
            futures = []
            for c in calls:
                self.on_event(LoopEvent(kind="tool_call", data={"call": c}))
                futures.append(ex.submit(self.registry.invoke, c))
            return [f.result() for f in futures]


# --------------------------------------------------------------------------- #
# 5. 消息结构化工具
# --------------------------------------------------------------------------- #

def _assistant_tool_calls_message(resp: LLMResponse) -> dict[str, Any]:
    """构造 OpenAI 风格的 `role=assistant, tool_calls=[...]` 消息。

    有些模型（如 DeepSeek V3 / Claude Extended Thinking / o1 系列）在开启
    thinking 模式后，会在 response 里带上 `reasoning_content` 字段，并要求
    **下一轮必须原样回传**，否则 API 直接 400。我们通过 `extra_assistant_fields`
    统一处理这种情况。
    """
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": resp.content or None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in resp.tool_calls
        ],
    }
    for k, v in resp.extra_assistant_fields.items():
        if v is not None:
            msg[k] = v
    return msg


def _already_denied(messages: list[dict[str, Any]], call_id: str) -> bool:
    """看看这个 call_id 是否已经写过一条 role=tool 的结果（被拒就写了）。"""
    for m in reversed(messages):
        if m.get("role") == "tool" and m.get("tool_call_id") == call_id:
            return True
    return False
