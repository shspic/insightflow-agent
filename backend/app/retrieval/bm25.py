"""共享 Okapi BM25 检索——支持 dict chunk 和 CorpusChunk 两种输入。

提供：
    BM25Scorer: 可预计算并复用的 BM25 打分器
    bm25_scorer: 便捷函数，等价于临时创建 BM25Scorer 并调用 score()
"""

from __future__ import annotations

import math
from collections import Counter
from statistics import mean
from typing import Any

from app.retrieval.tokenizer import tokenize


class BM25Scorer:
    """Okapi BM25 打分器。

    预计算文档统计信息，可对多条 query 复用。
    支持两种 corpus 格式：
    - dict corpus: [{"chunk_id": ..., "text": ..., ...}, ...]
    - CorpusChunk list: [CorpusChunk(...), ...]
    """

    def __init__(
        self,
        corpus: list[dict[str, Any]] | list[Any],
        k1: float = 1.5,
        b: float = 0.75,
    ):
        if not corpus:
            raise ValueError("corpus 不能为空")

        self._k1 = k1
        self._b = b

        # 统一获取 text 和 chunk_id
        self._chunk_ids: list[str] = []
        doc_term_freqs: list[Counter[str]] = []
        doc_lengths: list[int] = []

        for chunk in corpus:
            text = self._get_text(chunk)
            chunk_id = self._get_chunk_id(chunk)
            self._chunk_ids.append(chunk_id)
            tokens = tokenize(text or "")
            doc_term_freqs.append(Counter(tokens))
            doc_lengths.append(len(tokens))

        self._doc_term_freqs = doc_term_freqs
        self._doc_lengths = doc_lengths
        self._doc_count = len(corpus)
        self._avgdl = mean(doc_lengths) if doc_lengths else 0.0

    def score(self, query: str) -> list[tuple[str, float]]:
        """对给定 query 计算所有 chunk 的 BM25 分数。

        返回 [(chunk_id, score), ...] 按 score 降序排列。
        只包含 score > 0 的结果。
        """
        query = query.strip()
        if not query:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        # 计算 query IDF
        query_idf: dict[str, float] = {}
        unique_q = set(query_tokens)
        for qi in unique_q:
            df = sum(1 for dtf in self._doc_term_freqs if qi in dtf)
            query_idf[qi] = math.log(
                (self._doc_count - df + 0.5) / (df + 0.5) + 1.0
            )

        # 对每个 chunk 计算 BM25
        scored: list[tuple[str, float]] = []
        for idx in range(self._doc_count):
            doc_len = self._doc_lengths[idx]
            if doc_len == 0:
                continue

            score = 0.0
            dtf = self._doc_term_freqs[idx]
            for qi in unique_q:
                idf = query_idf.get(qi, 0)
                if idf == 0:
                    continue
                f = dtf.get(qi, 0)
                if f == 0:
                    continue
                numerator = f * (self._k1 + 1)
                denominator = f + self._k1 * (
                    1 - self._b + self._b * doc_len / self._avgdl
                )
                score += idf * numerator / denominator

            if score > 0:
                scored.append((self._chunk_ids[idx], round(score, 6)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    @staticmethod
    def _get_text(chunk: Any) -> str:
        """从 chunk 中提取文本，兼容 dict 和 CorpusChunk。"""
        if isinstance(chunk, dict):
            return chunk.get("text", "") or ""
        return getattr(chunk, "text", "") or ""

    @staticmethod
    def _get_chunk_id(chunk: Any) -> str:
        """从 chunk 中提取 chunk_id，兼容 dict 和 CorpusChunk。"""
        if isinstance(chunk, dict):
            return chunk.get("chunk_id", "")
        return getattr(chunk, "chunk_id", "")


def bm25_scorer(
    corpus: list[dict[str, Any]] | list[Any],
    k1: float = 1.5,
    b: float = 0.75,
) -> BM25Scorer:
    """创建 BM25Scorer 的便捷函数。"""
    return BM25Scorer(corpus, k1=k1, b=b)
