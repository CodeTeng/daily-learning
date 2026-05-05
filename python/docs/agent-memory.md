# Agent 记忆系统（Memory）

> 配套代码：[`src/learning_py/agent/memory/`](../src/learning_py/agent/memory/)
>
> Agent 没有记忆 = 每次问"我用什么编辑器"都得重新回答。
> 给它装个记忆 = 跨轮、跨会话都记得用户偏好、历史经验、知识资料。

---

## 1. 为什么需要"记忆"

LLM 本身的上下文窗口（哪怕 128K / 1M）有三个硬约束：

1. **会被填满**：长会话越聊越长，迟早超窗口。
2. **越长越贵**：每次都把全量历史塞进去，token 计费滚雪球。
3. **跨会话归零**：下次新开对话，模型完全不认识你。

记忆系统就是给 Agent 加一层「**持久化 + 选择性召回**」，让它"该记的记着、该忘的忘掉、该用的时候捞出来"。

---

## 2. 记忆的两层结构

| 层 | 角色 | 数据载体 | 容量 | 生命周期 |
| --- | --- | --- | --- | --- |
| **短期记忆**（Short-term） | 当前对话上下文 | 消息列表 | 上下文窗口 / token 预算 | 单次会话 |
| **长期记忆**（Long-term） | 跨会话事实 / 经验 / 知识 | 向量数据库 | TB 级（理论上） | 持久化 |

两者协作：

```
┌──────────────────────────────────────────────────────┐
│                       LLM                            │
└──────────────────────────────────────────────────────┘
              ▲ messages（system + 召回 + 历史）
              │
   ┌──────────┴──────────┐
   │   MemoryManager     │
   └──┬──────────────┬───┘
      │              │
      ▼              ▼
 短期记忆        长期记忆
 ────────       ────────
 滑窗 / 压缩    向量检索
 OpenAI msgs    cosine TopK
```

---

## 3. 短期记忆：滑窗 / 预算 / 压缩

短期记忆就是当前对话的消息列表 `[{role, content}]`，三个常见容量控制策略：

### 3.1 按条数滑窗（FIFO）

最简单：超过 N 条就丢最早的。**system 永远保留**。
适合短任务、token 预算很宽松的场景。

### 3.2 按 token 预算

更接近真实成本——估算每条消息的 token，超出预算就驱逐。
本仓库用 `estimate_tokens()` 做粗估（中文约 1.5 token/字、英文约 1.3 token/词）；
真实工程请用 `tiktoken` 精确计数。

### 3.3 摘要压缩（Summarization）

驱逐前**先让 LLM 把要丢的内容压成一段摘要**，再以 system 消息形式注入到上下文头部：

```
现状：[system, sys-2, sys-3, …, very old, …, recent]
压缩：把 very old 那批丢给 LLM 写成 "[历史摘要]" 再插到 system 后
结果：[system, "[历史摘要] …", recent]
```

这样既保留早期信息的精华，又把上下文长度压到可控范围。

**对应代码**：[`short_term.py`](../src/learning_py/agent/memory/short_term.py)，
核心类 `ShortTermMemory`，构造时传一个 `summarizer` 函数即可。

---

## 4. 长期记忆：向量数据库

### 4.1 原理

把每条记忆**编码成向量**，写入向量库；查询时把 query 也编码成向量，用 **cosine 相似度**找最相近的几条。

为什么不直接 SQL `LIKE` 匹配？因为人话查询和事实陈述往往**字面对不上**：

| 查询 | 事实 | LIKE | 向量 |
| --- | --- | --- | --- |
| "他用啥编辑器" | "用户使用 Cursor" | ❌ 找不到 | ✅ 高分 |
| "讨论过哪些 Python 机制" | "我们聊过 GIL" | ❌ 找不到 | ✅ 命中 |

### 4.2 Embedder 抽象

本仓库提供两种 embedding 实现，**接口完全一致**（`embed(text) -> list[float]`）：

| 实现 | 何时用 |
| --- | --- |
| `HashEmbedder` | 学习、单测，零依赖 / 确定性。仅按字面相似，**不是真正的语义相似** |
| `OpenAIEmbedder` | 真实场景，走 OpenAI 协议（OpenAI / 智谱 / 自建 BGE 等都支持） |

> ⚠️ DeepSeek 当前**不提供 embedding 接口**。要用 `OpenAIEmbedder` 请把
> `LLM_BASE_URL` 切到提供 embedding 的服务，或单独再设一组环境变量。
> 教学场景用默认 `HashEmbedder` 完全够。

**对应代码**：[`embedding.py`](../src/learning_py/agent/memory/embedding.py)。

### 4.3 向量库的最小实现

[`vector_store.py`](../src/learning_py/agent/memory/vector_store.py) 是一个不到 80 行、纯内存的最小向量库：

```python
store = InMemoryVectorStore(HashEmbedder(dim=512))
store.add("用户使用 macOS 与 Cursor 编辑器")
store.add("用户偏好简洁回答")

hits = store.query("他用什么编辑器？", top_k=2)
# hits[0].score = 0.546, hits[0].record.text = "用户使用 macOS 与 Cursor 编辑器"
```

接口刻意做得像 Chroma / Pinecone：`add` / `query` / `delete`。
真实工程请用专业方案（chromadb、qdrant、milvus、pgvector），但接口模式不变。

### 4.4 长期记忆的工程化包装

[`long_term.py`](../src/learning_py/agent/memory/long_term.py) 在向量库之上加了：

