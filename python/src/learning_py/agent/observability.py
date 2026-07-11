"""Agent 可观测性 MVP：零外部依赖的全链路追踪与指标收集。

核心概念：
- Span：一次可观测的操作（LLM 调用、工具调用、Agent 整体执行）
- Tracer：管理 Span 的生命周期，自动计算耗时、嵌套关系
- Metrics：聚合统计（token 用量、延迟分布、工具调用频次、成本估算）

设计原则：
1. 零依赖——只用标准库，不引入 OpenTelemetry / LangSmith 等重型框架
2. 无侵入——通过装饰器 / 包装器接入，不修改现有 Agent 代码
3. 可落盘——支持导出 JSON 格式的 trace，方便后续接入任何可视化系统

运行：
    uv run python -m learning_py.agent.observability
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .tools import DEFAULT_TOOLBOX, Tool, TraceEntry, call_tool


# ────────────────────────────────────────────────────────────
# Span：一次可观测操作
# ────────────────────────────────────────────────────────────

@dataclass
class Span:
    """一个可观测的操作单元。"""

    span_id: str
    trace_id: str
    name: str
    kind: str  # "agent" | "llm" | "tool"
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list[Span] = field(default_factory=list)
    parent_id: str | None = None

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": self.attributes,
            "children": [c.to_dict() for c in self.children],
        }


# ────────────────────────────────────────────────────────────
# Tracer：管理 Span 的生命周期
# ────────────────────────────────────────────────────────────

class Tracer:
    """轻量级 Tracer，管理一次 Agent 执行的全部 Span。"""

    def __init__(self) -> None:
        self.trace_id = uuid.uuid4().hex[:12]
        self.root_span: Span | None = None
        self._span_stack: list[Span] = []
        self.all_spans: list[Span] = []

    @contextmanager
    def span(self, name: str, kind: str, **attrs: Any) -> Iterator[Span]:
        """上下文管理器：自动记录开始/结束时间，维护父子关系。"""
        s = Span(
            span_id=uuid.uuid4().hex[:8],
            trace_id=self.trace_id,
            name=name,
            kind=kind,
            attributes=attrs,
        )

        if self._span_stack:
            parent = self._span_stack[-1]
            s.parent_id = parent.span_id
            parent.children.append(s)
        else:
            self.root_span = s

        self._span_stack.append(s)
        self.all_spans.append(s)
        s.start_time = time.perf_counter()

        try:
            yield s
        finally:
            s.end_time = time.perf_counter()
            self._span_stack.pop()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "root": self.root_span.to_dict() if self.root_span else None,
        }

    def export_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))


# ────────────────────────────────────────────────────────────
# Metrics：聚合统计
# ────────────────────────────────────────────────────────────

# Claude / DeepSeek 等主流模型的大致定价 ($/1M tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "default": {"input": 1.00, "output": 3.00},
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Metrics:
    """从 Tracer 中提取聚合指标。"""

    total_duration_ms: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    llm_latencies_ms: list[float] = field(default_factory=list)
    tool_latencies_ms: list[float] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    errors: list[str] = field(default_factory=list)
    model: str = "default"

    @staticmethod
    def from_tracer(tracer: Tracer, model: str = "default") -> Metrics:
        m = Metrics(model=model)
        if tracer.root_span:
            m.total_duration_ms = tracer.root_span.duration_ms

        for span in tracer.all_spans:
            if span.kind == "llm":
                m.llm_calls += 1
                m.llm_latencies_ms.append(span.duration_ms)
                m.token_usage.input_tokens += span.attributes.get("input_tokens", 0)
                m.token_usage.output_tokens += span.attributes.get("output_tokens", 0)
            elif span.kind == "tool":
                m.tool_calls += 1
                m.tool_latencies_ms.append(span.duration_ms)
                tool_name = span.attributes.get("tool_name", "unknown")
                m.tool_call_counts[tool_name] = m.tool_call_counts.get(tool_name, 0) + 1
                if span.attributes.get("error"):
                    m.errors.append(f"{tool_name}: {span.attributes['error']}")
        return m

    @property
    def avg_llm_latency_ms(self) -> float:
        return sum(self.llm_latencies_ms) / len(self.llm_latencies_ms) if self.llm_latencies_ms else 0.0

    @property
    def estimated_cost_usd(self) -> float:
        pricing = MODEL_PRICING.get(self.model, MODEL_PRICING["default"])
        return (
            self.token_usage.input_tokens * pricing["input"]
            + self.token_usage.output_tokens * pricing["output"]
        ) / 1_000_000


# ────────────────────────────────────────────────────────────
# 可观测 Agent 包装器：无侵入接入
# ────────────────────────────────────────────────────────────

class ObservableReActAgent:
    """在 ReActAgent 外面包一层可观测性，不修改原始代码。"""

    def __init__(
        self,
        llm: Any,
        toolbox: dict[str, Tool] | None = None,
        max_steps: int = 6,
        model_name: str = "default",
    ) -> None:
        self.llm = llm
        self.toolbox = dict(toolbox or DEFAULT_TOOLBOX)
        self.max_steps = max_steps
        self.model_name = model_name
        self.tracer = Tracer()

    def run(self, task: str) -> tuple[str, list[TraceEntry], Metrics]:
        trace: list[TraceEntry] = []
        final = "（达到最大步数仍未完成）"

        with self.tracer.span("ReActAgent.run", "agent", task=task):
            scratchpad = ""

            for step in range(self.max_steps):
                prompt = self._build_prompt(task, scratchpad)
                input_tokens = len(prompt) // 4  # 粗估

                with self.tracer.span(
                    f"llm_call_step_{step}", "llm",
                    step=step, input_tokens=input_tokens,
                ) as llm_span:
                    output = self.llm.complete(prompt)
                    output_tokens = len(output) // 4
                    llm_span.attributes["output_tokens"] = output_tokens
                    llm_span.attributes["output_preview"] = output[:120]

                trace.append(TraceEntry("llm", output))

                if _has_final(output):
                    final = _extract_final(output)
                    trace.append(TraceEntry("final", final))
                    break

                action = _parse_action(output)
                if action is None:
                    final = "（无法解析模型输出）"
                    trace.append(TraceEntry("final", final))
                    break

                tool_name, arg = action

                with self.tracer.span(
                    f"tool_{tool_name}", "tool",
                    tool_name=tool_name, argument=arg, step=step,
                ) as tool_span:
                    obs = call_tool(self.toolbox, tool_name, arg)
                    tool_span.attributes["result"] = obs
                    if obs.startswith("（") and obs.endswith("）"):
                        tool_span.attributes["error"] = obs

                trace.append(TraceEntry("tool", f"{tool_name}({arg}) -> {obs}"))
                scratchpad += f"{output}\nOBSERVATION: {obs}\n"
            else:
                trace.append(TraceEntry("final", final))

        metrics = Metrics.from_tracer(self.tracer, self.model_name)
        return final, trace, metrics

    def _build_prompt(self, task: str, scratchpad: str) -> str:
        tools_desc = "\n".join(f"- {name}(arg): 工具" for name in self.toolbox)
        return (
            "[ReAct] 你是一个会使用工具的 Agent，每轮严格按以下两种格式之一回答，**不要输出额外文字**：\n"
            "格式 A（需要工具）：\n"
            "  THOUGHT: <你的想法>\n"
            "  ACTION: <tool_name>(<argument>)\n"
            "格式 B（已经能给出最终答案）：\n"
            "  THOUGHT: <你的想法>\n"
            "  FINAL: <最终答案>\n\n"
            f"可用工具：\n{tools_desc}\n\n"
            f"任务：{task}\n\n"
            f"历史（上一轮的 ACTION 与 OBSERVATION）：\n{scratchpad or '（空）'}\n"
            "现在请输出你的下一步："
        )


# ────────────────────────────────────────────────────────────
# 终端可视化报告
# ────────────────────────────────────────────────────────────

def print_trace_timeline(tracer: Tracer) -> None:
    """打印完整的 Trace 时间线，像一个迷你版的 Jaeger/Zipkin。"""
    print(f"\n{'─' * 70}")
    print(f"  TRACE TIMELINE  │  trace_id: {tracer.trace_id}")
    print(f"{'─' * 70}")

    if not tracer.root_span:
        print("  （空 trace）")
        return

    _print_span_tree(tracer.root_span, indent=0)
    print(f"{'─' * 70}")


def _print_span_tree(span: Span, indent: int) -> None:
    prefix = "  │ " * indent
    kind_icon = {"agent": "🤖", "llm": "🧠", "tool": "🔧"}.get(span.kind, "  ")
    duration = f"{span.duration_ms:.1f}ms"

    print(f"  {prefix}├─ {kind_icon} {span.name}  [{duration}]")

    for key in ["task", "output_preview", "tool_name", "argument", "result", "error"]:
        if key in span.attributes:
            val = str(span.attributes[key])
            if len(val) > 80:
                val = val[:77] + "..."
            label = key
            print(f"  {prefix}│    {label}: {val}")

    for child in span.children:
        _print_span_tree(child, indent + 1)


def print_metrics_report(metrics: Metrics) -> None:
    """打印聚合指标报告。"""
    print(f"\n{'═' * 70}")
    print(f"  OBSERVABILITY REPORT")
    print(f"{'═' * 70}")

    print(f"\n  ⏱  总耗时：{metrics.total_duration_ms:.1f}ms")
    print(f"  📊 模型：{metrics.model}")

    print(f"\n  ── LLM 调用 {'─' * 45}")
    print(f"     调用次数：{metrics.llm_calls}")
    print(f"     平均延迟：{metrics.avg_llm_latency_ms:.1f}ms")
    if metrics.llm_latencies_ms:
        print(f"     最快/最慢：{min(metrics.llm_latencies_ms):.1f}ms / {max(metrics.llm_latencies_ms):.1f}ms")

    print(f"\n  ── Token 用量 {'─' * 43}")
    print(f"     输入：{metrics.token_usage.input_tokens:,} tokens")
    print(f"     输出：{metrics.token_usage.output_tokens:,} tokens")
    print(f"     合计：{metrics.token_usage.total:,} tokens")
    print(f"     预估成本：${metrics.estimated_cost_usd:.6f}")

    print(f"\n  ── 工具调用 {'─' * 45}")
    print(f"     调用次数：{metrics.tool_calls}")
    if metrics.tool_call_counts:
        for name, count in sorted(metrics.tool_call_counts.items(), key=lambda x: -x[1]):
            bar = "█" * count
            print(f"     {name:>12s} │ {bar} ({count})")

    if metrics.errors:
        print(f"\n  ── 错误 {'─' * 48}")
        for err in metrics.errors:
            print(f"     ⚠ {err}")

    print(f"\n{'═' * 70}")


def print_latency_histogram(metrics: Metrics) -> None:
    """打印 LLM 调用延迟的 ASCII 直方图。"""
    latencies = metrics.llm_latencies_ms
    if not latencies:
        return

    print(f"\n  LLM Latency Distribution (n={len(latencies)})")
    print(f"  {'─' * 50}")

    buckets = [50, 100, 200, 500, 1000, 2000, 5000, float("inf")]
    labels = ["<50ms", "<100ms", "<200ms", "<500ms", "<1s", "<2s", "<5s", ">=5s"]
    counts = [0] * len(buckets)

    for lat in latencies:
        for i, threshold in enumerate(buckets):
            if lat < threshold:
                counts[i] += 1
                break

    max_count = max(counts) if counts else 1
    for label, count in zip(labels, counts):
        bar_len = int(count / max_count * 30) if max_count > 0 else 0
        bar = "▓" * bar_len
        print(f"  {label:>8s} │ {bar} ({count})")


# ────────────────────────────────────────────────────────────
# 复用 react_agent.py 里的解析函数（避免循环导入直接内联）
# ────────────────────────────────────────────────────────────

import re

_ACTION_HEAD_RE = re.compile(
    r"\**\s*action\s*\**\s*[:：]\s*([a-zA-Z_]+)\s*\(",
    re.IGNORECASE,
)
_FINAL_RE = re.compile(r"\**\s*final\s*\**\s*[:：]\s*(.+)", re.IGNORECASE | re.DOTALL)


def _has_final(text: str) -> bool:
    return _FINAL_RE.search(text) is not None


def _extract_final(text: str) -> str:
    m = _FINAL_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _parse_action(text: str) -> tuple[str, str] | None:
    m = _ACTION_HEAD_RE.search(text)
    if not m:
        return None
    tool_name = m.group(1)
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return None
    arg = text[start:i].strip().strip("\"'")
    return tool_name, arg


# ────────────────────────────────────────────────────────────
# FakeLLM：用于 demo 的确定性 LLM 模拟
# ────────────────────────────────────────────────────────────

class FakeLLM:
    """按脚本逐步返回预设回答，用于 demo 演示，不需要真实 API。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0
        self.call_count = 0

    def complete(self, prompt: str) -> str:
        self.call_count += 1
        if self._index >= len(self._responses):
            return "THOUGHT: 我已经收集了足够信息。\nFINAL: 任务完成。"
        resp = self._responses[self._index]
        self._index += 1
        time.sleep(0.05 + self._index * 0.03)  # 模拟不同延迟
        return resp


