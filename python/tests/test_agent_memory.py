"""Agent 记忆系统的纯逻辑单测。

全部不依赖 LLM 或网络，覆盖：
- 短期记忆：滑窗 / token 预算 / 摘要压缩 / system 保留
- HashEmbedder：基本属性、相同输入相同输出、维度
- InMemoryVectorStore：增删查、top_k、阈值过滤
- LongTermMemory：容量驱逐、TTL 过期
- MemoryManager：build_context 自动召回并注入到 system 后
"""

from __future__ import annotations

import time

from learning_py.agent.memory.embedding import HashEmbedder, cosine_similarity
from learning_py.agent.memory.long_term import LongTermMemory
from learning_py.agent.memory.manager import MemoryManager
from learning_py.agent.memory.short_term import ShortTermMemory, estimate_tokens
from learning_py.agent.memory.vector_store import InMemoryVectorStore


# --------------------------------------------------------------------------- #
# Token 估算
# --------------------------------------------------------------------------- #

def test_estimate_tokens_handles_empty_and_chinese() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") > 0
    # 中文每字 ≈ 1.5 token，10 字应该 >= 15
    assert estimate_tokens("中文测试一二三四五六七") >= 15


# --------------------------------------------------------------------------- #
# 短期记忆
# --------------------------------------------------------------------------- #

def test_short_term_keeps_system_message() -> None:
    stm = ShortTermMemory(max_messages=2)
    stm.add_system("你是助手")
    for i in range(5):
        stm.add_user(f"q{i}")
        stm.add_assistant(f"a{i}")

    msgs = stm.as_messages()
    # system 必须在最前面、必须保留
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "你是助手"
    # 非系统消息不超过 max_messages
    non_system = [m for m in msgs if m["role"] != "system"]
    assert len(non_system) <= 2


def test_short_term_summarizer_compresses_evicted_history() -> None:
    captured: list[int] = []

    def summarizer(msgs):
        captured.append(len(msgs))
        return f"summary-of-{len(msgs)}"

    stm = ShortTermMemory(max_messages=2, summarizer=summarizer)
    stm.add_system("sys")
    for i in range(4):
        stm.add_user(f"q{i}")
        stm.add_assistant(f"a{i}")

    # 必然触发了压缩
    assert captured, "summarizer 应该被调用过"
    # 摘要被注入到 system 之后
    msgs = stm.as_messages()
    assert msgs[0]["role"] == "system"
    assert "[历史摘要]" in msgs[1]["content"]


def test_short_term_token_budget_triggers_eviction() -> None:
    stm = ShortTermMemory(max_messages=100, token_budget=20)
    stm.add_system("s")
    stm.add_user("一段非常长的中文文本测试用例" * 5)
    stm.add_assistant("另一段也很长的中文回复内容" * 5)
    stm.add_user("新消息")
    # token 预算很小，前面长消息应被驱逐
    assert stm.total_tokens() <= 20 or stm.message_count() <= 2


def test_short_term_clear_keeps_system() -> None:
    stm = ShortTermMemory()
    stm.add_system("sys")
    stm.add_user("hi")
    stm.clear()
    assert stm.as_messages() == [{"role": "system", "content": "sys"}]


# --------------------------------------------------------------------------- #
# Embedding
# --------------------------------------------------------------------------- #

def test_hash_embedder_deterministic() -> None:
    e = HashEmbedder(dim=128)
    a = e.embed("hello world")
    b = e.embed("hello world")
    assert a == b
    assert len(a) == 128


def test_hash_embedder_similar_text_higher_similarity() -> None:
    e = HashEmbedder(dim=512)
    a = e.embed("用户使用 macOS 与 Cursor 编辑器")
    b = e.embed("他用什么编辑器？Cursor")
    c = e.embed("天气真好今天阳光明媚")
    sim_ab = cosine_similarity(a, b)
    sim_ac = cosine_similarity(a, c)
    # 字面相关的应该比无关的更相似
    assert sim_ab > sim_ac


def test_cosine_similarity_zero_vector_is_zero() -> None:
    assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# --------------------------------------------------------------------------- #
# 向量库
# --------------------------------------------------------------------------- #

def test_vector_store_add_query_top_k() -> None:
    store = InMemoryVectorStore(HashEmbedder(dim=256))
    store.add("Python 是一种解释型语言")
    store.add("Go 是一种编译型语言")
    store.add("今晚去吃火锅")

    hits = store.query("Python", top_k=2)
    assert len(hits) == 2
    # 第一条命中"Python"必须排在最前
    assert "Python" in hits[0].record.text


def test_vector_store_threshold_filters_irrelevant() -> None:
    store = InMemoryVectorStore(HashEmbedder(dim=256))
    rid = store.add("用户使用 macOS 与 Cursor 编辑器")
    store.add("天气真好")
    # HashEmbedder 是字面级相似，阈值不能设太严
    hits = store.query("macOS Cursor 编辑器", top_k=5, score_threshold=0.1)
    assert any(h.record.id == rid for h in hits)
    # 同时阈值确实能过滤掉无关结果
    hits_strict = store.query("完全无关的查询内容", top_k=5, score_threshold=0.9)
    assert hits_strict == []


def test_vector_store_delete() -> None:
    store = InMemoryVectorStore(HashEmbedder(dim=64))
    rid = store.add("hello")
    assert store.delete(rid) is True
    assert store.delete(rid) is False
    assert len(store) == 0


# --------------------------------------------------------------------------- #
# 长期记忆
# --------------------------------------------------------------------------- #

def test_long_term_capacity_evicts_oldest() -> None:
    ltm = LongTermMemory(embedder=HashEmbedder(dim=64), capacity=2)
    ltm.remember("第一条")
    ltm.remember("第二条")
    ltm.remember("第三条")  # 触发驱逐
    assert len(ltm) == 2


def test_long_term_ttl_expires() -> None:
    ltm = LongTermMemory(embedder=HashEmbedder(dim=64), ttl_seconds=0.02)
    ltm.remember("速朽事实")
    assert len(ltm.recall("速朽", top_k=1)) == 1
    time.sleep(0.03)
    # 检索时 lazy expire
    assert len(ltm.recall("速朽", top_k=1)) == 0


# --------------------------------------------------------------------------- #
# MemoryManager
# --------------------------------------------------------------------------- #

def test_manager_build_context_injects_recall_after_system() -> None:
    mm = MemoryManager()
    mm.short_term.add_system("助手人格")
    mm.remember_fact("用户使用 Cursor 编辑器")
    mm.remember_fact("用户偏好简洁回答")

    ctx = mm.build_context(user_input="我用什么编辑器")

    # 第一条必须是 system，第二条应该是召回块（也是 system）
    assert ctx[0]["role"] == "system"
    assert ctx[0]["content"] == "助手人格"
    assert ctx[1]["role"] == "system"
    assert "[长期记忆召回]" in ctx[1]["content"]
    assert "Cursor" in ctx[1]["content"]


def test_manager_observe_appends_to_short_term() -> None:
    mm = MemoryManager()
    mm.observe(user="hi", assistant="hello")
    msgs = mm.short_term.as_messages()
    roles = [m["role"] for m in msgs]
    assert "user" in roles and "assistant" in roles


def test_manager_recall_threshold_filters_noise() -> None:
    mm = MemoryManager(recall_threshold=0.99)  # 几乎不可能命中
    mm.remember_fact("用户使用 Cursor 编辑器")
    ctx = mm.build_context(user_input="完全无关的查询")
    # 召回块应该不存在（或为空）
    assert all("[长期记忆召回]" not in m["content"] for m in ctx)
