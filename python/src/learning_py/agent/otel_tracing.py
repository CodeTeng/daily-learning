"""OpenTelemetry 集成：将 Agent 执行轨迹桥接到 OTel 标准格式。

功能：
- 将现有 Tracer/Span 导出为 OTel Span（保留父子层级）
- 遵循 GenAI 语义约定（gen_ai.usage.input_tokens 等）
- 支持 Console / OTLP 两种导出器
- 环境变量驱动开关，未启用时零开销

运行：
    uv run python -m learning_py.agent.otel_tracing                # Console 输出 demo
    uv run python -m learning_py.agent.otel_tracing --real          # 真实 LLM
"""

from __future__ import annotations

import os
import time
from typing import Any

from .llm_client import _load_dotenv_once

_load_dotenv_once()

from .observability import (
    FakeLLM,
    Metrics,
    ObservableReActAgent,
    Span,
    Tracer,
    print_metrics_report,
    print_trace_timeline,
)
from .tools import TraceEntry

# ────────────────────────────────────────────────────────────
# GenAI 语义约定常量（避免对 semconv 包的硬依赖）
# 参考：https://opentelemetry.io/docs/specs/semconv/gen-ai/
# ────────────────────────────────────────────────────────────

_GENAI_SYSTEM = "gen_ai.system"
_GENAI_REQUEST_MODEL = "gen_ai.request.model"
_GENAI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GENAI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_GENAI_RESPONSE_FINISH_REASON = "gen_ai.response.finish_reason"


# ────────────────────────────────────────────────────────────
# 环境配置
# ────────────────────────────────────────────────────────────

def otel_is_enabled() -> bool:
    """OTel 追踪是否启用（读 OTEL_TRACING_ENABLED 环境变量）。"""
    return os.environ.get("OTEL_TRACING_ENABLED", "").lower() in ("true", "1", "yes")


