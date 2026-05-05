# LLM API 工程化实践：参数 / 流式 / 错误处理

> 对应代码：[`src/learning_py/llm_api/`](../src/learning_py/llm_api/)
>
> 运行演示：
> ```bash
> uv run python -m learning_py.llm_api.demo
> ```

调大模型 API 和调一个普通 REST 接口，**工程上完全不是一回事**。本文聚焦线上真会踩坑的三块：

1. 采样参数：选错温度，下游解析率掉两位数
2. 流式处理：首 token 延迟是线上最重要的体验指标之一
3. 错误处理：5xx / 429 / 超时各有各的策略，不能一把梭

---

## 1. 采样参数

### 1.1 核心参数速查表

| 参数 | 范围 | 作用 | 经验值 |
| --- | --- | --- | --- |
| `temperature` | 0.0 ~ 2.0 | 采样温度。0 最确定，越高越发散 | 抽取 0、翻译 0.2、写作 0.9 |
| `top_p` | 0.0 ~ 1.0 | 核采样，只从累积概率 top_p 的 token 里挑 | 保持默认 1.0 |
| `max_tokens` | int | 单次响应最多生成的 token 数 | **必设**，默认给一个偏保守值 |
| `frequency_penalty` | -2.0 ~ 2.0 | 正值抑制重复 token | 写作任务可给 0.2 ~ 0.5 |
| `presence_penalty` | -2.0 ~ 2.0 | 正值鼓励引入新话题 | 写作任务可给 0.2 ~ 0.5 |
| `stop` | list[str] | 命中即停止生成 | 代码场景设 `"\n```\n"` |
| `seed` | int | 尽量可复现 | 抽取/分类任务固定一个值 |

### 1.2 temperature 和 top_p：只调一个

两者都是控制随机性的，**同时调会让行为变得难以预测**。经验法则：
- 默认只调 `temperature`，`top_p` 保持 1.0
- 除非你明确知道自己在干嘛，否则不要两个一起调

### 1.3 max_tokens 必须设

线上出过的事故：某同学没设 `max_tokens`，用户一个恶意 Prompt 让模型写了 1 万 token，一次调用烧了 4 毛钱。一天下来 API 账单直接起飞。

**更严谨的做法**是算 Token Budget —— 确保 `prompt_tokens + max_tokens <= context_window`：

```python
from learning_py.llm_api.params import TokenBudget

budget = TokenBudget(context_window=8192, reserved_output=1024)
safe = budget.fit_max_tokens(prompt_tokens=7800, requested=2048)
# 上下文只剩 392 token 了，safe == 392
```

### 1.4 按任务类型预设 Profile

不要把魔法数字散落在业务代码各处。定义好任务类型 → 参数的映射，调用处只写：

```python
from learning_py.llm_api.params import params_for, TaskType

params = params_for(TaskType.EXTRACTION)            # 抽取：T=0, seed=42
params = params_for(TaskType.CREATIVE)              # 写作：T=0.9 + 频率惩罚
params = params_for(TaskType.CODE, max_tokens=8192) # 局部覆盖
```

这样做的好处：
- **统一口径**：所有团队成员对"抽取任务用什么参数"有一致答案
- **易于 A/B**：想把抽取任务的温度从 0 改成 0.1 试试，只改一处
- **便于回归**：哪天某个任务效果抖动了，先看是不是 Profile 被改了

### 1.5 供应商差异：在边界处适配

OpenAI 叫 `max_tokens`，Anthropic 也叫 `max_tokens` 但**必填**，Google Gemini 叫 `max_output_tokens`。不要让业务代码关心这些差异：

```python
params.to_openai_kwargs()     # {"temperature": 0, "max_tokens": 1024, ...}
params.to_anthropic_kwargs()  # Anthropic 不支持 frequency/presence/seed
```

---

## 2. 流式处理（Streaming）

### 2.1 为什么一定要流式

- **首 token 延迟（TTFT, Time To First Token）**：用户按下回车到看见第一个字的时间。
  - 非流式：等整段生成完才返回，3~10 秒起步，用户以为卡了
  - 流式：1 秒内就看见第一个字，体感完全不同
