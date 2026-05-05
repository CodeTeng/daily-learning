"""最小向量数据库：内存里维护 (id, vector, text, meta) 元组，提供 cosine top-k 检索。

为什么自己写而不是用 chroma / faiss / milvus？

- 教学目的：让你看清楚"向量库"在 100 行代码内可以多简单
- 零依赖：本仓库不引入任何额外二进制
- 真实工程请用专业方案；接口设计上保持和 chroma / pinecone 类似（add / query / delete）
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .embedding import Embedder, cosine_similarity


@dataclass
class VectorRecord:
    id: str
    vector: list[float]
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class SearchHit:
    record: VectorRecord
    score: float  # cosine 相似度，[-1, 1]，越大越相似


class InMemoryVectorStore:
    """最小向量库：增 / 查 / 删 / 列表。

    - 同 `id` 重复 add 会**覆盖**（upsert 语义）
    - query 返回按 score 降序排列的 top-k
    - 可选的 score_threshold 过滤掉相似度太低的结果
    """

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._records: dict[str, VectorRecord] = {}

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add(
        self,
        text: str,
        meta: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> str:
        rid = record_id or str(uuid.uuid4())
        vec = self.embedder.embed(text)
        self._records[rid] = VectorRecord(
            id=rid, vector=vec, text=text, meta=meta or {}
        )
        return rid

    def delete(self, record_id: str) -> bool:
        return self._records.pop(record_id, None) is not None

    def clear(self) -> None:
        self._records.clear()

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def query(
        self,
        text: str,
        top_k: int = 3,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        if not self._records:
            return []
        q = self.embedder.embed(text)
        hits = [
            SearchHit(record=r, score=cosine_similarity(q, r.vector))
            for r in self._records.values()
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        if score_threshold is not None:
            hits = [h for h in hits if h.score >= score_threshold]
        return hits[:top_k]

    def list_all(self) -> list[VectorRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)
