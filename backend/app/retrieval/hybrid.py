"""V3 阶段 4B：RRF Hybrid Retrieval（BM25 + Dense）。

使用标准 Reciprocal Rank Fusion：
    RRF_score(d) = 1/(k + rank_bm25(d)) + 1/(k + rank_dense(d))
    k = 60, rank 从 1 开始, 两路等权。

返回结果包含 rrf_score、bm25_rank、dense_rank。
"""

from __future__ import annotations

from typing import Any

RRF_K = 60


def hybrid_rrf_retrieve(
    query: str,
    corpus: list[dict[str, Any]],
    top_k: int,
    *,
    bm25_retrieve_fn=None,
    dense_retrieve_fn=None,
    rrf_k: int = RRF_K,
) -> list[dict[str, Any]]:
    """RRF 混合检索：融合 BM25 与 Dense 排名。

    bm25_retrieve_fn / dense_retrieve_fn: 检索函数，签名为 fn(q, corpus, top_k) -> list[dict]

    步骤：
    1. 对全部 Corpus chunk 执行 BM25 排序 → 计算 rank
    2. 对全部 Corpus chunk 执行 Dense 排序 → 计算 rank
    3. RRF 融合 → 按 rrf_score 降序、chunk_id 升序返回 top_k

    返回的每个结果除原有字段外，额外携带：
        rrf_score, bm25_rank, dense_rank
    """
    if not corpus:
        return []

    # 获取两路全排序（top_k=len(corpus)）
    bm25_results = bm25_retrieve_fn(query, corpus, top_k=len(corpus))
    dense_results = dense_retrieve_fn(query, corpus, top_k=len(corpus))

    # 建立 chunk_id → rank 映射（rank 从 1 开始）
    bm25_rank_map: dict[str, int] = {}
    for rank, r in enumerate(bm25_results, start=1):
        bm25_rank_map[r["chunk_id"]] = rank

    dense_rank_map: dict[str, int] = {}
    for rank, r in enumerate(dense_results, start=1):
        dense_rank_map[r["chunk_id"]] = rank

    # 所有出现过的 chunk_id
    all_cids = set(bm25_rank_map.keys()) | set(dense_rank_map.keys())

    # 计算 RRF 分数
    scored: list[tuple[float, str, int, int, int]] = []  # (rrf, cid, corpus_idx, bm25_r, dense_r)
    for i, chunk in enumerate(corpus):
        cid = chunk["chunk_id"]
        if cid not in all_cids:
            continue
        bm25_r = bm25_rank_map.get(cid, 0)
        dense_r = dense_rank_map.get(cid, 0)
        if bm25_r == 0 or dense_r == 0:
            # 只在一路中出现过，RRF 只用存在的那路
            rrf = (1.0 / (rrf_k + bm25_r) if bm25_r > 0 else 0) + \
                  (1.0 / (rrf_k + dense_r) if dense_r > 0 else 0)
        else:
            rrf = 1.0 / (rrf_k + bm25_r) + 1.0 / (rrf_k + dense_r)
        scored.append((rrf, cid, i, bm25_r, dense_r))

    # 排序：rrf_score 降序 → chunk_id 升序
    scored.sort(key=lambda x: (-x[0], x[1]))

    results = []
    for rrf_score, cid, idx, bm25_r, dense_r in scored[:top_k]:
        chunk = corpus[idx]
        result = {
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
            "score": round(rrf_score, 6),
            "retrieval_mode": "hybrid_rrf",
            "rrf_score": round(rrf_score, 6),
            "bm25_rank": bm25_r,
            "dense_rank": dense_r,
        }
        results.append(result)

    return results