- **可提前终止**：用户关了页面 / 答案已经够了 / 检测到有害内容，立刻断开，省下剩余 token 的钱
- **长响应更稳**：2 万 token 的响应一次性返回，中间任何一个网关/CDN 超时就全挂；流式每块都有数据，keep-alive 不断

### 2.2 SSE 协议速览

OpenAI / Anthropic / 通义 / 智谱 几乎都是 SSE：

```
data: {"choices":[{"delta":{"content":"你好"}}]}

data: {"choices":[{"delta":{"content":"，世界"}}]}

data: {"choices":[{"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

- 每条消息以 `data: ` 开头，以 `\n\n` 分隔
- 最后一条一定是 `data: [DONE]`
- `:` 开头的是注释（心跳），忽略

解析实现见 [`streaming.py`](../src/learning_py/llm_api/streaming.py) 的 `parse_sse_lines`。

### 2.3 消费一条流需要处理的 6 件事

不要只会 `for chunk in stream: print(chunk)`。线上流式消费必须覆盖：

| 关注点 | 为什么重要 | 本项目实现 |
| --- | --- | --- |
| **首 token 延迟** | 核心体验指标，要打点上报 | `StreamResult.first_token_latency` |
| **总超时** | 防止流无限拖 | `StreamOptions.total_timeout` |
| **空闲超时** | 两块之间超过 N 秒，八成是卡住了 | `StreamOptions.idle_timeout` |
| **外部取消** | 用户点了停止 / WebSocket 断开 | `StreamOptions.should_stop` |
| **最大字符数** | 兜底防烧钱 | `StreamOptions.max_chars` |
| **已生成文本保留** | 中途断流，别把已到达的内容也丢了 | `StreamResult.text` 即使报错也保留 |

### 2.4 推送给前端的常见模式

Python 侧用 FastAPI 举例：

```python
from fastapi.responses import StreamingResponse
from learning_py.llm_api.streaming import consume_stream, StreamOptions

async def chat(request):
    def event_source():
        def on_chunk(chunk):
            # SSE 格式推给前端
            yield f"data: {chunk.delta}\n\n"

        # 注意：实际项目里 on_chunk 是回调，这里只是示意
        result = consume_stream(upstream_chunks, StreamOptions(on_chunk=on_chunk))
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

线上还要注意：

- **反向代理要关缓冲**：Nginx 必须设 `proxy_buffering off`，否则网关把 chunk 攒一大块才吐给客户端，流式退化成非流式
- **心跳**：长连接经过某些中间层 30~60 秒无数据就会被掐，定期发 `: keep-alive\n\n` 注释行
- **优雅降级**：前端收到 `[DONE]` 之前连接断了，要能恢复已展示的部分内容

---

## 3. 错误处理

### 3.1 错误分类决定策略

把所有异常当 `except Exception` 捞起来重试，是**代价最高的错误写法**。不同错误的策略天差地别：

| 类别 | HTTP | 能否重试 | 策略 |
| --- | --- | --- | --- |
| 入参错误 | 400 / 422 | ❌ | 直接抛，打 ERROR 日志 |
| 鉴权/权限 | 401 / 403 | ❌ | 快速失败 + 告警 |
| 限流 | 429 | ✅ | 指数退避 + 尊重 Retry-After |
| 服务端错误 | 5xx | ✅ | 指数退避，超阈值熔断 |
| 网络超时 | — | ✅ | 指数退避 |
| 内容审核 | 400 + content_filter | ❌ | 换 Prompt 或换模型 |

对应到代码就是一套细分的异常体系：`LLMBadRequestError` / `LLMAuthError` /
`LLMRateLimitError` / `LLMServerError` / `LLMTimeoutError` /
`LLMContentFilterError`。**只对可重试的三类做 retry**，见 [`errors.py`](../src/learning_py/llm_api/errors.py) 的 `RETRIABLE` 白名单。

### 3.2 指数退避 + 抖动

