"""Embedder 抽象 + 两个实现。

`HashEmbedder`（默认）：
  - 零依赖、确定性、跑得起来；用 hash 散列把 token 投到固定维度 + 简单平滑
  - 只用于教学和单测，**不要用于生产**——它没有真正的语义相似度
  - 但能保证"相同字面/相近字面"的文本距离更近，足以演示向量库工作原理

`OpenAIEmbedder`（可选）：
  - 走 OpenAI 协议（DeepSeek/月之暗面/智谱等也支持），从 .env 读配置
  - 模型名走 `LLM_EMBEDDING_MODEL`，没配则尝试 `text-embedding-3-small`
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"维度不一致：{len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- #
# HashEmbedder：零依赖、教学用
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[A-Za-z]+|[\u4e00-\u9fff]")


def _tokenize(text: str) -> list[str]:
    """简易分词：英文按词、中文按字。"""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class HashEmbedder:
    """用 feature hashing 把文本投到 dim 维空间。

    原理：
    - 每个 token 用 md5 hash 落到 [0, dim) 上的一个或多个桶，桶内累加 1
    - 最后对向量做 L2 归一化

    这是 NLP 早期 "hashing trick" 的最简版本，不需要训练，
    对**字面相近**的文本能给出有意义的相似度。
    """

    dim: int = 256

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _tokenize(text)
        if not tokens:
            return vec
        for tok in tokens:
            # 用两个不同 salt 投两次，缓解碰撞
            for salt in ("a", "b"):
                h = hashlib.md5(f"{salt}:{tok}".encode()).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                # 第 5 字节决定符号，避免所有维度都是正
                sign = 1.0 if h[4] & 1 else -1.0
                vec[idx] += sign
        # L2 归一化
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]


# --------------------------------------------------------------------------- #
# OpenAIEmbedder：可选，需要 .env 配置
# --------------------------------------------------------------------------- #

@dataclass
class OpenAIEmbedder:
    """走 OpenAI Embeddings 协议的真实 embedder。

    配置项（与 `agent.llm_client` 共用 `.env`）：
        LLM_BASE_URL          # 必填
        LLM_API_KEY           # 必填
        LLM_EMBEDDING_MODEL   # 可选，默认 "text-embedding-3-small"

    注意：**DeepSeek 暂不提供 embedding 接口**，需切到提供 embedding 的服务
    （OpenAI / 智谱 / 自建 BGE 网关等），把 LLM_BASE_URL 改成对应地址即可。
    """

    model: str | None = None
    dim: int = 1536  # 真实维度由模型决定，这里给个常见默认值

    def __post_init__(self) -> None:
        from openai import OpenAI

        self.model = self.model or os.environ.get(
            "LLM_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        base_url = os.environ.get("LLM_BASE_URL")
        api_key = os.environ.get("LLM_API_KEY")
        if not (base_url and api_key):
            raise RuntimeError(
                "OpenAIEmbedder 需要 LLM_BASE_URL 和 LLM_API_KEY，"
                "请在 python/.env 中配置。"
            )
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def embed(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(model=self.model, input=text)  # type: ignore[arg-type]
        vec = list(resp.data[0].embedding)
        # 真实维度以模型为准，更新 dim 让后续校验通过
        self.dim = len(vec)
        return vec
