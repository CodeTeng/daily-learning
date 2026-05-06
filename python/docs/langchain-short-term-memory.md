# LangChain / LangGraph 短期记忆（Short-Term Memory）

> 配套代码：[`src/learning_py/langchain_framework/short_term_memory.py`](../src/learning_py/langchain_framework/short_term_memory.py)
>
> 短期记忆 = **当前会话的消息列表**。它让 LLM 在同一个 thread_id 下"记得刚才聊了什么"。

---

## 1. 为什么需要短期记忆

LLM 本身是无状态的——每次调用都是一个"全新的大脑"。不做记忆管理的话：

| 问题 | 后果 |
|---|---|
| **上下文无限增长** | 超出模型窗口 → 报错 / 截断 |
| **成本滚雪球** | 每次都把全量历史塞进去，token 计费指数级上升 |
| **响应变慢** | 上下文越长，推理延迟越高 |

短期记忆的核心职责：**保留最近的对话上下文，丢弃或压缩旧的，让 LLM 在可控窗口内工作。**

---

## 2. 短期记忆 vs 长期记忆

| 维度 | 短期记忆 | 长期记忆 |
|---|---|---|
| **实现** | `State` + `Checkpointer`（如 `InMemorySaver`） | `Store`（如 `InMemoryStore`） |
| **作用域** | 单个 `thread_id`（线程级别） | 跨 `thread_id` / 跨会话 |
| **存储内容** | 对话历史、状态数据、中间结果 | 用户偏好、历史事实、跨会话知识 |
| **生命周期** | 与线程绑定 | 持久化 |
| **对应 API** | `trim_messages()` / `RemoveMessage` / 摘要 | `store.put()` / `store.search()` |

两者的关系：

```
┌─────────────────────────────────────────────┐
│                    LLM                        │
└─────────────────────────────────────────────┘
           ▲ 组装后的 messages
           │
    ┌──────┴──────────┐
    │  MemoryManager  │
    └──┬───────────┬──┘
       │           │
       ▼           ▼
  短期记忆      长期记忆
  ────────      ────────
  Checkpointer  Store
  thread 级别   跨 session 级别
```

---

## 3. 核心机制：State + Checkpointer

在 LangGraph 中，**短期记忆 = 图状态 + Checkpointer**。不需要额外的"记忆类"——编译图时传入 `checkpointer`，用 `thread_id` 区分会话即可：

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, MessagesState

checkpointer = InMemorySaver()

builder = StateGraph(MessagesState)
builder.add_node(call_model)
builder.add_edge(START, "call_model")
graph = builder.compile(checkpointer=checkpointer)

# 两个独立的会话
config_bob = {"configurable": {"thread_id": "user-bob"}}
config_alice = {"configurable": {"thread_id": "user-alice"}}

graph.invoke({"messages": "我叫 Bob"}, config_bob)
graph.invoke({"messages": "我叫 Alice"}, config_alice)

# Bob 的会话记得 Bob
graph.invoke({"messages": "我叫什么？"}, config_bob)
# → "Your name is Bob"

# Alice 的会话记得 Alice  
graph.invoke({"messages": "我叫什么？"}, config_alice)
# → "Your name is Alice"
```

**关键点**：
- `InMemorySaver` 存的是每个 `thread_id` 的完整状态快照
- 同一个 `thread_id` 内的消息会自然累积
- 不同 `thread_id` 之间完全隔离
- 生产环境换 `SqliteSaver` / `PostgresSaver` 即可持久化

---

## 4. 三种管理策略

上下文不会自己管理自己——你需要主动裁剪、删除或压缩。

### 4.1 Trim Messages（裁剪）

保留最近的消息，按 token 预算截断：

```python
from langchain_core.messages.utils import trim_messages, count_tokens_approximately

# 在 call_model 节点中裁剪
def call_model(state: MessagesState):
    messages = trim_messages(
        state["messages"],
        strategy="last",              # 保留最后 N 条
        token_counter=count_tokens_approximately,
        max_tokens=384,               # 最多 384 token
        start_on="human",             # 必须从 human 消息开始
        end_on=("human", "tool"),     # 必须止于 human 或 tool
        include_system=True,          # 始终保留 system 消息
    )
    response = model.invoke(messages)
    return {"messages": [response]}
```

**参数说明**：

| 参数 | 含义 |
|---|---|
| `strategy` | `"last"` 保留尾部 / `"first"` 保留头部 |
| `max_tokens` | token 预算上限 |
| `token_counter` | 计数函数，内置 `count_tokens_approximately` 或传 `tiktoken` |
| `start_on` | 结果必须以指定角色开头（防止对话断层） |
| `end_on` | 结果必须以指定角色结尾 |
| `include_system` | 是否始终包含 system 消息 |

### 4.2 Delete Messages（删除）

精确删除指定消息，或清空全部：

```python
from langchain_core.messages import RemoveMessage

