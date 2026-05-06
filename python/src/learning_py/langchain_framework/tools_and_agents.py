"""
LangChain Tools and Agents demos.
"""

import json
from datetime import datetime

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from learning_py.langchain_framework.config import create_chat_model


def _model(temp: float = 0) -> ChatOpenAI:
    return create_chat_model(temperature=temp)


@tool
def get_current_time() -> str:
    """Get current local time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def demo_tool_binding() -> None:
    print("=" * 60)
    print("Demo: Tool Binding")
    print("=" * 60)
    model = _model()
    model_with_tools = model.bind_tools([get_current_time, add])
    resp = model_with_tools.invoke([HumanMessage(content="What time is it now?")])
    print("AI:", resp.content)
    print("tool_calls:", getattr(resp, "tool_calls", []))


def demo_agent_loop() -> None:
    print("=" * 60)
    print("Demo: Agent Loop")
    print("=" * 60)
    model = _model()
    model_with_tools = model.bind_tools([get_current_time, add])
    tools = {"get_current_time": get_current_time, "add": add}

    messages = [HumanMessage(content="Please calculate 7.5 + 2.5 and also tell me current time.")]

    for _ in range(6):
        ai = model_with_tools.invoke(messages)
        messages.append(ai)
        calls = getattr(ai, "tool_calls", [])
        if not calls:
            print("Final:", ai.content)
            return

        for call in calls:
            name = call.get("name")
            if not name:
                function = call.get("function") or {}
                name = function["name"]

            if "args" in call and call["args"] is not None:
                args = call["args"]
            else:
                function = call.get("function") or {}
                args = json.loads(function["arguments"])
            result = tools[name].invoke(args)
            messages.append(
                ToolMessage(content=str(result), tool_call_id=call["id"], name=name)
            )

    print("Stopped due to max iterations")


if __name__ == "__main__":
    demo_tool_binding()
    demo_agent_loop()
