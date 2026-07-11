"""OpenTelemetry 集成的单元测试。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

try:
    import opentelemetry  # noqa: F401

    otel_installed = True
except ImportError:
    otel_installed = False

pytestmark = pytest.mark.skipif(not otel_installed, reason="opentelemetry not installed")

from learning_py.agent.observability import FakeLLM, Tracer
from learning_py.agent.otel_tracing import (
    OTelReActAgent,
    _build_otel_attributes,
    _detect_genai_system,
    export_to_otel,
    otel_is_enabled,
    setup_otel_tracer_provider,
)


class TestOTelConfig:
    def test_otel_is_enabled_true(self) -> None:
        with patch.dict(os.environ, {"OTEL_TRACING_ENABLED": "true"}):
            assert otel_is_enabled() is True

    def test_otel_is_enabled_false(self) -> None:
        with patch.dict(os.environ, {"OTEL_TRACING_ENABLED": ""}, clear=False):
            env = os.environ.copy()
            env.pop("OTEL_TRACING_ENABLED", None)
            with patch.dict(os.environ, env, clear=True):
                assert otel_is_enabled() is False

    def test_otel_is_enabled_case_insensitive(self) -> None:
        for val in ("TRUE", "True", "1", "yes", "YES"):
            with patch.dict(os.environ, {"OTEL_TRACING_ENABLED": val}):
                assert otel_is_enabled() is True


class TestGenAIConventions:
    def test_detect_deepseek(self) -> None:
        assert _detect_genai_system("deepseek-chat") == "deepseek"

    def test_detect_anthropic(self) -> None:
        assert _detect_genai_system("claude-sonnet-4-6") == "anthropic"

    def test_detect_openai(self) -> None:
        assert _detect_genai_system("gpt-4o") == "openai"

    def test_detect_unknown(self) -> None:
        assert _detect_genai_system("my-custom-model") == "unknown"

    def test_build_llm_attributes(self) -> None:
        from learning_py.agent.observability import Span

        span = Span(
            span_id="abc",
            trace_id="xyz",
            name="llm_call",
            kind="llm",
            attributes={"input_tokens": 100, "output_tokens": 50},
        )
        attrs = _build_otel_attributes(span, "deepseek-chat")
        assert attrs["gen_ai.system"] == "deepseek"
        assert attrs["gen_ai.request.model"] == "deepseek-chat"
        assert attrs["gen_ai.usage.input_tokens"] == 100
        assert attrs["gen_ai.usage.output_tokens"] == 50

    def test_build_tool_attributes(self) -> None:
        from learning_py.agent.observability import Span

        span = Span(
            span_id="abc",
            trace_id="xyz",
            name="tool_search",
            kind="tool",
            attributes={"tool_name": "search", "argument": "python", "result": "ok"},
        )
        attrs = _build_otel_attributes(span, "default")
        assert attrs["tool.name"] == "search"
        assert attrs["tool.input"] == "python"
        assert attrs["tool.output"] == "ok"

    def test_build_agent_attributes(self) -> None:
        from learning_py.agent.observability import Span

        span = Span(
            span_id="abc",
            trace_id="xyz",
            name="agent",
            kind="agent",
            attributes={"task": "test task"},
        )
        attrs = _build_otel_attributes(span, "default")
        assert attrs["agent.task"] == "test task"


class TestSetupProvider:
    def test_console_exporter(self) -> None:
        provider = setup_otel_tracer_provider("test-service", use_console=True)
        assert provider is not None
        provider.shutdown()

    def test_returns_provider(self) -> None:
        provider = setup_otel_tracer_provider("test-service")
        assert provider is not None
        provider.shutdown()


class TestExportToOTel:
    def test_export_preserves_hierarchy(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor,
        )
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_tracer = provider.get_tracer("test")

        tracer = Tracer()
        with tracer.span("root", "agent", task="test"):
            with tracer.span("llm_0", "llm", input_tokens=50, output_tokens=20):
                pass
            with tracer.span("tool_search", "tool", tool_name="search"):
                pass

        export_to_otel(tracer, otel_tracer=otel_tracer, model_name="deepseek-chat")
        provider.force_flush()

        spans = exporter.get_finished_spans()
        assert len(spans) == 3

        span_names = {s.name for s in spans}
        assert "root" in span_names
        assert "llm_0" in span_names
        assert "tool_search" in span_names

        llm_span = next(s for s in spans if s.name == "llm_0")
        assert llm_span.attributes is not None
        assert llm_span.attributes.get("gen_ai.system") == "deepseek"
        assert llm_span.attributes.get("gen_ai.usage.input_tokens") == 50

        provider.shutdown()

    def test_export_empty_tracer(self) -> None:
        tracer = Tracer()
        export_to_otel(tracer, model_name="default")  # should not raise


class TestOTelReActAgent:
    def test_full_run_with_export(self) -> None:
        """端到端测试：运行 Agent → 导出到 OTel → 验证 span。"""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from learning_py.agent.observability import ObservableReActAgent

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_tracer = provider.get_tracer("test")

        fake_llm = FakeLLM([
            "THOUGHT: 搜索\nACTION: search(python)",
            "THOUGHT: 知道了\nFINAL: Python 是高级语言",
        ])

        agent = ObservableReActAgent(llm=fake_llm, model_name="deepseek-chat")
        final, trace_entries, metrics = agent.run("Python 是什么")

        assert "Python" in final
        assert metrics.llm_calls == 2
        assert metrics.tool_calls == 1

        export_to_otel(agent.tracer, otel_tracer=otel_tracer, model_name="deepseek-chat")
        provider.force_flush()

        spans = exporter.get_finished_spans()
        assert len(spans) >= 3  # root + 2 llm + 1 tool

        provider.shutdown()

    def test_demo_runs_without_error(self) -> None:
        from learning_py.agent.otel_tracing import demo

        demo()
