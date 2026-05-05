"""记忆系统 demo。

包含两个部分：

1. `demo_core()`：**零依赖**，演示短期记忆压缩、向量库检索、长期记忆 TTL；
   不需要 LLM，跑得起来，跑得稳。

2. `demo_with_llm()`：用真实 LLM 跑一段**带记忆的多轮对话**，
   能看到 Agent 跨轮回忆"用户的偏好"。需要 `python/.env`。

运行：
    uv run python -m learning_py.agent.memory.demo            # 跑全部
    uv run python -m learning_py.agent.memory.demo core       # 仅核心
    uv run python -m learning_py.agent.memory.demo llm        # 仅 LLM 对话
"""

from __future__ import annotations

import sys
import time

from .embedding import HashEmbedder
from .long_term import LongTermMemory
from .manager import MemoryManager
from .short_term import ShortTermMemory


def _section(title: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{title}\n{line}")


# --------------------------------------------------------------------------- #
# 1. 核心逻辑（零依赖）
# --------------------------------------------------------------------------- #

def demo_short_term() -> None:
    _section("1. 短期记忆：FIFO 驱逐 + 摘要压缩")

    def fake_summarizer(msgs):
        # 演示用：把被驱逐的内容压成一行
        items = [f"{m.role}:{m.content[:8]}…" for m in msgs]
        return "之前讨论了 " + "、".join(items)

    stm = ShortTermMemory(
        max_messages=4,
        token_budget=10_000,  # 把 token 限制放很高，专测 max_messages
        summarizer=fake_summarizer,
    )
    stm.add_system("你是技术助手")
    for i in range(1, 7):
        stm.add_user(f"问题 #{i}")
        stm.add_assistant(f"答案 #{i}")

    print(f"短期消息条数：{stm.message_count()}（上限 4）")
    print(f"当前摘要：{stm.summary or '（无）'}")
    print("当前消息：")
    for m in stm.as_messages():
        print(f"  - [{m['role']}] {m['content'][:40]}")


def demo_vector_recall() -> None:
    _section("2. 长期记忆：向量库 cosine 检索")

    ltm = LongTermMemory(embedder=HashEmbedder(dim=512), capacity=100)
    ltm.remember("用户偏好简洁回答，不要废话")
    ltm.remember("用户使用 macOS 与 Cursor 编辑器")
    ltm.remember("用户主要用 Python 后端开发")
    ltm.remember("我们之前讨论过 GIL 的话题")

    queries = ["他用什么编辑器？", "用户喜欢长文还是短文？", "讨论过哪些 Python 内部机制？"]
    for q in queries:
        hits = ltm.recall(q, top_k=2)
        print(f"\n查询：{q}")
        for hit in hits:
            print(f"  ★ {hit.score:+.3f}  {hit.record.text}")


def demo_ttl() -> None:
    _section("3. 长期记忆：TTL 过期")

    ltm = LongTermMemory(embedder=HashEmbedder(dim=64), ttl_seconds=0.05)
    ltm.remember("会过期的事实")
    print(f"立即查询：{len(ltm.recall('过期'))} 条")

    time.sleep(0.06)
    print(f"睡 60ms 后查询：{len(ltm.recall('过期'))} 条（应为 0）")


def demo_manager_build_context() -> None:
    _section("4. MemoryManager：自动召回 + 拼接 messages")

    mm = MemoryManager()
    mm.short_term.add_system("你是技术助手，记得用户的偏好。")
    mm.remember_fact("用户使用 macOS 与 Cursor 编辑器")
    mm.remember_fact("用户偏好简洁回答")

    # 第一轮
    mm.observe(user="帮我推荐个 Python 学习路线", assistant="可以从基础到进阶分 5 步…")

    # 第二轮：用户提到"编辑器"——长期记忆应被自动召回
    user2 = "我用什么编辑器来着？"
    ctx = mm.build_context(user_input=user2)
    print(f"用户问：{user2}\n")
    print("发给 LLM 的 messages：")
    for m in ctx:
        print(f"  - [{m['role']}] {m['content'][:60]}")


def demo_core() -> None:
    demo_short_term()
    demo_vector_recall()
    demo_ttl()
    demo_manager_build_context()


# --------------------------------------------------------------------------- #
# 2. 真实 LLM：带记忆的多轮对话
# --------------------------------------------------------------------------- #

def demo_with_llm() -> None:
    _section("5. 真实 LLM：带记忆的多轮对话")

    try:
        from learning_py.agent.llm_client import OpenAICompatLLM
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] 无法导入 OpenAICompatLLM：{e}")
        return

    # 初始化 LLM；同时让短期记忆配上 LLM 摘要器
    llm = OpenAICompatLLM(name="memory-demo", temperature=0.2, max_tokens=300)

    def llm_summarizer(msgs):
        joined = "\n".join(f"{m.role}: {m.content}" for m in msgs)
        prompt = (
            "请把下面这段对话压缩成不超过 50 字的中文要点，只保留关键事实：\n\n" + joined
        )
        try:
            return llm.complete(prompt)
        except Exception as e:  # noqa: BLE001
            return f"（摘要失败：{e}）"

    mm = MemoryManager(
        short_term=ShortTermMemory(max_messages=6, token_budget=1500, summarizer=llm_summarizer),
    )
    mm.short_term.add_system(
        "你是简洁的技术助手。如果上下文里出现 [长期记忆召回]，请把它当作既有事实使用。"
    )

    # 预设几条长期事实（模拟用户在过去会话里告诉过 Agent 的事）
    mm.remember_fact("用户的名字叫小李")
    mm.remember_fact("用户使用 macOS 与 Cursor 编辑器")
    mm.remember_fact("用户偏好极简回答，每次不超过 2 句话")

    turns = [
        "帮我推荐一个 Python Agent 框架",
        "我用什么编辑器来着？",
        "我叫什么名字？",
    ]

    for i, user_msg in enumerate(turns, 1):
        print(f"\n--- 第 {i} 轮 ---")
        print(f"USER: {user_msg}")
        ctx = mm.build_context(user_input=user_msg)
        ctx.append({"role": "user", "content": user_msg})

        # 直接调底层 client，绕开 OpenAICompatLLM.complete（它只接受单 prompt）
        resp = llm._client.chat.completions.create(  # noqa: SLF001  demo 内部直连
            model=llm.model,  # type: ignore[arg-type]
            messages=ctx,  # type: ignore[arg-type]
            temperature=llm.temperature,
            max_tokens=llm.max_tokens,
        )
        answer = (resp.choices[0].message.content or "").strip()
        print(f"ASSISTANT: {answer}")

        mm.observe(user=user_msg, assistant=answer)

    print("\n短期记忆当前摘要：")
    print("  " + (mm.short_term.summary or "（尚未触发压缩）"))


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

DEMOS = {
    "core": demo_core,
    "llm": demo_with_llm,
}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    debug = "--debug" in sys.argv

    if not args:
        targets = list(DEMOS.values())
    else:
        targets = []
        for name in args:
            if name not in DEMOS:
                print(f"未知 demo：{name}，可选：{list(DEMOS)}")
                sys.exit(2)
            targets.append(DEMOS[name])

    for fn in targets:
        try:
            fn()
        except Exception as e:  # noqa: BLE001  顶层 demo
            print(f"\n[ERROR] {fn.__name__} 失败：{type(e).__name__}: {e}")
            if debug:
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    main()