# ────────────────────────────────────────────────────────────
# Demo：直接运行体验
# ────────────────────────────────────────────────────────────

def demo() -> None:
    """用 FakeLLM 跑一个完整的可观测性 demo，零配置、零网络调用。"""

    print("\n" + "🔭" * 3 + " Agent 可观测性 MVP Demo " + "🔭" * 3)
    print("演示：全链路追踪 + 指标收集 + 终端可视化\n")

    fake_llm = FakeLLM([
        "THOUGHT: 用户问了两件事，先搜索 Python 是什么。\nACTION: search(python)",
        "THOUGHT: 好的，已经知道 Python 的定义。现在计算数学表达式。\nACTION: calc((1+2+3)*4)",
        "THOUGHT: 两个信息都拿到了，可以回答了。\nFINAL: Python 是一种解释型、动态类型、强类型的高级编程语言。(1+2+3)*4 = 24。",
    ])

    agent = ObservableReActAgent(
        llm=fake_llm,
        model_name="deepseek-chat",
        max_steps=6,
    )

    final, trace, metrics = agent.run(
        "请告诉我 Python 是什么语言，并计算 (1+2+3)*4。"
    )

    # 1. 打印 Trace 时间线
    print_trace_timeline(agent.tracer)

    # 2. 打印指标报告
    print_metrics_report(metrics)

    # 3. 打印延迟直方图
    print_latency_histogram(metrics)

    # 4. 导出 JSON（可选）
    export_path = Path(__file__).parent / "trace_output.json"
    agent.tracer.export_json(export_path)
    print(f"\n  📁 Trace 已导出到：{export_path}")
    print(f"     可用 jq 查看：cat {export_path.name} | python -m json.tool")


def demo_with_real_llm() -> None:
    """用真实 LLM 跑可观测性 demo（需要配置 .env）。"""
    from .llm_client import OpenAICompatLLM

    print("\n" + "🔭" * 3 + " Agent 可观测性 MVP Demo（真实 LLM）" + "🔭" * 3)

    llm = OpenAICompatLLM(name="observable-react", temperature=0.0)
    model_name = llm.model or "default"

    agent = ObservableReActAgent(
        llm=llm,
        model_name=model_name,
        max_steps=6,
    )

    final, trace, metrics = agent.run(
        "请告诉我 Python 是什么语言，并计算 (1+2+3)*4。"
    )

    print_trace_timeline(agent.tracer)
    print_metrics_report(metrics)
    print_latency_histogram(metrics)

    export_path = Path(__file__).parent / "trace_output.json"
    agent.tracer.export_json(export_path)
    print(f"\n  📁 Trace 已导出到：{export_path}")


if __name__ == "__main__":
    import sys
    if "--real" in sys.argv:
        demo_with_real_llm()
    else:
        demo()
