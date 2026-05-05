"""Tool Calling（工具调用）学习示例。

对应文档：`docs/tool-calling.md`

覆盖工具调用的 4 个核心环节（源自学习路线「工具调用【必学】」）：

1. **Function Calling**：LLM 输出结构化"我想调哪个工具"的协议
2. **工具定义和描述**：把 Python 函数转成 JSON Schema，交给 LLM 看
3. **工具参数解析**：把 LLM 吐出的 JSON 参数用 Pydantic 安全还原成 Python 值
4. **工具执行和结果返回**：执行 + 错误兜底 + 把结果喂回下一轮

子模块：
- `schema`：用 `pydantic.create_model` 把函数签名 → JSON Schema；同时产出
    `TypeAdapter` 给运行期参数校验用
- `registry`：`ToolRegistry` 注册 / 查找 / 执行工具；`ToolCall` / `ToolResult`
    都是 Pydantic 模型
- `loop`：完整的多轮 Tool Calling 循环，接任意实现 `LLMClient` 协议的客户端
- `openai_client`：OpenAI 兼容协议的客户端实现（支持 DeepSeek / 通义 等第三方）
- `demo`：接 `.env` 里的真实 LLM，把四个环节端到端跑一遍
"""
