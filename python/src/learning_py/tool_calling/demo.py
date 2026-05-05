"""把 Tool Calling 四步骤串起来跑的 Demo。

**要求**：`python/.env` 里需要配置好 LLM_API_KEY / LLM_MODEL / LLM_BASE_URL，
本 demo 会真的发请求到 LLM。

运行：
    uv run python -m learning_py.tool_calling.demo

覆盖的四个学习点：

1. **工具定义和描述** —— 把 Python 函数 → OpenAI tools JSON schema
2. **工具参数解析** —— 用 Pydantic 做类型校验，非法输入不让到达业务函数
3. **工具执行和结果返回** —— 超时 / 异常 / 截断 三件套兜底
4. **Function Calling 完整循环** —— 真实 LLM 自主选工具、并行调用、合成答复
"""

from __future__ import annotations

import json

from learning_py.tool_calling.loop import AgentLoop, LoopEvent
from learning_py.tool_calling.openai_client import LLMConfig, OpenAILLMClient
from learning_py.tool_calling.registry import (
    ToolCall,
    ToolRegistry,
    requires_confirmation,
)


# --------------------------------------------------------------------------- #
# 1. 准备几个工具 —— 就像真实项目里散落的业务函数
# --------------------------------------------------------------------------- #

registry = ToolRegistry()


@registry.tool()
def get_weather(city: str, unit: str = "c") -> dict[str, object]:
    """查询指定城市的当前天气。

    Args:
        city: 城市中文名，如 "北京"。
        unit: 温度单位，"c"=摄氏度，"f"=华氏度。
    """
    # 真实场景：调气象 API。这里写死返回值便于演示。
    data: dict[str, dict[str, object]] = {
        "北京": {"c": 22, "desc": "晴"},
        "上海": {"c": 26, "desc": "多云"},
        "深圳": {"c": 30, "desc": "雷阵雨"},
    }
    row = data.get(city, {"c": 20, "desc": "未知"})
    celsius = float(row["c"])  # type: ignore[arg-type]
    temp = celsius if unit == "c" else round(celsius * 9 / 5 + 32, 1)
    return {
        "city": city,
        "temperature": temp,
        "unit": unit,
        "description": row["desc"],
    }


