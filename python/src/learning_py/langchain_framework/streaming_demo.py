"""
LangChain streaming demos.
"""

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from learning_py.langchain_framework.config import create_chat_model


def _model(temp: float = 0.7) -> ChatOpenAI:
    return create_chat_model(temperature=temp)


def demo_stream() -> None:
    print("=" * 60)
    print("Demo: Streaming")
    print("=" * 60)
    m = _model()
    msg = [HumanMessage(content="Explain Python decorators in 5 short lines.")]
    full = ""
    for chunk in m.stream(msg):
        print(chunk.content, end="", flush=True)
        full += chunk.content
    print("\n---\nlen:", len(full))


if __name__ == "__main__":
    demo_stream()
