"""Agent 架构模式示例。

对应文档：`docs/agent-architectures.md`

子模块：
- `tools`：可执行的工具箱（search / calc / translate）和执行轨迹辅助类型
- `llm_client`：OpenAI 协议兼容的 LLM 客户端（DeepSeek / OpenAI / 任意网关）
- `react_agent`：ReAct（Reasoning + Acting）
- `plan_and_execute`：先计划后执行
- `reflection_agent`：Reflection（自我反思）
- `multi_agent`：Multi-Agent 协作
- `demo`：用真实 LLM 把 4 种架构跑一遍

运行（需先在 `python/.env` 配置 LLM）：
    uv run python -m learning_py.agent.demo
"""