重试间隔必须指数增长，否则雪崩来临时客户端会反复打在同一时刻，把上游彻底打挂。

```python
# 第 n 次重试等待：
sleep = min(base * 2**n, max_delay) + random.uniform(0, jitter)
```

**抖动（jitter）必须加**。没有 jitter 的重试，本质上是把一堆客户端的重试对齐到了同一个时刻。

### 3.3 尊重 Retry-After

被限流时，服务端通常会在响应头里告诉你「等 X 秒再来」。实现里要优先用这个值：

```python
def sleep_for(self, attempt, retry_after=None):
    if retry_after is not None:
        return retry_after + random.uniform(0, self.jitter)
    return min(self.base_delay * 2**attempt, self.max_delay) + random.uniform(0, self.jitter)
```

### 3.4 熔断器：别把上游彻底打挂

当下游持续失败时（比如 OpenAI 整条区域挂了），继续重试只是让自己也挂得更快。熔断器的作用是：**连续失败 N 次后，N 秒内直接快速失败，不再发请求**。

三态状态机：

```
CLOSED  --连续失败超阈值-->  OPEN
  ^                           |
  |                      cooldown 到期
  |                           |
  +-- 探测成功 -- HALF_OPEN <-+
```

HALF_OPEN 状态放 1 次探测请求：成功就回 CLOSED，失败就回 OPEN 并重置计时。

真实生产建议直接用 [`pybreaker`](https://github.com/danielfm/pybreaker) / [`tenacity`](https://github.com/jd/tenacity)，本项目的实现主要是演示状态机。

### 3.5 幂等键（Idempotency Key）

**特别注意**：带副作用的调用（比如创建订单后调 LLM 发通知）做重试时，要附带幂等键，防止"重试其实服务端已经成功了"导致重复执行。OpenAI 等 API 已支持在请求头加 `Idempotency-Key`，业务层也应自己做一份防护。

---

## 4. 把三者串起来的调用骨架

一个生产可用的调用，至少要这么写：

```python
from learning_py.llm_api.errors import RetryPolicy, retry_call, CircuitBreaker
from learning_py.llm_api.params import params_for, TaskType
from learning_py.llm_api.streaming import consume_stream, StreamOptions

params = params_for(TaskType.QA)         # 1. 参数来自 Profile
breaker = CircuitBreaker()               # 2. 模块级单例
policy = RetryPolicy(max_retries=3)

def call_once() -> str:
    # 真实实现：client.chat.completions.create(..., stream=True, **params.to_openai_kwargs())
    raw_chunks = fake_llm_stream(params)
    result = consume_stream(
        raw_chunks,
        StreamOptions(
            total_timeout=60,
            idle_timeout=15,
            on_chunk=push_to_websocket,
        ),
    )
    if result.error:
        raise result.error       # 让上层的 retry_call 判断是否重试
    return result.text

# 熔断 外面套一层 重试
answer = breaker.call(lambda: retry_call(call_once, policy))
```

顺序很重要：**retry 在内，breaker 在外**。这样"单次调用"的重试算一次完整尝试，
熔断器只在"这一整次尝试"失败时计数，不会因为内部重试了 3 次就误判为 3 次失败。

---

## 5. 一页纸 Checklist

上线前过一遍：

- [ ] `max_tokens` 设了吗？算过 prompt + max_tokens 不会超上下文窗口吗？
- [ ] 采样参数是从统一 Profile 取的，还是散落的魔法数字？
- [ ] temperature 和 top_p 是不是只调了其中一个？
- [ ] 非流式改成流式了吗？首 token 延迟打点上报了吗？
- [ ] 流式处理有 total_timeout / idle_timeout 兜底吗？
- [ ] 异常有按 4xx / 5xx / 429 / timeout 分类处理吗？
- [ ] 重试用了指数退避 + 抖动吗？429 尊重 Retry-After 了吗？
- [ ] 有熔断器吗？阈值和 cooldown 设了合理值吗？
- [ ] 带副作用的调用有幂等键吗？
- [ ] Nginx / 网关关了 SSE 缓冲吗？
