"""LangSmith 集成：用 @traceable 和 wrap_openai 追踪 Agent 执行。

功能：
- @traceable 装饰器自动记录函数调用链（Agent → LLM → Tool）
- wrap_openai 无侵入包装 OpenAI 客户端，自动捕获 token 用量
- 环境变量驱动开关，未配置时零开销、优雅降级

运行：
    uv run python -m learning_py.agent.langsmith_tracing              # FakeLLM demo
    uv run python -m learning_py.agent.langsmith_tracing --real        # 真实 LLM

环境变量：
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=lsv2_pt_xxxxx
    LANGSMITH_PROJECT=agent-observability-demo   # 可选
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
    Tracer,
    print_metrics_report,
    print_trace_timeline,
    _has_final,
    _extract_final,
    _parse_action,
)
from .tools import DEFAULT_TOOLBOX, Tool, TraceEntry, call_tool

# ────────────────────────────────────────────────────────────
# 条件导入 @traceable：未安装 langsmith 时使用 no-op
# ────────────────────────────────────────────────────────────

try:
    from langsmith import traceable
except ImportError:

    def traceable(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        """langsmith 未安装时的 no-op 替代。"""
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn


# ────────────────────────────────────────────────────────────
# 环境配置
# ────────────────────────────────────────────────────────────

def langsmith_is_enabled() -> bool:
    """LangSmith 追踪是否启用（需要同时设置 LANGSMITH_TRACING 和 LANGSMITH_API_KEY）。"""
    return (
        os.environ.get("LANGSMITH_TRACING", "").lower() in ("true", "1")
        and bool(os.environ.get("LANGSMITH_API_KEY"))
    )


# ────────────────────────────────────────────────────────────
# LLM 工厂：wrap_openai 无侵入包装
# ────────────────────────────────────────────────────────────

def create_traced_llm(name: str = "langsmith-traced", **kwargs: Any) -> Any:
    """创建带 LangSmith 追踪的 LLM 客户端。

    内部构造 OpenAICompatLLM，然后用 wrap_openai 包装其 _client。
    如果 LangSmith 未启用，返回原始的 OpenAICompatLLM。
    """
    from .llm_client import OpenAICompatLLM

    llm = OpenAICompatLLM(name=name, **kwargs)

    if langsmith_is_enabled():
        try:
            from langsmith.wrappers import wrap_openai

            llm._client = wrap_openai(llm._client)  # type: ignore[attr-defined]
        except ImportError:
            pass

    return llm


# ────────────────────────────────────────────────────────────
# Traced FakeLLM：用于 demo
# ────────────────────────────────────────────────────────────

class TracedFakeLLM:
    """带 LangSmith 追踪的 FakeLLM，用于无 API Key 的 demo 演示。"""

    def __init__(self, responses: list[str]) -> None:
        self._inner = FakeLLM(responses)
        self.call_count = 0

    @traceable(run_type="llm", name="FakeLLM.complete")
    def complete(self, prompt: str) -> str:
        result = self._inner.complete(prompt)
        self.call_count = self._inner.call_count
        return result


# ────────────────────────────────────────────────────────────
# LangSmith Agent 包装器
# ────────────────────────────────────────────────────────────

class LangSmithReActAgent:
    """ReAct Agent + LangSmith 追踪。

    通过 @traceable 装饰器标记每个层级：
    - run() → run_type="chain"（整体执行链）
    - _llm_step() → run_type="llm"（单次 LLM 调用）
    - _tool_step() → run_type="tool"（单次工具调用）

    同时保留轻量级 Tracer 用于终端可视化。
    """

    def __init__(
        self,
        llm: Any,
        toolbox: dict[str, Tool] | None = None,
        max_steps: int = 6,
        model_name: str = "default",
        project_name: str | None = None,
    ) -> None:
        self.llm = llm
        self.toolbox = dict(toolbox or DEFAULT_TOOLBOX)
        self.max_steps = max_steps
        self.model_name = model_name
        self.project_name = project_name or os.environ.get(
            "LANGSMITH_PROJECT", "agent-observability"
        )
        self.tracer = Tracer()

    @traceable(run_type="chain", name="ReActAgent.run")
    def run(self, task: str) -> tuple[str, list[TraceEntry], Metrics]:
        trace: list[TraceEntry] = []
        final = "（达到最大步数仍未完成）"

        with self.tracer.span("ReActAgent.run", "agent", task=task):
            scratchpad = ""

            for step in range(self.max_steps):
                prompt = self._build_prompt(task, scratchpad)
                output = self._llm_step(prompt, step)

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
                obs = self._tool_step(tool_name, arg, step)

                trace.append(TraceEntry("tool", f"{tool_name}({arg}) -> {obs}"))
                scratchpad += f"{output}\nOBSERVATION: {obs}\n"
            else:
                trace.append(TraceEntry("final", final))

        metrics = Metrics.from_tracer(self.tracer, self.model_name)
        return final, trace, metrics

    @traceable(run_type="llm", name="llm_call")
    def _llm_step(self, prompt: str, step: int) -> str:
        input_tokens = len(prompt) // 4

        with self.tracer.span(
            f"llm_call_step_{step}", "llm",
            step=step, input_tokens=input_tokens,
        ) as llm_span:
            output = self.llm.complete(prompt)
            output_tokens = len(output) // 4
            llm_span.attributes["output_tokens"] = output_tokens
            llm_span.attributes["output_preview"] = output[:120]

        return output

    @traceable(run_type="tool", name="tool_call")
    def _tool_step(self, tool_name: str, arg: str, step: int) -> str:
        with self.tracer.span(
            f"tool_{tool_name}", "tool",
            tool_name=tool_name, argument=arg, step=step,
        ) as tool_span:
            obs = call_tool(self.toolbox, tool_name, arg)
            tool_span.attributes["result"] = obs
            if obs.startswith("（") and obs.endswith("）"):
                tool_span.attributes["error"] = obs

        return obs

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
# Demo
# ────────────────────────────────────────────────────────────

def demo() -> None:
    """LangSmith demo：FakeLLM，展示 @traceable 代码结构。"""
    print("\n" + "🔬" * 3 + " LangSmith 可观测性 Demo " + "🔬" * 3)
    print("演示：@traceable 装饰器 + 分层追踪（chain → llm → tool）\n")

    if langsmith_is_enabled():
        print("  ✅ LangSmith 已启用，trace 将上报到：")
        print(f"     项目：{os.environ.get('LANGSMITH_PROJECT', 'default')}")
        print(f"     地址：{os.environ.get('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com')}")
    else:
        print("  ⚠ LangSmith 未配置，trace 不会上报（demo 仍可正常运行）。")
        print("    启用方法：在 .env 中设置 LANGSMITH_TRACING=true 和 LANGSMITH_API_KEY=...")

    print()

    fake_llm = TracedFakeLLM([
        "THOUGHT: 先搜索 Python 是什么。\nACTION: search(python)",
        "THOUGHT: 再算一下数学。\nACTION: calc((1+2+3)*4)",
        "THOUGHT: 信息齐全了。\nFINAL: Python 是解释型高级语言，(1+2+3)*4 = 24。",
    ])

    agent = LangSmithReActAgent(
        llm=fake_llm,
        model_name="deepseek-chat",
        max_steps=6,
    )

    final, trace_entries, metrics = agent.run(
        "请告诉我 Python 是什么语言，并计算 (1+2+3)*4。"
    )

    print_trace_timeline(agent.tracer)
    print_metrics_report(metrics)

    if langsmith_is_enabled():
        print("\n  🔗 在 LangSmith 控制台查看完整 trace：https://smith.langchain.com")
    else:
        print("\n  💡 设置 LANGSMITH_TRACING=true 和 LANGSMITH_API_KEY 后，")
        print("     以上所有 @traceable 调用将自动上报到 LangSmith 控制台。")


def demo_with_real_llm() -> None:
    """LangSmith demo：真实 LLM + wrap_openai（需要 .env 配置）。"""
    print("\n" + "🔬" * 3 + " LangSmith Demo（真实 LLM + wrap_openai）" + "🔬" * 3)

    llm = create_traced_llm(name="langsmith-react", temperature=0.0)

    agent = LangSmithReActAgent(
        llm=llm,
        model_name=llm.model or "default",
        max_steps=6,
    )

    final, _, metrics = agent.run(
        "请告诉我 Python 是什么语言，并计算 (1+2+3)*4。"
    )

    print_trace_timeline(agent.tracer)
    print_metrics_report(metrics)


if __name__ == "__main__":
    import sys

    if "--real" in sys.argv:
        demo_with_real_llm()
    else:
        demo()
