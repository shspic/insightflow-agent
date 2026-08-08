"""V3 检索基线实现：关键词检索、TF-IDF、Okapi BM25。

本模块提供三种独立检索基线，每种返回 (chunk_id, score) 排序列表。
检索结果包含当前 chunk 的 locator、file_role 和 file_name。
所有检索算法均为纯 Python 实现，不依赖 Chroma/FAISS 或任何向量数据库。
"""

import math
from collections import Counter
from statistics import mean
from typing import Any

import numpy as np

from app.retrieval.tokenizer import tokenize

# -- 关键词检索 --


def keyword_retrieve(
    query: str,
    corpus: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    query_lower = query.lower()
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    results: list[dict[str, Any]] = []
    for chunk in corpus:
        score = _keyword_score(query_lower, query_tokens, chunk["text"].lower())
        if score > 0:
            results.append(_result_from_chunk(chunk, score, "keyword"))

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def _keyword_score(query_lower: str, query_tokens: list[str], chunk_lower: str) -> float:
    score = 0.0
    if query_lower in chunk_lower:
        score += 5.0
    for token in query_tokens:
        score += chunk_lower.count(token)
    return score


# -- TF-IDF 检索 --


def tfidf_retrieve(
    query: str,
    corpus: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query or not corpus:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    chunk_texts = [c["text"] or "" for c in corpus]
    chunk_tokens = [tokenize(ct) for ct in chunk_texts]
    doc_freq = _build_doc_freq(chunk_tokens)
    doc_count = len(chunk_tokens)

    query_vec = _build_tfidf_vec(query_tokens, doc_freq, doc_count)

    results: list[dict[str, Any]] = []
    for chunk, tokens in zip(corpus, chunk_tokens):
        chunk_vec = _build_tfidf_vec(tokens, doc_freq, doc_count)
        score = _cosine_sim(query_vec, chunk_vec)
        if score > 0:
            results.append(_result_from_chunk(chunk, round(score, 6), "tfidf"))

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def _build_doc_freq(doc_tokens: list[list[str]]) -> Counter[str]:
    freq: Counter[str] = Counter()
    for tokens in doc_tokens:
        freq.update(set(tokens))
    return freq


def _build_tfidf_vec(
    tokens: list[str],
    doc_freq: Counter[str],
    doc_count: int,
) -> dict[str, float]:
    tf = Counter(tokens)
    vec: dict[str, float] = {}
    for term, count in tf.items():
        df = doc_freq.get(term, 0)
        idf = math.log((doc_count + 1) / (df + 1)) + 1
        vec[term] = count * idf
    return vec


def _cosine_sim(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[t] * right[t] for t in shared)
    l_norm = math.sqrt(sum(v * v for v in left.values()))
    r_norm = math.sqrt(sum(v * v for v in right.values()))
    if l_norm == 0 or r_norm == 0:
        return 0.0
    return dot / (l_norm * r_norm)


# -- Okapi BM25 检索 --


def bm25_retrieve(
    query: str,
    corpus: list[dict[str, Any]],
    top_k: int,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query or not corpus:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    doc_term_freqs: list[Counter[str]] = []
    doc_lengths: list[int] = []

    for chunk in corpus:
        tokens = tokenize(chunk["text"] or "")
        doc_term_freqs.append(Counter(tokens))
        doc_lengths.append(len(tokens))

    if not doc_lengths:
        return []

    avgdl = mean(doc_lengths) if doc_lengths else 0
    doc_count = len(corpus)

    query_idf: dict[str, float] = {}
    for qi in set(query_tokens):
        df = sum(1 for dtf in doc_term_freqs if qi in dtf)
        query_idf[qi] = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)

    results: list[dict[str, Any]] = []
    for idx, chunk in enumerate(corpus):
        dtf = doc_term_freqs[idx]
        doc_len = doc_lengths[idx]
        if doc_len == 0:
            continue

        score = 0.0
        for qi in set(query_tokens):
            idf = query_idf.get(qi, 0)
            if idf == 0:
                continue
            f = dtf.get(qi, 0)
            if f == 0:
                continue
            numerator = f * (k1 + 1)
            denominator = f + k1 * (1 - b + b * doc_len / avgdl)
            score += idf * numerator / denominator

        if score > 0:
            results.append(_result_from_chunk(chunk, round(score, 6), "bm25"))

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


# -- Dense 检索 --


def make_dense_retriever(
    corpus_embeddings: Any,  # np.ndarray [n_chunks, dim]
    encode_query_fn: Any,    # fn(query_text: str) -> np.ndarray
    chunk_ids_corpus_order: list[str] | None = None,
):
    """创建 dense_retrieve 闭包，预绑定 corpus embeddings 和 query 编码函数。

    返回函数签名与 keyword_retrieve/tfidf_retrieve/bm25_retrieve 一致：
        fn(query: str, corpus: list[dict], top_k: int) -> list[dict]

    corpus_embeddings: 按 corpus 顺序排列的预计算归一化向量
    encode_query_fn: 接受单条 query 文本，返回归一化向量
    """

    # 建立 chunk_id → embedding_idx 映射
    if chunk_ids_corpus_order is not None:
        id_to_idx = {cid: i for i, cid in enumerate(chunk_ids_corpus_order)}
    else:
        id_to_idx = {}

    def dense_retrieve(
        query: str,
        corpus: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query or not corpus:
            return []

        # 编码 query
        q_vec = encode_query_fn(query)

        # cosine similarity = dot product（因为向量已归一化）
        # 只对 corpus 中的 chunk 计算
        scores: list[tuple[float, int, str]] = []  # (score, idx, chunk_id)
        for i, chunk in enumerate(corpus):
            cid = chunk["chunk_id"]
            emb_idx = id_to_idx.get(cid, i) if id_to_idx else i
            if emb_idx < len(corpus_embeddings):
                sim = float(np.dot(q_vec, corpus_embeddings[emb_idx]))
                if sim > 0:
                    scores.append((sim, i, cid))

        # 排序：score 降序 → chunk_id 升序（稳定排序）
        scores.sort(key=lambda x: (-x[0], x[2]))

        results = []
        for sim, idx, cid in scores[:top_k]:
            chunk = corpus[idx]
            result = _result_from_chunk(chunk, round(sim, 6), "dense")
            results.append(result)

        return results

    return dense_retrieve


# -- 结果构建 --


def _result_from_chunk(
    chunk: dict[str, Any],
    score: float,
    retrieval_mode: str,
) -> dict[str, Any]:
    """从语料分块构建检索结果，携带完整 locator。"""
    return {
        "chunk_id": chunk["chunk_id"],
        "file_role": chunk["file_role"],
        "file_name": chunk["file_name"],
        "locator_type": chunk["locator_type"],
        "page_number": chunk.get("page_number"),
        "sheet_name": chunk.get("sheet_name"),
        "cell_range": chunk.get("cell_range"),
        "text_chunk_index": chunk.get("text_chunk_index"),
        "section_title": chunk.get("section_title"),
        "text": chunk["text"],
        "score": score,
        "retrieval_mode": retrieval_mode,
    }
