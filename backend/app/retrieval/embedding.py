"""V3 阶段 4B：真实本地 Dense Embedding Provider。

使用 BAAI/bge-small-zh-v1.5 通过 sentence-transformers 加载。
CPU 推理，L2 normalize，passage 不加 instruction，query 添加检索 instruction。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np


# 模型常量
MODEL_REPO_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

# 默认缓存目录：仓库根 backend/data/model_cache
_DEFAULT_CACHE = (
    Path(__file__).resolve().parents[2] / "data" / "model_cache"
)


class EmbeddingError(Exception):
    """Embedding 加载或推理失败。"""


class FakeEmbeddingProvider:
    """确定性 fake provider，仅用于单元测试。

    从固定种子生成归一化向量，不对真实模型做任何推理。
    """

    def __init__(self, dimension: int = 512, seed: int = 42):
        self._dim = dimension
        self._rng = np.random.default_rng(seed)
        self._query_instruction = QUERY_INSTRUCTION

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._dim), dtype=np.float32)
        vecs = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, text in enumerate(texts):
            h = hashlib.sha256(text.encode("utf-8")).digest()
            # 用 hash 种子确定性生成向量
            local_rng = np.random.default_rng(int.from_bytes(h[:4], "big"))
            v = local_rng.normal(0, 1, self._dim).astype(np.float32)
            norm = np.linalg.norm(v)
            if norm > 0:
                v = v / norm
            vecs[i] = v
        return vecs

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        # fake provider: query 编码与 passage 相同（这不对应真实行为，仅用于测试）
        return self.encode_passages(texts)

    def _ensure_loaded(self) -> None:
        """兼容 LocalEmbeddingProvider 接口（无需加载真实模型）。"""

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": "fake",
            "model_repo_id": "fake/test",
            "model_revision": "fake",
            "dimension": self._dim,
            "normalize_embeddings": True,
            "query_instruction": self._query_instruction,
            "device": "cpu",
        }


class LocalEmbeddingProvider:
    """真实本地 Embedding provider。

    使用 sentence-transformers 加载 BGE 模型。
    """

    def __init__(
        self,
        model_repo_id: str = MODEL_REPO_ID,
        model_revision: str = MODEL_REVISION,
        query_instruction: str = QUERY_INSTRUCTION,
        cache_dir: str | None = None,
        batch_size: int = 8,
    ):
        self._repo_id = model_repo_id
        self._revision = model_revision
        self._query_instruction = query_instruction
        self._batch_size = batch_size
        # 未传 cache_dir 时使用默认缓存目录，确保始终有明确路径
        self._cache_dir = cache_dir if cache_dir is not None else str(_DEFAULT_CACHE)

        # 延迟加载
        self._model: Any = None
        self._dimension: int | None = None
        self._loaded = False

    # -- 公开接口 --

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        """编码 passage（不加 instruction）。"""
        return self._encode(texts, instruction="")

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        """编码 query（加 instruction）。"""
        return self._encode(texts, instruction=self._query_instruction)

    def metadata(self) -> dict[str, Any]:
        self._ensure_loaded()
        return {
            "provider": "sentence-transformers",
            "model_repo_id": self._repo_id,
            "model_revision": self._revision,
            "dimension": self._dimension,
            "normalize_embeddings": True,
            "query_instruction": self._query_instruction,
            "batch_size": self._batch_size,
            "device": "cpu",
        }

    # -- 内部实现 --

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load_model()

    def _load_model(self) -> None:
        """加载模型并验证维度。"""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingError(
                "sentence-transformers 未安装。请执行: pip install sentence-transformers"
            ) from e

        self._model = SentenceTransformer(
            self._repo_id,
            revision=self._revision,
            device="cpu",
            cache_folder=self._cache_dir,
        )
        # 获取实际维度
        self._dimension = self._model.get_sentence_embedding_dimension()
        if self._dimension is None:
            raise EmbeddingError("无法从模型获取 embedding 维度")
        self._loaded = True

    def _encode(self, texts: list[str], instruction: str) -> np.ndarray:
        """统一编码流程。

        - 空输入 → 空 ndarray
        - 对每个 text 添加 instruction（如有）
        - batch encode
        - L2 normalize（每个向量独立归一化到单位长度）
        - 验证无 NaN/Inf
        """
        if not texts:
            return np.empty((0, self._dimension or 0), dtype=np.float32)

        self._ensure_loaded()

        # 添加 instruction
        if instruction:
            encoded_texts = [instruction + t for t in texts]
        else:
            encoded_texts = list(texts)

        # batch 编码
        embeddings = self._model.encode(
            encoded_texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # sentence-transformers 内置 L2 normalize
        )

        # 确保 float32
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype(np.float32)

        # 验证
        if np.isnan(embeddings).any():
            raise EmbeddingError("编码结果包含 NaN")
        if np.isinf(embeddings).any():
            raise EmbeddingError("编码结果包含 Inf")

        return embeddings


def load_provider(
    model_cache_dir: str | None = None,
) -> LocalEmbeddingProvider:
    """创建并加载真实 LocalEmbeddingProvider。"""
    provider = LocalEmbeddingProvider(cache_dir=model_cache_dir)
    provider._ensure_loaded()
    return provider
