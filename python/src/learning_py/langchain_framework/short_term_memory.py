"""
LangChain / LangGraph Short-term Memory demos.

覆盖短记忆的三种管理策略 + LangGraph Checkpointer:
  - 策略 1: 滑窗裁剪（FIFO）
  - 策略 2: Token 预算裁剪（trim_messages）
  - 策略 3: 精确删除（RemoveMessage）
  - 策略 4: 对话摘要压缩（Summarization）
  - LangGraph: InMemorySaver + thread_id 隔离

运行方式:
    uv run python -m learning_py.langchain_framework.short_term_memory
    uv run python -m learning_py.langchain_framework.demo memory
"""

from __future__ import annotations

import sys
from collections import deque

# Windows 终端默认 GBK，LLM 返回可能含 emoji → 避免 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from learning_py.langchain_framework.config import create_chat_model


def _model(temp: float = 0.7) -> ChatOpenAI:
    return create_chat_model(temperature=temp)


# ═══════════════════════════════════════════════════════════════════
# 策略 1: 滑窗裁剪（Sliding Window / FIFO）
# ═══════════════════════════════════════════════════════════════════


class SlidingWindowMemory:
    """基于 deque 的定长消息窗口。

    system 消息始终保留在窗口外部，不被驱逐。
    """

    def __init__(self, max_messages: int = 6) -> None:
        self.max_messages = max_messages
        self._messages: deque = deque(maxlen=max_messages)

    def add_user(self, text: str) -> None:
        self._messages.append(HumanMessage(content=text))

    def add_ai(self, text: str) -> None:
        self._messages.append(AIMessage(content=text))

    def list(self) -> list:
        return list(self._messages)


def demo_window_memory() -> None:
    """演示 1: 定长滑窗 — 超出上限自动驱逐最早的消息。"""
    print("=" * 60)
    print("策略 1: 滑窗裁剪 (Sliding Window, max=6)")
    print("=" * 60)

    m = _model()
    mem = SlidingWindowMemory(max_messages=6)
    system = SystemMessage(content="记住用户的个人信息，回答时引用他们的名字和偏好。")

    questions = [
        "我叫张三，是一名后端开发。",
        "我喜欢用 Python 写 Web 服务。",
        "我平时用 VS Code 写代码。",
        "我叫什么名字？我的职业是什么？",
        "我用什么编辑器？喜欢什么语言？",
    ]

    for q in questions:
        mem.add_user(q)
        messages = [system] + mem.list()
        resp = m.invoke(messages)
        mem.add_ai(resp.content)
        print(f"\n[User]  {q}")
        print(f"[AI]   {resp.content}")

    print(f"\n当前窗口内消息数: {len(mem.list())} (max={mem.max_messages})")


# ═══════════════════════════════════════════════════════════════════
# 策略 2: Token 预算裁剪（trim_messages）
# ═══════════════════════════════════════════════════════════════════


def demo_trim_messages() -> None:
    """演示 2: 基于 token 预算裁剪 — 超出 max_tokens 就裁掉最早的消息。"""
    print("\n" + "=" * 60)
    print("策略 2: Token 预算裁剪 (trim_messages, max_tokens=256)")
    print("=" * 60)

    m = _model()
    messages = [
        SystemMessage(content="你是一个简洁的助手。"),
        HumanMessage(content="我叫王五，住在北京。"),
        AIMessage(content="你好王五！住在北京是个不错的地方。"),
        HumanMessage(content="我喜欢骑行和爬山。"),
        AIMessage(content="骑行和爬山都是很好的户外运动！"),
        HumanMessage(content="我最近在学习 Rust 语言。"),
        AIMessage(content="Rust 是一门很棒的底层语言，内存安全做得很好。"),
        HumanMessage(content="推荐一些适合我的周末活动。"),
    ]

    print(f"原始消息数: {len(messages)}")
    estimated = count_tokens_approximately(messages)
    print(f"预估 token 数: {estimated}")

    # 按 token 预算裁剪，始终保留 system + 以 human 开头和结尾
    trimmed = trim_messages(
        messages,
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=256,
        start_on="human",
        end_on=("human", "ai"),
        include_system=True,
    )

    print(f"裁剪后消息数: {len(trimmed)}")
    print(f"被裁掉的消息数: {len(messages) - len(trimmed)}")
    print()

    for msg in trimmed:
        role = type(msg).__name__.replace("Message", "").upper()
        content = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        print(f"[{role}] {content}")

    print("\n--- 用裁剪后的上下文调用 LLM ---")
    resp = m.invoke(trimmed)
    print(f"[AI]   {resp.content}")


# ═══════════════════════════════════════════════════════════════════
# 策略 3: 精确删除（RemoveMessage）
# ═══════════════════════════════════════════════════════════════════


