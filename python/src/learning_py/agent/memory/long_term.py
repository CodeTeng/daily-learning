"""长期记忆：在向量库之上加 TTL、容量驱逐、按 meta 过滤。

什么时候用长期记忆？

- 跨会话的用户偏好（"用户喜欢简洁回答"、"用户用 macOS"）
- 历史经验（上次 search 这个关键词得到了 X）
- 知识库（公司文档、商品资料）

设计上把"读 / 写"两面分开：
- `remember(text, meta)`：写入一条
- `recall(query, top_k)`：检索最相关的若干条
- `forget(record_id)` / `prune(...)`：清理
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .embedding import Embedder
from .vector_store import InMemoryVectorStore, SearchHit


@dataclass
class LongTermMemory:
    embedder: Embedder
    # 容量上限：超出就驱逐最旧的
    capacity: int = 1000
    # TTL（秒）；None 表示不过期
    ttl_seconds: float | None = None

    def __post_init__(self) -> None:
        self._store = InMemoryVectorStore(self.embedder)

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def remember(
        self,
        text: str,
        meta: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> str:
        rid = self._store.add(text, meta=meta, record_id=record_id)
        self._evict_if_needed()
        return rid

    def forget(self, record_id: str) -> bool:
        return self._store.delete(record_id)

    def clear(self) -> None:
        self._store.clear()

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def recall(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        # 检索前先清掉过期记录（lazy expiration）
        self._prune_expired()
        return self._store.query(query, top_k=top_k, score_threshold=score_threshold)

    def __len__(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------ #
    # 清理
    # ------------------------------------------------------------------ #
    def _prune_expired(self) -> int:
        if self.ttl_seconds is None:
            return 0
        now = time.time()
        cutoff = now - self.ttl_seconds
        expired = [r.id for r in self._store.list_all() if r.created_at < cutoff]
        for rid in expired:
            self._store.delete(rid)
        return len(expired)

    def _evict_if_needed(self) -> None:
        n_to_drop = len(self._store) - self.capacity
        if n_to_drop <= 0:
            return
        # 按 created_at 升序，先丢最早的
        records = sorted(self._store.list_all(), key=lambda r: r.created_at)
        for r in records[:n_to_drop]:
            self._store.delete(r.id)