def setup_otel_tracer_provider(
    service_name: str = "agent-observability",
    *,
    use_console: bool = False,
    otlp_endpoint: str | None = None,
) -> Any:
    """创建并注册 OTel TracerProvider。

    Args:
        service_name: 服务名称，写入 Resource
        use_console: 是否添加 ConsoleSpanExporter（终端输出）
        otlp_endpoint: OTLP Collector 地址（如 http://localhost:4317）

    Returns:
        TracerProvider 实例，用于后续 force_flush / shutdown。
        如果 OTel 包未安装则返回 None。
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    except ImportError:
        print("  ⚠ opentelemetry-sdk 未安装，跳过 OTel 初始化")
        print("    安装：uv sync --extra otel")
        return None

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter_type = os.environ.get("OTEL_EXPORTER_TYPE", "")
    if use_console or exporter_type == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
        except ImportError:
            print(f"  ⚠ opentelemetry-exporter-otlp 未安装，跳过 OTLP 导出到 {endpoint}")

    trace.set_tracer_provider(provider)
    return provider


# ────────────────────────────────────────────────────────────
# Span 桥接：现有 Tracer → OTel Spans
# ────────────────────────────────────────────────────────────

def _detect_genai_system(model_name: str) -> str:
    """从模型名推断 gen_ai.system。"""
    model_lower = model_name.lower()
    if "deepseek" in model_lower:
        return "deepseek"
    if "claude" in model_lower:
        return "anthropic"
    if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
        return "openai"
    return "unknown"


def _build_otel_attributes(span: Span, model_name: str) -> dict[str, Any]:
    """根据 Span 类型构建 OTel 属性字典。"""
    attrs: dict[str, Any] = {}

    if span.kind == "llm":
        attrs[_GENAI_SYSTEM] = _detect_genai_system(model_name)
        attrs[_GENAI_REQUEST_MODEL] = model_name
        if "input_tokens" in span.attributes:
            attrs[_GENAI_USAGE_INPUT_TOKENS] = span.attributes["input_tokens"]
        if "output_tokens" in span.attributes:
            attrs[_GENAI_USAGE_OUTPUT_TOKENS] = span.attributes["output_tokens"]
        attrs[_GENAI_RESPONSE_FINISH_REASON] = "stop"
    elif span.kind == "tool":
        if "tool_name" in span.attributes:
            attrs["tool.name"] = span.attributes["tool_name"]
        if "argument" in span.attributes:
            attrs["tool.input"] = span.attributes["argument"]
        if "result" in span.attributes:
            attrs["tool.output"] = str(span.attributes["result"])[:200]
        if "error" in span.attributes:
            attrs["error.message"] = span.attributes["error"]
    elif span.kind == "agent":
        if "task" in span.attributes:
            attrs["agent.task"] = span.attributes["task"]

    return attrs


def export_to_otel(
    tracer: Tracer,
    *,
    otel_tracer: Any | None = None,
    model_name: str = "default",
) -> None:
    """将现有 Tracer 的 Span 树导出为 OTel Span（后置桥接）。

    在 Agent 运行完毕后调用，将已记录的 Span 树一次性导出到 OTel。
    保留完整的父子层级和时间戳。
    """
    try:
        from opentelemetry import trace
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
    except ImportError:
        print("  ⚠ opentelemetry-api 未安装，无法导出")
        return

    if otel_tracer is None:
        otel_tracer = trace.get_tracer("agent.observability")

    if tracer.root_span is None:
        return

    # 用 trace 开始时的 wall-clock 作为锚点，把 perf_counter 转成绝对纳秒时间戳
    anchor_perf = tracer.root_span.start_time
    anchor_wall_ns = time.time_ns() - int(
        (time.perf_counter() - anchor_perf) * 1_000_000_000
    )

    def _perf_to_ns(t: float) -> int:
        return anchor_wall_ns + int((t - anchor_perf) * 1_000_000_000)

    def _export_span(span: Span, parent_context: Any = None) -> None:
        attrs = _build_otel_attributes(span, model_name)

        # 用 start_as_current_span 创建 OTel span，手动设置时间
        ctx = parent_context or trace.context_api.get_current()
        otel_span = otel_tracer.start_span(
            name=span.name,
            context=ctx,
            start_time=_perf_to_ns(span.start_time),
            attributes=attrs,
        )

        child_context = trace.set_span_in_context(otel_span, ctx)

        for child in span.children:
            _export_span(child, child_context)

        otel_span.end(end_time=_perf_to_ns(span.end_time))

    _export_span(tracer.root_span)


# ────────────────────────────────────────────────────────────
# 实时 OTel Agent 包装器
# ────────────────────────────────────────────────────────────

class OTelReActAgent:
    """ReAct Agent + 实时 OTel Span 发射。

    同时保留轻量级 Tracer（用于终端可视化）和 OTel Span（用于导出到后端）。
    """

    def __init__(
        self,
        llm: Any,
        toolbox: dict[str, Any] | None = None,
        max_steps: int = 6,
        model_name: str = "default",
    ) -> None:
        self.inner = ObservableReActAgent(
            llm=llm, toolbox=toolbox, max_steps=max_steps, model_name=model_name
        )
        self.model_name = model_name
        self._otel_tracer: Any = None

        try:
            from opentelemetry import trace

            self._otel_tracer = trace.get_tracer("agent.observability")
        except ImportError:
            pass

    def run(self, task: str) -> tuple[str, list[TraceEntry], Metrics]:
        """执行 Agent 并同时发射 OTel Span。"""
        final, trace_entries, metrics = self.inner.run(task)

        if self._otel_tracer and self.inner.tracer.root_span:
            export_to_otel(
                self.inner.tracer,
                otel_tracer=self._otel_tracer,
                model_name=self.model_name,
            )

        return final, trace_entries, metrics

    @property
    def tracer(self) -> Tracer:
        return self.inner.tracer


# ────────────────────────────────────────────────────────────
# Demo
# ────────────────────────────────────────────────────────────

def demo() -> None:
    """OTel demo：FakeLLM + Console 导出，零配置。"""
    print("\n" + "📡" * 3 + " OpenTelemetry 可观测性 Demo " + "📡" * 3)
    print("演示：Agent Span → OTel Span → Console 导出\n")

    provider = setup_otel_tracer_provider("agent-otel-demo", use_console=True)
    if provider is None:
        print("  请先安装 OTel 依赖：uv sync --extra otel")
        return

    fake_llm = FakeLLM([
        "THOUGHT: 先搜索 Python 是什么。\nACTION: search(python)",
        "THOUGHT: 再算一下数学。\nACTION: calc((1+2+3)*4)",
        "THOUGHT: 信息齐全了。\nFINAL: Python 是解释型高级语言，(1+2+3)*4 = 24。",
    ])

    agent = OTelReActAgent(
        llm=fake_llm,
        model_name="deepseek-chat",
        max_steps=6,
    )

    final, trace_entries, metrics = agent.run(
        "请告诉我 Python 是什么语言，并计算 (1+2+3)*4。"
    )

    # 先打印轻量级可视化
    print_trace_timeline(agent.tracer)
    print_metrics_report(metrics)

    # OTel span 已通过 ConsoleSpanExporter 自动输出到终端
    provider.force_flush()

    print("\n  ✅ 以上 OTel span 输出来自 ConsoleSpanExporter")
    print("  💡 如需发送到 Jaeger/Tempo，设置 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317")


def demo_with_real_llm() -> None:
    """OTel demo：真实 LLM（需要 .env 配置）。"""
    from .llm_client import OpenAICompatLLM

    print("\n" + "📡" * 3 + " OpenTelemetry Demo（真实 LLM）" + "📡" * 3)

    provider = setup_otel_tracer_provider("agent-otel-demo", use_console=True)
    if provider is None:
        return

    llm = OpenAICompatLLM(name="otel-react", temperature=0.0)

    agent = OTelReActAgent(
        llm=llm,
        model_name=llm.model or "default",
        max_steps=6,
    )

    final, _, metrics = agent.run(
        "请告诉我 Python 是什么语言，并计算 (1+2+3)*4。"
    )

    print_trace_timeline(agent.tracer)
    print_metrics_report(metrics)
    provider.force_flush()


if __name__ == "__main__":
    import sys

    if "--real" in sys.argv:
        demo_with_real_llm()
    else:
        demo()
