"""把 params / streaming / errors 三个模块串起来跑一遍。

运行：
    uv run python -m learning_py.llm_api.demo

所有示例都**不访问外网**，用内置 Mock 客户端模拟 LLM 行为。
"""

from __future__ import annotations

import itertools
import time
from typing import Iterator

from learning_py.llm_api.errors import (
    LLMRateLimitError,
    LLMServerError,
    RetryPolicy,
    retry_call,
    CircuitBreaker,
)
from learning_py.llm_api.params import (
    SamplingParams,
    TaskType,
    TokenBudget,
    params_for,
)
from learning_py.llm_api.streaming import (
    StreamChunk,
    StreamOptions,
    consume_stream,
    mock_stream,
)


def _title(s: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{s}\n{line}")


# --------------------------------------------------------------------------- #
# Demo 1：按任务类型取参数 + 适配不同供应商
# --------------------------------------------------------------------------- #

def demo_params() -> None:
    _title("1. 采样参数：按任务选 Profile + 供应商适配")

    for task in [TaskType.EXTRACTION, TaskType.CODE, TaskType.CREATIVE]:
        p = params_for(task)
        print(f"\n[{task.value}] {p.as_dict()}")
        print(f"  OpenAI kwargs:    {p.to_openai_kwargs()}")
        print(f"  Anthropic kwargs: {p.to_anthropic_kwargs()}")

    # 局部覆盖
    custom = params_for(TaskType.CODE, max_tokens=8192, temperature=0.0)
    print(f"\n覆盖后（code + max_tokens=8192, T=0）: {custom.as_dict()}")

    # 校验失败
    print("\n非法参数会在构造时就报错：")
    try:
        SamplingParams(temperature=3.0)
    except ValueError as e:
        print(f"  ✅ 被拦截：{e}")

    # TokenBudget：防止 prompt + max_tokens 超窗口
    budget = TokenBudget(context_window=8192, reserved_output=1024)
    safe = budget.fit_max_tokens(prompt_tokens=7800, requested=2048)
    print(f"\nTokenBudget: prompt 用了 7800，想要 2048 → 实际给 {safe}")


# --------------------------------------------------------------------------- #
# Demo 2：流式消费 —— 首 token 延迟 / 回调 / 取消
# --------------------------------------------------------------------------- #

def demo_streaming_basic() -> None:
    _title("2. 流式：边生成边打印 + 统计首 token 延迟")

    printed: list[str] = []

    def on_chunk(c: StreamChunk) -> None:
        print(c.delta, end="", flush=True)
        printed.append(c.delta)

    text = "你好，这是一段用来演示 SSE 流式输出的模拟文本，每次返回几个字。"
    chunks = mock_stream(text, chunk_size=4, per_chunk_delay=0.02)

    result = consume_stream(chunks, StreamOptions(on_chunk=on_chunk))
    print()  # 换行
    print(
        f"\n首 token 延迟: {result.first_token_latency:.3f}s | "
        f"总耗时: {result.total_latency:.3f}s | "
        f"chunk 数: {result.chunk_count} | "
        f"finish: {result.finish_reason}"
    )


def demo_streaming_cancel() -> None:
    _title("3. 流式：用户中途取消（例如按了停止按钮）")

    counter = itertools.count()

    def should_stop() -> bool:
        # 跑到第 5 次检查时触发取消
        return next(counter) > 5

    text = "这是一段很长很长很长很长很长很长很长很长很长的文本。" * 5
    chunks = mock_stream(text, chunk_size=3)
    result = consume_stream(
        chunks,
        StreamOptions(should_stop=should_stop, on_chunk=lambda c: None),
    )
    print(f"已生成: {result.text!r}")
    print(f"cancelled={result.cancelled}, finish_reason={result.finish_reason}")


def demo_streaming_timeout() -> None:
    _title("4. 流式：idle_timeout 兜底（模型卡住了）")

    def slow_chunks() -> Iterator[StreamChunk]:
        yield StreamChunk(delta="开头")
        time.sleep(0.2)  # 故意拖很久
        yield StreamChunk(delta="继续", finish_reason="stop")

    result = consume_stream(
        slow_chunks(),
        StreamOptions(idle_timeout=0.1, on_chunk=lambda c: None),
    )
    print(f"text={result.text!r}, error={result.error!r}")


def demo_streaming_broken() -> None:
    _title("5. 流式：中途连接断开 —— 已生成文本不丢")

    chunks = mock_stream("保住已生成的文本很重要，" * 3, chunk_size=5, fail_at=3)
    result = consume_stream(chunks, StreamOptions(on_chunk=lambda c: None))
    print(f"已保住: {result.text!r}")
    print(f"error = {result.error!r}")


# --------------------------------------------------------------------------- #
# Demo 3：错误处理 —— 指数退避 + 熔断
# --------------------------------------------------------------------------- #

def demo_retry() -> None:
    _title("6. 错误处理：指数退避重试（前 2 次失败，第 3 次成功）")

    attempts = {"n": 0}
    sleeps: list[float] = []

    def unstable_call() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise LLMRateLimitError("被限流了", retry_after=0.1)
        if attempts["n"] == 2:
            raise LLMServerError("上游 502")
        return "finally ok!"

    policy = RetryPolicy(max_retries=3, base_delay=0.05, jitter=0.0)
    result = retry_call(unstable_call, policy, sleep=sleeps.append)
    print(f"调用 {attempts['n']} 次后成功，结果：{result}")
    print(f"每次等待：{[round(s, 3) for s in sleeps]}")


def demo_circuit_breaker() -> None:
    _title("7. 错误处理：熔断器 —— 连续失败自动切断，不再浪费调用")

    breaker = CircuitBreaker(failure_threshold=3, cooldown=0.1)

    def always_fail() -> str:
        raise LLMServerError("上游持续挂")

    for i in range(5):
        try:
            breaker.call(always_fail)
        except Exception as e:
            print(f"  第 {i + 1} 次：state={breaker.state:>10} | {type(e).__name__}: {e}")

    print("\n  等 cooldown 过去...")
    time.sleep(0.12)
    try:
        breaker.call(always_fail)
    except Exception as e:
        print(f"  half_open 探测失败，{type(e).__name__}: {e}，重新 OPEN")


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def main() -> None:
    demo_params()
    demo_streaming_basic()
    demo_streaming_cancel()
    demo_streaming_timeout()
    demo_streaming_broken()
    demo_retry()
    demo_circuit_breaker()


if __name__ == "__main__":
    main()
