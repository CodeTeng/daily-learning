"""LLM API 工程化实践示例。

对应文档：`docs/llm-api-practices.md`

关注三类真正会在生产踩坑的问题：

- `params`：采样参数（temperature / top_p / max_tokens / frequency_penalty / seed…）
    的语义、取值范围与按任务类型预设的 Profile。
- `streaming`：SSE 风格的流式增量消费、取消、超时、token 统计。
- `errors`：OpenAI 风格错误分类、指数退避 + 抖动重试、熔断与幂等键。
- `demo`：一个**不依赖外部 API Key** 的 Mock 客户端，把三者串起来跑。
"""
