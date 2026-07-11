"""可观测性模块的单元测试。"""

from __future__ import annotations

from learning_py.agent.observability import (
    FakeLLM,
    Metrics,
    ObservableReActAgent,
    Span,
    Tracer,
)


class TestTracer:
    def test_span_nesting(self) -> None:
        tracer = Tracer()
        with tracer.span("root", "agent") as root:
            with tracer.span("child1", "llm"):
                pass
            with tracer.span("child2", "tool"):
                pass

        assert root.span_id == tracer.root_span.span_id  # type: ignore[union-attr]
        assert len(root.children) == 2
        assert root.children[0].name == "child1"
        assert root.children[1].name == "child2"
        assert root.children[0].parent_id == root.span_id

    def test_span_duration_positive(self) -> None:
        tracer = Tracer()
        with tracer.span("op", "llm") as s:
            _ = sum(range(10000))
        assert s.duration_ms > 0

    def test_all_spans_collected(self) -> None:
        tracer = Tracer()
        with tracer.span("root", "agent"):
            with tracer.span("a", "llm"):
                with tracer.span("a1", "tool"):
                    pass
            with tracer.span("b", "llm"):
                pass
        assert len(tracer.all_spans) == 4

    def test_export_json(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tracer = Tracer()
        with tracer.span("root", "agent"):
            pass
        out = tmp_path / "trace.json"
        tracer.export_json(out)
        import json
        data = json.loads(out.read_text())
        assert data["trace_id"] == tracer.trace_id
        assert data["root"]["name"] == "root"


class TestMetrics:
    def test_from_tracer(self) -> None:
        tracer = Tracer()
        with tracer.span("root", "agent"):
            with tracer.span("llm1", "llm", input_tokens=100, output_tokens=50):
                pass
            with tracer.span("tool1", "tool", tool_name="search"):
                pass
            with tracer.span("llm2", "llm", input_tokens=200, output_tokens=80):
                pass

        m = Metrics.from_tracer(tracer)
        assert m.llm_calls == 2
        assert m.tool_calls == 1
        assert m.token_usage.input_tokens == 300
        assert m.token_usage.output_tokens == 130
        assert m.token_usage.total == 430
        assert m.tool_call_counts == {"search": 1}

    def test_cost_estimation(self) -> None:
        tracer = Tracer()
        with tracer.span("root", "agent"):
            with tracer.span("llm", "llm", input_tokens=1_000_000, output_tokens=100_000):
                pass
        m = Metrics.from_tracer(tracer, model="deepseek-chat")
        assert m.estimated_cost_usd > 0
        assert m.estimated_cost_usd < 1.0  # deepseek 很便宜

    def test_error_collection(self) -> None:
        tracer = Tracer()
        with tracer.span("root", "agent"):
            with tracer.span("t", "tool", tool_name="bad_tool", error="timeout"):
                pass
        m = Metrics.from_tracer(tracer)
        assert len(m.errors) == 1
        assert "bad_tool" in m.errors[0]


class TestObservableReActAgent:
    def test_full_run(self) -> None:
        llm = FakeLLM([
            "THOUGHT: 搜索一下\nACTION: search(python)",
            "THOUGHT: 知道了\nFINAL: Python 是高级语言",
        ])
        agent = ObservableReActAgent(llm=llm, model_name="deepseek-chat")
        final, trace, metrics = agent.run("Python 是什么")

        assert "Python" in final
        assert metrics.llm_calls == 2
        assert metrics.tool_calls == 1
        assert metrics.total_duration_ms > 0
        assert metrics.estimated_cost_usd >= 0

    def test_unparseable_output(self) -> None:
        llm = FakeLLM(["这是一段无法解析的输出"])
        agent = ObservableReActAgent(llm=llm)
        final, trace, metrics = agent.run("test")
        assert "无法解析" in final
        assert metrics.llm_calls == 1

    def test_max_steps_reached(self) -> None:
        llm = FakeLLM([
            "THOUGHT: 搜\nACTION: search(a)",
            "THOUGHT: 再搜\nACTION: search(b)",
            "THOUGHT: 继续\nACTION: search(c)",
        ])
        agent = ObservableReActAgent(llm=llm, max_steps=2)
        final, _, metrics = agent.run("test")
        assert "最大步数" in final
        assert metrics.llm_calls == 2

    def test_trace_json_export(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        llm = FakeLLM(["THOUGHT: ok\nFINAL: done"])
        agent = ObservableReActAgent(llm=llm)
        agent.run("test")

        out = tmp_path / "t.json"
        agent.tracer.export_json(out)
        import json
        data = json.loads(out.read_text())
        assert data["root"]["kind"] == "agent"
        assert len(data["root"]["children"]) >= 1