- **容量上限**：超出按 `created_at` 升序驱逐最旧的
- **TTL 过期**：检索时 lazy expire（避免后台线程）
- **更友好的 API**：`remember(text)` / `recall(query)` / `forget(id)`

```python
ltm = LongTermMemory(embedder=HashEmbedder(), capacity=1000, ttl_seconds=86400)
ltm.remember("用户偏好简洁回答")
hits = ltm.recall("用户的回答风格", top_k=3)
```

---

## 5. 检索与更新：MemoryManager

[`manager.py`](../src/learning_py/agent/memory/manager.py) 是统一门面，把短期 + 长期组合成一次完整的"对话回合"：

```python
mm = MemoryManager()
mm.short_term.add_system("你是技术助手")
mm.remember_fact("用户使用 macOS 与 Cursor 编辑器")  # 写入长期

# 一次对话：
user_msg = "我用什么编辑器来着？"
ctx = mm.build_context(user_input=user_msg)
#   ↑ 自动做了：召回长期记忆 → 以 [长期记忆召回] 的 system 块注入
#                + 把短期历史拼上
ctx.append({"role": "user", "content": user_msg})
answer = llm.chat(ctx)
mm.observe(user=user_msg, assistant=answer)  # 写入短期
```

**注入位置**很重要：召回内容**插在 system 之后、对话之前**，作为"既有事实"喂给模型。
这样 LLM 既知道"这是上下文不是用户当前问题"，又能保证规则比事实优先。

**写入策略**有两种风格：

1. **被动写入**：`observe(user, assistant)` 只更新短期，不主动写长期。
   长期记忆由调用方按业务规则（"用户说了一句重要的话") 显式 `remember_fact()`。
2. **主动抽取**：可以再加一个 LLM 调用，让模型自己判断"这一轮里有没有值得长期记忆的事实"。
   工业界 mem0 / LangChain Memory 走的就是这条路，但容易抽出噪音。

本仓库默认是**被动写入**——简单、可控；想升级成主动抽取，加一个抽取 prompt 即可。

---

## 6. 实测：带记忆 vs 不带记忆

`uv run python -m learning_py.agent.memory.demo llm` 跑出来的对话片段（DeepSeek deepseek-chat）：

```
预设长期记忆：
  - 用户的名字叫小李
  - 用户使用 macOS 与 Cursor 编辑器
  - 用户偏好极简回答，每次不超过 2 句话

第 1 轮  USER: 帮我推荐一个 Python Agent 框架
        ASSISTANT: ... 推荐 LangChain ...

第 2 轮  USER: 我用什么编辑器来着？
        ASSISTANT: 你使用的是 Cursor 编辑器，运行在 macOS 上。  ✅

第 3 轮  USER: 我叫什么名字？
        ASSISTANT: 根据之前的记忆，你叫小李。                    ✅
```

如果**不接长期记忆**，第 2、3 轮模型只能猜或诚实承认不知道。
所以记忆系统不是炫技——**它直接决定了 Agent 是不是"认得用户"**。

---

## 7. 怎么跑

### 7.1 安装与配置

依赖已在 `pyproject.toml` 里声明（`openai` + `python-dotenv`）：

```bash
cd python
uv sync
```

如果要跑 LLM demo（带记忆的多轮对话），还需要 `python/.env`（参考 [`agent-architectures.md`](./agent-architectures.md) §8.1）：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=deepseek-chat
```

### 7.2 跑 demo

```bash
cd python

# 全部跑（包含核心逻辑 + LLM 多轮对话）
uv run python -m learning_py.agent.memory.demo

# 只跑核心逻辑（零依赖、无费用）
uv run python -m learning_py.agent.memory.demo core

# 只跑 LLM 多轮对话（需 .env）
uv run python -m learning_py.agent.memory.demo llm

# 出错时打印 traceback
uv run python -m learning_py.agent.memory.demo --debug llm
```

### 7.3 跑测试

```bash
cd python
uv run pytest tests/test_agent_memory.py -q
```

测试只覆盖**与 LLM 无关的纯逻辑**：短期记忆滑窗 / 摘要插入位置、HashEmbedder 行为、向量库 top-k、长期记忆 TTL & 容量、MemoryManager 注入位置等。

---

## 8. 工程化注意事项

| 关注点 | 推荐做法 |
| --- | --- |
| **Embedding 模型** | 中文场景优先选 BGE / m3e / Cohere multilingual；OpenAI `text-embedding-3-small` 性价比高 |
| **向量库选型** | 单机简单：chromadb / sqlite-vss；分布式：qdrant / milvus；已有 Postgres：pgvector |
| **检索质量** | 加 reranker（cross-encoder）做二轮排序；或用 hybrid search（BM25 + 向量）补足关键字漏召 |
| **写入策略** | 防止"全部都记下来"——给长期记忆设容量、TTL、相似度去重 |
| **隐私 / 合规** | 用户敏感信息（手机号、住址）单独打标签；提供 `forget` 接口让用户能删除 |
| **冷启动** | 长期记忆为空时不要 recall（白白多一次 embedding 调用） |
| **成本** | embedding 调用要 batch（一次 N 条）；recall 命中阈值过滤掉相关度很低的结果 |

---

## 9. 配套阅读

- [`ai-agent.md`](./ai-agent.md) — Agent 四大能力（感知/推理/决策/执行）；记忆是"感知/决策"的输入源
- [`agent-architectures.md`](./agent-architectures.md) — 4 种 Agent 架构。本文实现的 MemoryManager 可以接到任意一种里
- [`prompt-engineering.md`](./prompt-engineering.md) — 召回内容怎么以 system 消息形式注入，本质上是 Prompt 拼接技巧