def demo_remove_messages() -> None:
    """演示 3: 用 RemoveMessage 精确删除指定消息。

    LangGraph 节点返回 RemoveMessage 时，系统会自动从状态中移除对应消息。
    这里演示在手动管理的消息列表中模拟这一过程。
    """
    print("\n" + "=" * 60)
    print("策略 3: 精确删除 (RemoveMessage)")
    print("=" * 60)

    m = _model()

    messages: list = [
        SystemMessage(content="你是一个简洁的助手。"),
        HumanMessage(content="我叫李四。"),
        AIMessage(content="你好李四！"),
        HumanMessage(content="天气真好。"),
        AIMessage(content="是啊，适合出门走走。"),
        HumanMessage(content="Python 中如何处理 CSV 文件？"),
        AIMessage(content="用 csv 模块或 pandas 都可以。"),
        HumanMessage(content="我叫什么名字？"),
    ]

    print(f"原始消息数: {len(messages)}")
    print("原始对话:")
    for msg in messages:
        role = type(msg).__name__.replace("Message", "").upper()
        content = msg.content[:60] + "..." if len(msg.content) > 60 else msg.content
        print(f"  [{role}] {content}")

    # 模拟：删除关于天气的寒暄（索引 3 和 4）
    # 注意：直接构造的消息 id 为 None；在 LangGraph 中消息会由 state 管道
    # 分配唯一 id，届时可用 RemoveMessage(id=m.id) 精确删除。
    remove_indices = {3, 4}
    kept = [msg for i, msg in enumerate(messages) if i not in remove_indices]

    print(f"\n删除寒暄消息后: {len(kept)} 条 (原 {len(messages)} 条)")
    for msg in kept:
        role = type(msg).__name__.replace("Message", "").upper()
        print(f"  [{role}] {msg.content}")

    print("\n--- 用精简后的上下文调用 LLM ---")
    resp = m.invoke(kept)
    print(f"[AI]   {resp.content}")
    print(
        "\n注: 在 LangGraph 节点中，返回 [RemoveMessage(id=m.id)] "
        "即可让系统自动从状态中移除该消息。"
    )


# ═══════════════════════════════════════════════════════════════════
# 策略 4: 对话摘要压缩（Summarization）
# ═══════════════════════════════════════════════════════════════════


def demo_summarization() -> None:
    """演示 4: 摘要压缩 — 让 LLM 把旧消息压缩成一段摘要，保留精华。

    核心流程:
      1. 累积足够的对话轮次后触发摘要
      2. LLM 将旧消息压缩为自然语言摘要
      3. 删除旧消息，以 system 消息注入摘要
      4. 后续对话基于「摘要 + 最近消息」进行
    """
    print("\n" + "=" * 60)
    print("策略 4: 对话摘要压缩 (Summarization)")
    print("=" * 60)

    m = _model()
    summary_model = _model(temp=0.3)  # 摘要用低温度，更稳定

    system = SystemMessage(content="你是一个友好的助手，用中文回答，尽量简短。")
    messages: list = [
        system,
        HumanMessage(content="我叫赵六，在上海做产品经理。"),
        AIMessage(content="你好赵六！产品经理是很有意思的工作。"),
        HumanMessage(content="我们最近在做一个 AI 客服项目，遇到了一些挑战。"),
        AIMessage(content="AI 客服确实有不少挑战。请说说具体是什么问题？"),
        HumanMessage(content="主要是对话质量不稳定，有时候会胡说八道。"),
        AIMessage(content="这确实是 LLM 的常见问题。可以从 prompt 工程、RAG 检索增强、和 fine-tuning 三个方向入手。"),
        HumanMessage(content="我们还发现多轮对话的上下文管理也很麻烦。"),
        AIMessage(content="上下文管理确实是关键。短期记忆的裁剪和摘要策略能帮上忙。"),
    ]

    print("--- 触发摘要前 ---")
    print(f"总消息数: {len(messages)}")
    estimated = count_tokens_approximately(messages)
    print(f"预估 token: {estimated}")

    # 取要摘要的部分（前 6 条：system + 3 轮对话）和保留的部分（最后 4 条）
    to_summarize = messages[1:7]  # 跳过 system，取前 3 轮
    to_keep = messages[7:]  # 保留最近 1 轮

    print(f"\n摘要对象 ({len(to_summarize)} 条):")
    for msg in to_summarize:
        role = type(msg).__name__.replace("Message", "").upper()
        print(f"  [{role}] {msg.content}")

    # 让 LLM 生成摘要
    summary_prompt = HumanMessage(
        content=(
            "请将以上对话压缩为一段简短的中文摘要，包含用户的关键信息（姓名、职业、"
            "工作内容和遇到的挑战）。用第三人称叙述，控制在 100 字以内。"
        )
    )
    summary_resp = summary_model.invoke(to_summarize + [summary_prompt])
    summary_text = summary_resp.content

    print(f"\n生成的摘要:\n  \"{summary_text}\"")

    # 用摘要替换旧消息
    summary_system = SystemMessage(
        content=f"[历史对话摘要] {summary_text}\n\n请基于以上摘要继续对话。"
    )
    compressed = [system, summary_system] + to_keep

    print(f"\n压缩后消息数: {len(compressed)} (原 {len(messages)})")
    print("压缩后的上下文结构:")
    for msg in compressed:
        role = type(msg).__name__.replace("Message", "").upper()
        content = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        print(f"  [{role}] {content}")

    # 用压缩后的上下文继续对话
    print("\n--- 基于压缩上下文继续对话 ---")
    follow_up = HumanMessage(content="针对上下文管理，你有什么具体建议？")
    compressed.append(follow_up)
    resp = m.invoke(compressed)
    print(f"[User]  {follow_up.content}")
    print(f"[AI]    {resp.content}")


