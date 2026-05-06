"""
LangChain Framework unified demo.

运行方式：

    uv run python -m learning_py.langchain_framework.demo check
    uv run python -m learning_py.langchain_framework.demo models
    uv run python -m learning_py.langchain_framework.demo agents
    uv run python -m learning_py.langchain_framework.demo memory
    uv run python -m learning_py.langchain_framework.demo streaming
    uv run python -m learning_py.langchain_framework.demo structured
    uv run python -m learning_py.langchain_framework.demo caching
    uv run python -m learning_py.langchain_framework.demo all

默认读取 python/.env 中的：

- LLM_MODEL
- LLM_API_KEY
- LLM_BASE_URL

这个入口的目标是把各个学习模块串起来，方便一次性看整体，也方便按需单独跑。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from learning_py.langchain_framework.config import load_chat_config
from learning_py.langchain_framework.models_and_messages import (
    demo_basic_chat_model,
    demo_batch_messages,
    demo_chat_with_history_loop,
    demo_conversation_history,
    demo_message_types,
    demo_model_parameters,
    demo_tool_message,
)
from learning_py.langchain_framework.short_term_memory import (
    demo_all_memory,
    demo_langgraph_checkpointer,
    demo_remove_messages,
    demo_summarization,
    demo_trim_messages,
    demo_window_memory,
)
from learning_py.langchain_framework.streaming_demo import demo_stream
from learning_py.langchain_framework.structured_output import demo_structured as run_structured_demo
from learning_py.langchain_framework import prompt_caching
from learning_py.langchain_framework.tools_and_agents import (
    demo_agent_loop,
    demo_tool_binding,
)


def _title(text: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n{text}\n{line}")


def demo_check() -> None:
    _title("环境检查")
    config = load_chat_config()
    print(f"model: {config.model}")
    print(f"base_url: {config.base_url}")
    print("env: OK")


def demo_models() -> None:
    _title("Models / Messages")
    demo_basic_chat_model()
    demo_message_types()
    demo_conversation_history()
    demo_tool_message()
    demo_model_parameters()
    demo_batch_messages()
    demo_chat_with_history_loop()


def demo_agents() -> None:
    _title("Tools / Agents")
    demo_tool_binding()
    demo_agent_loop()


def demo_memory() -> None:
    _title("Short-term Memory")
    demo_all_memory()


def demo_streaming() -> None:
    _title("Streaming")
    demo_stream()


def demo_structured() -> None:
    _title("Structured Output")
    run_structured_demo()


def demo_caching() -> None:
    _title("Prompt Caching")
    prompt_caching.demo_summary()
    print()
    prompt_caching.demo_check_cache_metadata()
    print()
    prompt_caching.demo_implicit_caching()


def demo_all() -> None:
    _title("LangChain Framework 全量演示")
    demo_check()
    demo_basic_chat_model()
    demo_agents()
    demo_memory()
    demo_streaming()
    demo_structured()


SECTION_RUNNERS: dict[str, Callable[[], None]] = {
    "check": demo_check,
    "models": demo_models,
    "agents": demo_agents,
    "memory": demo_memory,
    "memory-window": demo_window_memory,
    "memory-trim": demo_trim_messages,
    "memory-delete": demo_remove_messages,
    "memory-summary": demo_summarization,
    "memory-checkpointer": demo_langgraph_checkpointer,
    "streaming": demo_streaming,
    "structured": demo_structured,
    "caching": demo_caching,
    "all": demo_all,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the LangChain framework learning demos.",
    )
    parser.add_argument(
        "section",
        nargs="?",
        default="all",
        choices=tuple(SECTION_RUNNERS.keys()),
        help="Which section to run.",
    )
    args = parser.parse_args(argv)
    SECTION_RUNNERS[args.section]()


if __name__ == "__main__":
    main()