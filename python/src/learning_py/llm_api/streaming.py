"""LLM 流式响应处理。

为什么要流式？

- **首 token 延迟（TTFT）**：用户按下回车到看到第一个字的时间。非流式要
    等模型把整段话生成完才返回，体感 3~10 秒起步；流式边生成边返回，
    1 秒内就能看到第一个字。
- **可提前终止**：用户划走了 / 答案已够 / 检测到危险内容，可以立刻断开，
    不用白烧剩下几百个 token 的钱。
- **超长响应**：2 万 token 一次性返回，连接可能被网关/CDN 掐掉；流式
    每块都有数据，keep-alive 稳。

OpenAI / Anthropic / 通义 等都是用 **SSE（Server-Sent Events）**：
每块形如

    data: {"choices":[{"delta":{"content":"你好"}}]}\n\n
    data: {"choices":[{"delta":{"content":"，世界"}}]}\n\n
    data: [DONE]\n\n

本模块提供：

- `StreamChunk`：一块增量的抽象
- `parse_sse_lines`：SSE 协议解析
- `consume_stream`：带超时、取消、token 统计的通用消费器
- `MockStream`：零依赖 mock，方便写 demo 和单测
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator


# --------------------------------------------------------------------------- #
# 1. 抽象数据结构
# --------------------------------------------------------------------------- #

@dataclass
class StreamChunk:
    """一块流式增量。抽象掉具体供应商的字段差异。"""

    delta: str                      # 新增的文本
    finish_reason: str | None = None  # stop / length / content_filter / None
    raw: dict | None = None         # 原始 chunk，debug 用


@dataclass
class StreamResult:
    """流式消费结束后的汇总。"""

    text: str = ""
    finish_reason: str | None = None
    first_token_latency: float | None = None  # 首 token 延迟（秒）
    total_latency: float = 0.0
    chunk_count: int = 0
    cancelled: bool = False
    error: Exception | None = None


# --------------------------------------------------------------------------- #
# 2. SSE 协议解析
# --------------------------------------------------------------------------- #

def parse_sse_lines(lines: Iterable[str]) -> Iterator[dict]:
    """解析 SSE 字节流。每遇到 `data: xxx` 就 yield 一个 dict。

    - `data: [DONE]` 结束标记直接返回
    - 空行 / 注释（`:` 开头）忽略
    - 非法 JSON 跳过（真实接入建议打一条 warning）
    """
    for line in lines:
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def openai_chunk_to_stream_chunk(raw: dict) -> StreamChunk | None:
    """把 OpenAI 风格的 chunk 转成统一的 `StreamChunk`。

    OpenAI 的 chunk 长这样：
        {"choices": [{"delta": {"content": "你好"}, "finish_reason": null}]}
    """
    choices = raw.get("choices") or []
    if not choices:
        return None
    choice = choices[0]
    delta = (choice.get("delta") or {}).get("content") or ""
    finish = choice.get("finish_reason")
    if not delta and finish is None:
        return None
    return StreamChunk(delta=delta, finish_reason=finish, raw=raw)


# --------------------------------------------------------------------------- #
# 3. 通用消费器：超时、取消、回调、统计
# --------------------------------------------------------------------------- #

@dataclass
class StreamOptions:
    """流式消费的运行期选项。"""

    # 整个响应的最大耗时（秒），超过就中断
    total_timeout: float = 60.0
    # 两次 chunk 之间的最长间隔（秒），防止模型"卡死"
    idle_timeout: float = 15.0
    # 生成达到这么多字符就主动停止（用于省钱兜底）
    max_chars: int | None = None
    # 外部取消信号：返回 True 表示用户点了「停止」
    should_stop: Callable[[], bool] = field(default=lambda: False)
    # 每拿到一块就回调一次，典型用途：往 WebSocket 推 / 打印
    on_chunk: Callable[[StreamChunk], None] = field(default=lambda _c: None)


def consume_stream(
    chunks: Iterable[StreamChunk],
    options: StreamOptions | None = None,
    *,
    now: Callable[[], float] = time.monotonic,
) -> StreamResult:
    """消费一个 `StreamChunk` 迭代器，返回汇总结果。

    设计要点：
    - 首 token 延迟单独记录，这是线上最重要的体验指标之一
    - idle timeout / total timeout 分开，前者防模型卡顿，后者兜底总耗时
    - cancel 和 timeout 都走「正常结束」，不抛异常，因为已经有部分文本
    """
    options = options or StreamOptions()
    result = StreamResult()

    start = now()
    last_chunk_at = start
    buf: list[str] = []

    try:
        for chunk in chunks:
            current = now()

            # 1) 外部取消
            if options.should_stop():
                result.cancelled = True
                break

            # 2) 总超时
            if current - start > options.total_timeout:
                result.error = TimeoutError(
                    f"total_timeout {options.total_timeout}s 已超"
                )
                break

            # 3) 空闲超时（两个 chunk 之间太久没动静）
            if current - last_chunk_at > options.idle_timeout:
                result.error = TimeoutError(
                    f"idle_timeout {options.idle_timeout}s 已超"
                )
                break
            last_chunk_at = current

            # 4) 首 token 延迟
            if result.first_token_latency is None and chunk.delta:
                result.first_token_latency = current - start

            # 5) 累积内容 + 回调
            if chunk.delta:
                buf.append(chunk.delta)
                result.chunk_count += 1
                try:
                    options.on_chunk(chunk)
                except Exception:  # 回调异常不能把整条流搞挂
                    pass

            # 6) max_chars 兜底
            if options.max_chars is not None:
                if sum(len(s) for s in buf) >= options.max_chars:
                    result.finish_reason = "max_chars"
                    break

            # 7) 模型主动结束
            if chunk.finish_reason is not None:
                result.finish_reason = chunk.finish_reason
                break
    except Exception as exc:
        # 网络中断等运行期错误：保留已经拿到的部分文本
        result.error = exc

    result.text = "".join(buf)
    result.total_latency = now() - start
    return result


# --------------------------------------------------------------------------- #
# 4. Mock Stream：零依赖 demo / 单测用
# --------------------------------------------------------------------------- #

def mock_stream(
    text: str,
    *,
    chunk_size: int = 4,
    per_chunk_delay: float = 0.0,
    fail_at: int | None = None,
) -> Iterator[StreamChunk]:
    """把一段文本切成若干 chunk yield 出来，模拟真实流式。

    - `chunk_size`：每块几个字
    - `per_chunk_delay`：块间 sleep，模拟网络
    - `fail_at`：到第几块时抛异常，模拟中途断流
    """
    i = 0
    idx = 0
    while idx < len(text):
        if fail_at is not None and i == fail_at:
            raise ConnectionError(f"mock 在第 {i} 块中断")
        piece = text[idx : idx + chunk_size]
        idx += chunk_size
        i += 1
        if per_chunk_delay:
            time.sleep(per_chunk_delay)
        yield StreamChunk(delta=piece)
    # 正常结束
    yield StreamChunk(delta="", finish_reason="stop")
