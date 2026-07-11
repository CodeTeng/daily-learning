"""LangSmith 集成的单元测试。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from learning_py.agent.observability import FakeLLM
from learning_py.agent.langsmith_tracing import (
    LangSmithReActAgent,
    TracedFakeLLM,
    langsmith_is_enabled,
)


class TestLangSmithConfig:
    def test_enabled_when_both_set(self) -> None:
        with patch.dict(os.environ, {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "lsv2_pt_test",
        }):
            assert langsmith_is_enabled() is True

    def test_disabled_without_api_key(self) -> None:
        env = os.environ.copy()
        env["LANGSMITH_TRACING"] = "true"
        env.pop("LANGSMITH_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            assert langsmith_is_enabled() is False

    def test_disabled_without_tracing_flag(self) -> None:
        env = os.environ.copy()
        env.pop("LANGSMITH_TRACING", None)
        env["LANGSMITH_API_KEY"] = "lsv2_pt_test"
        with patch.dict(os.environ, env, clear=True):
            assert langsmith_is_enabled() is False

    def test_disabled_by_default(self) -> None:
        env = os.environ.copy()
        env.pop("LANGSMITH_TRACING", None)
        env.pop("LANGSMITH_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            assert langsmith_is_enabled() is False


class TestTracedFakeLLM:
    def test_satisfies_protocol(self) -> None:
        llm = TracedFakeLLM(["FINAL: test"])
        assert hasattr(llm, "complete")
        assert hasattr(llm, "call_count")

    def test_returns_responses_sequentially(self) -> None:
        llm = TracedFakeLLM(["resp1", "resp2", "resp3"])
        assert llm.complete("a") == "resp1"
        assert llm.complete("b") == "resp2"
        assert llm.complete("c") == "resp3"
        assert llm.call_count == 3

    def test_fallback_on_exhaustion(self) -> None:
        llm = TracedFakeLLM(["resp1"])
        _ = llm.complete("a")
        result = llm.complete("b")
        assert "FINAL" in result


class TestLangSmithReActAgent:
    def test_full_run(self) -> None:
        fake_llm = TracedFakeLLM([
            "THOUGHT: 搜索一下\nACTION: search(python)",
            "THOUGHT: 知道了\nFINAL: Python 是高级语言",
        ])
        agent = LangSmithReActAgent(llm=fake_llm, model_name="deepseek-chat")
        final, trace, metrics = agent.run("Python 是什么")

        assert "Python" in final
        assert metrics.llm_calls == 2
        assert metrics.tool_calls == 1
        assert metrics.total_duration_ms > 0

    def test_unparseable_output(self) -> None:
        fake_llm = TracedFakeLLM(["乱七八糟的输出"])
        agent = LangSmithReActAgent(llm=fake_llm)
        final, _, metrics = agent.run("test")
        assert "无法解析" in final
        assert metrics.llm_calls == 1

    def test_max_steps_reached(self) -> None:
        fake_llm = TracedFakeLLM([
            "THOUGHT: 搜\nACTION: search(a)",
            "THOUGHT: 搜\nACTION: search(b)",
            "THOUGHT: 搜\nACTION: search(c)",
        ])
        agent = LangSmithReActAgent(llm=fake_llm, max_steps=2)
        final, _, metrics = agent.run("test")
        assert "最大步数" in final
        assert metrics.llm_calls == 2

    def test_tracer_has_correct_hierarchy(self) -> None:
        fake_llm = TracedFakeLLM([
            "THOUGHT: 搜\nACTION: search(python)",
            "THOUGHT: 好\nFINAL: done",
        ])
        agent = LangSmithReActAgent(llm=fake_llm)
        agent.run("test")

        root = agent.tracer.root_span
        assert root is not None
        assert root.kind == "agent"
        assert len(root.children) == 3  # llm + tool + llm

    def test_demo_runs_without_error(self) -> None:
        from learning_py.agent.langsmith_tracing import demo

        demo()
