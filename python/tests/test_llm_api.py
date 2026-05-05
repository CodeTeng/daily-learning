"""llm_api 模块的单元测试。

重点覆盖参数校验、重试、熔断、流式消费的行为边界，不依赖外部服务。
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from learning_py.llm_api.errors import (
    CircuitBreaker,
    LLMBadRequestError,
    LLMCircuitOpenError,
    LLMContentFilterError,
    LLMRateLimitError,
    LLMServerError,
    RetryPolicy,
    classify_http_error,
    retry_call,
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
    parse_sse_lines,
)


# --------------------------------------------------------------------------- #
# params
# --------------------------------------------------------------------------- #

class TestSamplingParams:
    def test_default_is_valid(self) -> None:
        p = SamplingParams()
        assert 0.0 <= p.temperature <= 2.0
        assert p.max_tokens > 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"temperature": -0.1},
            {"temperature": 2.1},
            {"top_p": 1.1},
            {"max_tokens": 0},
            {"frequency_penalty": -2.5},
            {"presence_penalty": 2.5},
        ],
    )
    def test_invalid_values_raise(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            SamplingParams(**kwargs)

    def test_openai_kwargs_omits_empty_stop_and_seed(self) -> None:
        p = SamplingParams()
        kw = p.to_openai_kwargs()
        assert "stop" not in kw
        assert "seed" not in kw

    def test_openai_kwargs_includes_stop_and_seed(self) -> None:
        p = SamplingParams(stop=("\n\n",), seed=42)
        kw = p.to_openai_kwargs()
        assert kw["stop"] == ["\n\n"]
        assert kw["seed"] == 42

    def test_anthropic_kwargs_drops_unsupported(self) -> None:
        p = SamplingParams(frequency_penalty=0.5, presence_penalty=0.5, seed=1)
        kw = p.to_anthropic_kwargs()
        assert "frequency_penalty" not in kw
        assert "presence_penalty" not in kw
        assert "seed" not in kw


class TestParamsFor:
    def test_extraction_is_deterministic(self) -> None:
        p = params_for(TaskType.EXTRACTION)
        assert p.temperature == 0.0
        assert p.seed is not None

    def test_creative_has_high_temperature(self) -> None:
        p = params_for(TaskType.CREATIVE)
        assert p.temperature >= 0.7

    def test_override_respected(self) -> None:
        p = params_for(TaskType.CODE, max_tokens=8192)
        assert p.max_tokens == 8192
        # 其他字段保持默认
        assert p.temperature == 0.2
        # stop 字段被保留为 tuple
        assert isinstance(p.stop, tuple)


class TestTokenBudget:
    def test_fit_max_tokens_shrinks_when_near_limit(self) -> None:
        b = TokenBudget(context_window=1000, reserved_output=200)
        assert b.fit_max_tokens(prompt_tokens=900, requested=500) == 100

    def test_fit_max_tokens_keeps_requested_when_room(self) -> None:
        b = TokenBudget(context_window=1000, reserved_output=200)
        assert b.fit_max_tokens(prompt_tokens=100, requested=500) == 500

    def test_overflow_prompt_raises(self) -> None:
        b = TokenBudget(context_window=1000, reserved_output=200)
        with pytest.raises(ValueError):
            b.fit_max_tokens(prompt_tokens=1000, requested=1)


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #

class TestClassify:
    def test_400_is_bad_request(self) -> None:
        assert isinstance(classify_http_error(400, "invalid"), LLMBadRequestError)

    def test_400_content_filter(self) -> None:
        err = classify_http_error(400, '{"error":{"code":"content_filter"}}')
        assert isinstance(err, LLMContentFilterError)

    def test_429_is_rate_limit(self) -> None:
        assert isinstance(classify_http_error(429), LLMRateLimitError)

    def test_5xx_is_server_error(self) -> None:
        assert isinstance(classify_http_error(503), LLMServerError)


class TestRetry:
    def test_succeeds_after_retriable_failures(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def fn() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise LLMServerError("503")
            return "ok"

        result = retry_call(
            fn, RetryPolicy(max_retries=5, base_delay=0.01, jitter=0.0),
            sleep=sleeps.append,
        )
        assert result == "ok"
        assert calls["n"] == 3
        assert len(sleeps) == 2  # 重试了 2 次

    def test_does_not_retry_bad_request(self) -> None:
        calls = {"n": 0}

        def fn() -> str:
            calls["n"] += 1
            raise LLMBadRequestError("invalid input")

        with pytest.raises(LLMBadRequestError):
            retry_call(fn, RetryPolicy(max_retries=3), sleep=lambda _s: None)
        assert calls["n"] == 1  # 一次都没重试

    def test_gives_up_after_max_retries(self) -> None:
        calls = {"n": 0}

        def fn() -> str:
            calls["n"] += 1
            raise LLMServerError("down")

        with pytest.raises(LLMServerError):
            retry_call(
                fn, RetryPolicy(max_retries=2, base_delay=0.0, jitter=0.0),
                sleep=lambda _s: None,
            )
        assert calls["n"] == 3  # 初次 + 2 次重试

    def test_rate_limit_retry_after_respected(self) -> None:
        sleeps: list[float] = []
        calls = {"n": 0}

        def fn() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMRateLimitError("slow down", retry_after=1.5)
            return "ok"

        retry_call(
            fn, RetryPolicy(max_retries=3, base_delay=0.01, jitter=0.0),
            sleep=sleeps.append,
        )
        assert sleeps[0] == pytest.approx(1.5, abs=0.01)


class TestCircuitBreaker:
    def test_opens_after_threshold(self) -> None:
        b = CircuitBreaker(failure_threshold=3, cooldown=10)

        def fail() -> None:
            raise LLMServerError("x")

        for _ in range(3):
            with pytest.raises(LLMServerError):
                b.call(fail)
        # 第 4 次应该直接被熔断拒绝
        with pytest.raises(LLMCircuitOpenError):
            b.call(fail)

    def test_bad_request_does_not_open(self) -> None:
        b = CircuitBreaker(failure_threshold=2, cooldown=10)

        def fail() -> None:
            raise LLMBadRequestError("bad")

        for _ in range(5):
            with pytest.raises(LLMBadRequestError):
                b.call(fail)
        assert b.state == CircuitBreaker.CLOSED

    def test_success_resets_counter(self) -> None:
        b = CircuitBreaker(failure_threshold=3, cooldown=10)
        calls = iter([False, False, True, False, False])  # 第 3 次成功

        def maybe() -> str:
            if next(calls):
                return "ok"
            raise LLMServerError("x")

        # 前两次失败
        for _ in range(2):
            with pytest.raises(LLMServerError):
                b.call(maybe)
        # 第三次成功
        assert b.call(maybe) == "ok"
        assert b.state == CircuitBreaker.CLOSED
        # 再来两次失败不应触发熔断（计数已重置）
        for _ in range(2):
            with pytest.raises(LLMServerError):
                b.call(maybe)
        assert b.state == CircuitBreaker.CLOSED


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #

class TestSSEParser:
    def test_parses_data_lines(self) -> None:
        lines = [
            ": heartbeat",  # 注释
            "",
            'data: {"choices":[{"delta":{"content":"Hi"}}]}',
            'data: {"choices":[{"delta":{"content":" there"}}]}',
            "data: [DONE]",
            'data: {"should":"be ignored"}',  # DONE 之后不再产出
        ]
        events = list(parse_sse_lines(lines))
        assert len(events) == 2
        assert events[0]["choices"][0]["delta"]["content"] == "Hi"

    def test_skips_invalid_json(self) -> None:
        lines = ["data: not-json", 'data: {"ok":true}']
        events = list(parse_sse_lines(lines))
        assert events == [{"ok": True}]


class TestConsumeStream:
    def test_collects_all_text(self) -> None:
        result = consume_stream(mock_stream("hello world", chunk_size=3))
        assert result.text == "hello world"
        assert result.finish_reason == "stop"
        assert result.error is None
        assert result.cancelled is False
        assert result.first_token_latency is not None

    def test_on_chunk_called_for_each_delta(self) -> None:
        seen: list[str] = []
        consume_stream(
            mock_stream("abcdef", chunk_size=2),
            StreamOptions(on_chunk=lambda c: seen.append(c.delta) if c.delta else None),
        )
        assert "".join(seen) == "abcdef"

    def test_callback_exception_does_not_break_stream(self) -> None:
        def bad_cb(_c: StreamChunk) -> None:
            raise RuntimeError("callback error")

        result = consume_stream(
            mock_stream("abcdef", chunk_size=2),
            StreamOptions(on_chunk=bad_cb),
        )
        assert result.text == "abcdef"

    def test_cancel_preserves_partial_text(self) -> None:
        tick = itertools.count()
        result = consume_stream(
            mock_stream("aaaaaaaaaaaaaaaa", chunk_size=2),
            StreamOptions(should_stop=lambda: next(tick) > 2),
        )
        assert result.cancelled is True
        assert len(result.text) > 0
        assert len(result.text) < 16

    def test_broken_stream_keeps_collected_text(self) -> None:
        result = consume_stream(mock_stream("abcdefghij", chunk_size=2, fail_at=2))
        # 前 2 块（4 字）拿到了，第 3 块抛异常
        assert result.text == "abcd"
        assert isinstance(result.error, ConnectionError)

    def test_max_chars_stops_early(self) -> None:
        result = consume_stream(
            mock_stream("a" * 100, chunk_size=5),
            StreamOptions(max_chars=20),
        )
        assert len(result.text) >= 20
        assert result.finish_reason == "max_chars"

    def test_total_timeout_triggers(self) -> None:
        # 用假时钟：每次调用 now 时间前进 1 秒
        clock = itertools.count(start=0, step=1.0)

        def fake_now() -> float:
            return float(next(clock))

        def many_chunks() -> Iterator[StreamChunk]:
            return (StreamChunk(delta="x") for _ in range(100))

        result = consume_stream(
            many_chunks(),
            StreamOptions(total_timeout=3, idle_timeout=100),
            now=fake_now,
        )
        assert isinstance(result.error, TimeoutError)
        assert "total_timeout" in str(result.error)