# 删除指定消息
def delete_old_message(state: MessagesState):
    old_message = state["messages"][0]  # 最早的消息
    return {"messages": [RemoveMessage(id=old_message.id)]}

# 清空全部消息（仅保留最后 2 条）
def delete_all_but_recent(state: MessagesState):
    delete_messages = [
        RemoveMessage(id=m.id) for m in state["messages"][:-2]
    ]
    return {"messages": delete_messages}
```

`RemoveMessage` 是 LangGraph 的特殊修饰符——节点返回它时，系统会自动从状态中移除对应消息。

### 4.3 Summarize Messages（摘要压缩）

驱逐旧消息之前，先让 LLM 把它们压缩成一段摘要：

```python
class State(MessagesState):
    summary: str

def summarize_conversation(state: State):
    summary = state.get("summary", "")

    if summary:
        prompt = (
            f"This is a summary of conversation to date: {summary}\n\n"
            "Extend the summary by taking into account the new messages above:"
        )
    else:
        prompt = "Create a summary of the conversation above:"

    messages = state["messages"] + [HumanMessage(content=prompt)]
    response = model.invoke(messages)

    # 删除已摘要的消息（保留最后 2 条）
    delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-2]]
    return {"summary": response.content, "messages": delete_messages}

def call_model(state: State):
    summary = state.get("summary", "")
    if summary:
        system_message = SystemMessage(
            content=f"Summary of earlier conversation: {summary}"
        )
        messages = [system_message] + state["messages"]
    else:
        messages = state["messages"]
    response = model.invoke(messages)
    return {"messages": [response]}
```

**核心思路**：
1. 当前消息累积到一定量时触发摘要
2. LLM 把旧消息压缩成一段自然语言
3. 删除旧消息，保留摘要 + 最近消息
4. 后续对话以 system 消息注入摘要，让 LLM 知道"之前聊过什么"

---

## 5. 三种策略对比

| 策略 | 优点 | 缺点 | 适用场景 |
|---|---|---|---|
| **Trim** | 简单、无额外 LLM 调用 | 旧信息完全丢失 | 短任务、上下文不重要 |
| **Delete** | 精确控制、零开销 | 需要自己判断删什么 | 工具结果清理、中间态删除 |
| **Summarize** | 保留早期精华 | 多一次 LLM 调用、摘要可能失真 | 长对话、需要记住早期关键信息 |

---

## 6. Checkpointer 选型

| 实现 | 适用场景 |
|---|---|
| `InMemorySaver` | 开发 / 学习 / 测试 |
| `SqliteSaver` | 单机生产（需要持久化但不想搭数据库） |
| `PostgresSaver` | 多实例生产（需要并发读写） |

```python
# 开发
from langgraph.checkpoint.memory import InMemorySaver
checkpointer = InMemorySaver()

# 生产 — SQLite
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

# 生产 — PostgreSQL
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost:5432/db"
)
```

---

## 7. 最佳实践

| 关注点 | 做法 |
|---|---|
| **System 消息保护** | 裁剪时 `include_system=True`，保证规则不丢失 |
| **消息边界** | `start_on` / `end_on` 防止截断在 tool 调用中间 |
| **摘要触发时机** | 消息数 > 10 条或 token > 预算的 80% 时触发 |
| **生产持久化** | 用 `SqliteSaver` 起步，不够再升 `PostgresSaver` |
| **成本控制** | 摘要用便宜的模型（如 deepseek-chat），主力推理用强模型 |
| **token 计数** | 生产环境用 `tiktoken` 精确计数，粗估用 `count_tokens_approximately` |

---

## 8. 运行方式

```bash
cd python

# 单独跑短期记忆 demo
uv run python -m learning_py.langchain_framework.short_term_memory

# 通过统一入口跑
uv run python -m learning_py.langchain_framework.demo memory
```

---

## 9. 配套阅读

- [`agent-memory.md`](./agent-memory.md) — 本仓库的 Agent 记忆系统（短期 + 长期），含向量库实现
- [`langchain-framework-knowledge-base.md`](./langchain-framework-knowledge-base.md) — LangChain 学习总览
- [`ai-agent.md`](./ai-agent.md) — AI Agent 四大能力（感知 / 推理 / 决策 / 执行）
- [LangGraph 官方 Memory 指南](https://langchain-ai.github.io/langgraph/guides/memory/)