# ═══════════════════════════════════════════════════════════════════
# LangGraph: Checkpointer + thread_id 隔离
# ═══════════════════════════════════════════════════════════════════


def _build_checkpointer_graph():
    """构建带 checkpointer 的最简图：单节点，直接调模型。"""
    m = _model()

    def call_model(state: MessagesState):
        # 裁剪到 512 token 以内
        messages = trim_messages(
            state["messages"],
            strategy="last",
            token_counter=count_tokens_approximately,
            max_tokens=512,
            start_on="human",
            include_system=True,
        )
        return {"messages": [m.invoke(messages)]}

    builder = StateGraph(MessagesState)
    builder.add_node(call_model)
    builder.add_edge(START, "call_model")
    return builder.compile(checkpointer=InMemorySaver())


def demo_langgraph_checkpointer() -> None:
    """演示 5: LangGraph InMemorySaver + thread_id 会话隔离。

    不同 thread_id 的对话完全隔离，就像两个"平行宇宙"。
    """
    print("\n" + "=" * 60)
    print("LangGraph: Checkpointer + thread_id 会话隔离")
    print("=" * 60)

    graph = _build_checkpointer_graph()

    # 两个独立会话
    config_a = {"configurable": {"thread_id": "session-alice"}}
    config_b = {"configurable": {"thread_id": "session-bob"}}

    # Alice 的会话
    print("\n--- Alice 的会话 (thread_id=session-alice) ---")
    resp = graph.invoke(
        {"messages": [HumanMessage(content="我叫 Alice，我是一名设计师。")]},
        config_a,
    )
    print(f"[Alice]  我叫 Alice，我是一名设计师。")
    print(f"[AI]     {resp['messages'][-1].content}")

    # Bob 的会话
    print("\n--- Bob 的会话 (thread_id=session-bob) ---")
    resp = graph.invoke(
        {"messages": [HumanMessage(content="我叫 Bob，我是后端工程师。")]},
        config_b,
    )
    print(f"[Bob]    我叫 Bob，我是后端工程师。")
    print(f"[AI]     {resp['messages'][-1].content}")

    # Alice 继续 — 应该记得自己的名字
    print("\n--- Alice 继续 (同一个 thread_id) ---")
    resp = graph.invoke(
        {"messages": [HumanMessage(content="我叫什么名字？我的职业是什么？")]},
        config_a,
    )
    print(f"[Alice]  我叫什么名字？我的职业是什么？")
    print(f"[AI]     {resp['messages'][-1].content}")

    # Bob 继续 — 也应该记得自己的名字
    print("\n--- Bob 继续 (同一个 thread_id) ---")
    resp = graph.invoke(
        {"messages": [HumanMessage(content="我叫什么名字？我的职业是什么？")]},
        config_b,
    )
    print(f"[Bob]    我叫什么名字？我的职业是什么？")
    print(f"[AI]     {resp['messages'][-1].content}")

    print("\n注意: Alice 的会话不知道 Bob；Bob 的会话也不知道 Alice。")


# ═══════════════════════════════════════════════════════════════════
# 综合演示
# ═══════════════════════════════════════════════════════════════════


def demo_all_memory() -> None:
    """按顺序跑完所有短记忆策略演示。"""
    demo_window_memory()
    demo_trim_messages()
    demo_remove_messages()
    demo_summarization()
    demo_langgraph_checkpointer()

    print("\n" + "=" * 60)
    print("全部短期记忆策略演示完成！")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "all":
        demo_all_memory()
    else:
        # 默认：逐个运行
        demo_window_memory()
        demo_trim_messages()
        demo_remove_messages()
        demo_summarization()
        demo_langgraph_checkpointer()
