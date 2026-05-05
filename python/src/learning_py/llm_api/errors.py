"""LLM API 错误处理：分类、重试、熔断。

实战里调 LLM API 至少要处理 4 类错误，处理策略完全不同：

| 类别 | HTTP | 能否重试 | 策略 |
| --- | --- | --- | --- |
| 入参错误 | 400 / 422 | ❌ 重试也没用 | 直接抛给上层，打日志 |
| 鉴权/权限 | 401 / 403 | ❌ 密钥问题 | 快速失败 + 告警 |
| 限流 | 429 | ✅ | 指数退避 + 抖动，尊重 Retry-After |
| 服务端/网络 | 5xx / timeout | ✅ | 指数退避，超过 N 次熔断 |
| 内容审核 | 400 (content_filter) | ❌ | 换 Prompt 或换模型 |

**关键原则**：不要对所有异常一把梭 retry —— 对 4xx 入参错误无限重试，
只是把钱烧得更快而已。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


# --------------------------------------------------------------------------- #
# 1. 统一错误体系
# --------------------------------------------------------------------------- #

class LLMError(Exception):
    """所有 LLM 相关错误的基类。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMBadRequestError(LLMError):
    """入参错误，不可重试。"""


class LLMAuthError(LLMError):
    """鉴权/权限错误，不可重试。"""


class LLMRateLimitError(LLMError):
    """被限流，可重试。可能带 Retry-After。"""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class LLMServerError(LLMError):
    """服务端 5xx，可重试。"""


class LLMTimeoutError(LLMError):
    """网络超时，可重试。"""


class LLMContentFilterError(LLMError):
    """输出被内容安全拦截，重试不会变好。"""


class LLMCircuitOpenError(LLMError):
    """熔断器打开，快速失败。"""


# 哪些异常可以重试？集中一处定义，避免到处写 isinstance
RETRIABLE = (LLMRateLimitError, LLMServerError, LLMTimeoutError)


def classify_http_error(status: int, body: str = "") -> LLMError:
    """把 HTTP 响应转成上面的具体异常。真实接入时用这个做转换层。"""
    if status == 400:
        # OpenAI 内容审核也会返 400，body 里带 content_filter
        if "content_filter" in body or "content_policy" in body:
            return LLMContentFilterError(body, status_code=400)
        return LLMBadRequestError(body, status_code=400)
    if status in (401, 403):
        return LLMAuthError(body, status_code=status)
    if status == 429:
        return LLMRateLimitError(body)
    if 500 <= status < 600:
        return LLMServerError(body, status_code=status)
    return LLMError(body, status_code=status)


# --------------------------------------------------------------------------- #
# 2. 指数退避 + 抖动重试
# --------------------------------------------------------------------------- #

@dataclass
class RetryPolicy:
    """指数退避重试配置。

    第 n 次重试（n 从 0 开始）等待时间：
        sleep = min(base * 2**n, max_delay)
        sleep += random.uniform(0, jitter)

    抖动（jitter）必须加，否则一堆客户端会在同一时刻雪崩重试。
    """

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: float = 0.3

    def sleep_for(self, attempt: int, retry_after: float | None = None) -> float:
        """算出第 attempt 次重试前应等待多久。"""
        if retry_after is not None:
            # 服务端给了 Retry-After，优先尊重它（但也加点抖动错峰）
            return retry_after + random.uniform(0, self.jitter)
        backoff = min(self.base_delay * (2 ** attempt), self.max_delay)
        return backoff + random.uniform(0, self.jitter)


def retry_call(
    fn: Callable[[], T],
    policy: RetryPolicy | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """包一层重试。只对 RETRIABLE 这几种异常生效。

    `sleep` 参数注入方便测试（传一个累加器进去）。
    """
    policy = policy or RetryPolicy()
    last_exc: Exception | None = None
    for attempt in range(policy.max_retries + 1):
        try:
            return fn()
        except RETRIABLE as exc:
            last_exc = exc
            if attempt == policy.max_retries:
                break
            retry_after = getattr(exc, "retry_after", None)
            sleep(policy.sleep_for(attempt, retry_after))
        except LLMError:
            # 不可重试的业务错误，原样抛出
            raise
    assert last_exc is not None
    raise last_exc


# --------------------------------------------------------------------------- #
# 3. 简易熔断器
# --------------------------------------------------------------------------- #

class CircuitBreaker:
    """最小实现的熔断器。

    - CLOSED：正常；连续失败达到 threshold 就 → OPEN
    - OPEN：直接抛 `LLMCircuitOpenError`，过 cooldown 秒后 → HALF_OPEN
    - HALF_OPEN：放一次探测请求；成功 → CLOSED，失败 → OPEN

    真实生产建议用 `pybreaker` / `tenacity`，这里只是演示核心状态机。
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, *, failure_threshold: int = 5, cooldown: float = 10.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._state = self.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def _now(self) -> float:
        return time.monotonic()

    def before_call(self) -> None:
        if self._state == self.OPEN:
            if self._now() - self._opened_at >= self.cooldown:
                self._state = self.HALF_OPEN
            else:
                raise LLMCircuitOpenError("熔断器打开，拒绝请求")

    def on_success(self) -> None:
        self._failure_count = 0
        self._state = self.CLOSED

    def on_failure(self, exc: BaseException) -> None:
        # 只计入服务端/限流类错误，400 这种不算
        if not isinstance(exc, RETRIABLE):
            return
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = self._now()

    def call(self, fn: Callable[[], T]) -> T:
        self.before_call()
        try:
            result = fn()
        except BaseException as exc:
            self.on_failure(exc)
            raise
        else:
            self.on_success()
            return result