@registry.tool()
def calculate(expression: str) -> float:
    """计算一个算术表达式，只支持 + - * / ( ) 和数字。

    Args:
        expression: 要计算的算术表达式字符串。
    """
    # 真实场景里别直接 eval —— 这里用 AST 白名单做安全计算
    import ast
    import operator as op

    allowed_op = {
        ast.Add: op.add, ast.Sub: op.sub,
        ast.Mult: op.mul, ast.Div: op.truediv,
        ast.USub: op.neg, ast.UAdd: op.pos,
    }

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_op:
            return allowed_op[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_op:
            return allowed_op[type(node.op)](_eval(node.operand))
        raise ValueError(f"不允许的表达式节点：{ast.dump(node)}")

    return _eval(ast.parse(expression, mode="eval"))


@registry.tool()
@requires_confirmation  # 带副作用的危险工具：线上必须人工确认
def send_email(to: str, subject: str, body: str) -> str:
    """向指定邮箱发送一封邮件（带副作用，线上必须人工确认）。

    Args:
        to: 收件人邮箱。
        subject: 邮件标题。
        body: 邮件正文。
    """
    # 真实实现在这里调 SMTP
    return f"邮件已发送给 {to}，主题：{subject}"


# --------------------------------------------------------------------------- #
# 辅助打印
# --------------------------------------------------------------------------- #

def _title(s: str) -> None:
    line = "=" * 64
    print(f"\n{line}\n{s}\n{line}")


# --------------------------------------------------------------------------- #
# 2. Demo 1：工具定义 —— 自动生成的 JSON Schema
# --------------------------------------------------------------------------- #

def demo_schema() -> None:
    _title("1. 工具定义：Python 函数 + 类型注解 → OpenAI tools schema")
    tools = registry.as_openai_tools()
    print(json.dumps(tools, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# 3. Demo 2：工具参数解析（Pydantic 校验）
# --------------------------------------------------------------------------- #

def demo_parse_arguments() -> None:
    _title("2. 工具参数解析：JSON 字符串 → Python kwargs（Pydantic 校验 + 类型转换）")

    good = registry.parse_arguments("get_weather", '{"city": "北京", "unit": "f"}')
    print("✅ 正常解析:", good)

    # Pydantic 自动把字符串数字转成 float
    print("✅ 类型转换（字符串 -> 数字）：", end=" ")
    # 造一个有 int/float 参数的小工具演示
    demo_reg = ToolRegistry()

    @demo_reg.tool()
    def times(a: int, b: float) -> float:
        """两数相乘"""
        return a * b

    print(demo_reg.parse_arguments("times", '{"a": "3", "b": "2.5"}'))

    # 错误：缺必填
    try:
        registry.parse_arguments("get_weather", '{"unit": "c"}')
    except Exception as e:
        print("❌ 缺必填被拦截:", type(e).__name__, str(e))

    # 错误：非法 JSON
    try:
        registry.parse_arguments("get_weather", "not-a-json")
    except Exception as e:
        print("❌ JSON 非法被拦截:", type(e).__name__, str(e))

    # 错误：类型错（传不能被强转的字符串给 int）
    try:
        demo_reg.parse_arguments("times", '{"a": "not-an-int", "b": 2}')
    except Exception as e:
        print("❌ 类型错误被拦截:", type(e).__name__, str(e))


# --------------------------------------------------------------------------- #
# 4. Demo 3：工具执行和错误兜底
# --------------------------------------------------------------------------- #

def demo_execute() -> None:
    _title("3. 工具执行与结果封装：超时 / 异常 / 截断 三件套")

    call = ToolCall(id="c1", name="get_weather", arguments='{"city": "上海"}')
    result = registry.invoke(call)
    print("调用成功，content =", result.content)
    print("回传给 LLM 的消息:", result.to_openai_message())

    # 未知工具：不抛异常，返回结构化错误
    bad = registry.invoke(ToolCall(id="c2", name="not_exist", arguments="{}"))
    print("\n未知工具（不抛异常，返回结构化错误）:")
    print(" ", bad.model_dump())

    # 业务函数内部报错（除零）
    err = registry.invoke(ToolCall(
        id="c3", name="calculate", arguments='{"expression": "3/0"}',
    ))
    print("\n业务异常被包住:")
    print(" ", err.model_dump())


# --------------------------------------------------------------------------- #
# 5. Demo 4：真实 LLM Tool Calling 完整循环
# --------------------------------------------------------------------------- #

def _print_event(ev: LoopEvent) -> None:
    """把事件流简洁地打到终端，便于观察 Agent 的每一步。"""
    if ev.kind == "llm_response":
        resp = ev.data["response"]
        n = len(resp.tool_calls)
        text = (resp.content or "").strip()
        if n:
            tail = f"；同时说：{text[:60]!r}" if text else ""
            print(f"  [llm]  → 想调 {n} 个工具{tail}")
        else:
            print(f"  [llm]  → 最终答复：{text}")
    elif ev.kind == "tool_call":
        c: ToolCall = ev.data["call"]
        print(f"  [call] {c.name}({c.arguments})")
    elif ev.kind == "tool_result":
        r = ev.data["result"]
        label = "ok" if r.ok else "ERR"
        body = r.content if r.ok else r.error
        print(f"  [ret]  {r.name}[{label}] → {str(body)[:200]}")
    elif ev.kind == "needs_confirm":
        c = ev.data["call"]
        print(f"  [!]    工具 {c.name} 需要人工确认：{c.arguments}")


def demo_real_llm() -> None:
    """真的发请求给 LLM，观察它如何自主选择工具、传参、合成最终答复。"""
    _title("4. 真实 LLM 调用：让模型自己选工具 + 传参 + 合成答案")

    try:
        config = LLMConfig.from_env()
    except RuntimeError as e:
        print(f"[跳过] {e}")
        return

    print(f"使用模型: {config.model}")
    if config.base_url:
        print(f"自定义 base_url: {config.base_url}")
    print(
        f"采样参数: temperature={config.sampling.temperature}, "
        f"max_tokens={config.sampling.max_tokens}\n"
    )

    client = OpenAILLMClient(config)

    # 自动拒绝所有危险工具：演示 `requires_confirmation` 机制
    loop = AgentLoop(
        llm=client,
        registry=registry,
        on_event=_print_event,
        parallel_tools=True,
        max_iterations=5,
        confirm=lambda _call: False,
    )

    system = (
        "你是一个调用工具帮用户解决问题的助手。只在需要时调用工具；"
        "能一次并行调用多个工具的场景就并行调用。最终用简洁的中文回答用户。"
    )
    user_input = "帮我查北京、上海、深圳今天的天气（用摄氏度），再顺便算一下 23 * 45。"

    print(f">>> 用户：{user_input}\n")
    answer = loop.run(user_input, system=system)
    print(f"\n>>> 最终答复：\n{answer}")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

def main() -> None:
    demo_schema()
    demo_parse_arguments()
    demo_execute()
    demo_real_llm()


if __name__ == "__main__":
    main()
