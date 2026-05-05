"""Agent 记忆系统。

对应文档：`docs/agent-memory.md`

子模块：
- `short_term`：短期记忆（对话历史 + 滑窗 / token 预算 / 摘要压缩）
- `embedding`：可插拔的 Embedder 抽象，含零依赖 HashEmbedder + 可选 OpenAIEmbedder
- `vector_store`：纯 Python 实现的最小向量数据库（cosine 相似度）
- `long_term`：长期记忆（向量库 + TTL / 容量驱逐）
- `manager`：把短期 + 长期组合起来的 MemoryManager
- `demo`：跑一遍记忆驱动的对话（可对接真实 LLM，零依赖也能跑核心逻辑）
"""
