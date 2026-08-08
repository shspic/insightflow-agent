#!/usr/bin/env python3
"""Stage 4B 真实模型显式验证。

仅在用户明确运行时加载真实 BGE 模型。
不在 pytest 收集范围内（位于 scripts/，非 tests/），不会被 pytest 自动发现。

用途：
    加载固定 revision 的真实 BGE → 编码 passage/query → 验证 512 维和 L2 norm
    → 加载已持久化 Dense Index → 执行 Dense → 执行 Hybrid RRF → 输出模型与索引 metadata

要求：
    - 只有用户明确运行脚本时才加载真实模型
    - 支持 --model-cache-dir 指定缓存目录
    - 支持 --index-dir 指定索引目录
    - 支持离线模式（环境变量 HF_HUB_OFFLINE=1）
    - 出错返回非零退出码
    - 不得通过 skip 掩盖失败
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# 确保 backend 在 sys.path 中
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def main():
    parser = argparse.ArgumentParser(description="Stage 4B 真实模型显式验证")
    parser.add_argument(
        "--model-cache-dir",
        default=None,
        help="模型缓存目录（默认使用 backend/data/model_cache）",
    )
    parser.add_argument(
        "--index-dir",
        default=None,
        help="Dense Index 目录",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="强制离线模式（等价于 HF_HUB_OFFLINE=1）",
    )
    args = parser.parse_args()

    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    errors = []

    # ---- 1. 加载真实模型 ----
    print("=" * 60)
    print("[1/5] 加载真实 LocalEmbeddingProvider …")
    print("=" * 60)

    from app.evaluation.v3_embedding import (
        LocalEmbeddingProvider,
        MODEL_REPO_ID,
        MODEL_REVISION,
        QUERY_INSTRUCTION,
        EmbeddingError,
    )
    from app.evaluation.v3_dense_index import (
        load_dense_index,
        DenseIndexError,
    )
    from app.evaluation.v3_corpus import CHUNKING_VERSION, build_corpus
    from app.evaluation.v3_hybrid import hybrid_rrf_retrieve, RRF_K
    from app.evaluation.v3_retrieval import (
        make_dense_retriever,
        bm25_retrieve,
    )

    try:
        provider = LocalEmbeddingProvider(
            model_repo_id=MODEL_REPO_ID,
            model_revision=MODEL_REVISION,
            query_instruction=QUERY_INSTRUCTION,
            cache_dir=args.model_cache_dir,
            batch_size=8,
        )
        t0 = time.perf_counter()
        provider._ensure_loaded()
        load_time = (time.perf_counter() - t0) * 1000

        meta = provider.metadata()
        print(f"  provider: {meta['provider']}")
        print(f"  model_repo_id: {meta['model_repo_id']}")
        print(f"  model_revision: {meta['model_revision']}")
        print(f"  dimension: {meta['dimension']}")
        print(f"  normalize_embeddings: {meta['normalize_embeddings']}")
        print(f"  query_instruction: {meta['query_instruction']}")
        print(f"  batch_size: {meta['batch_size']}")
        print(f"  加载耗时: {load_time:.0f} ms")

        assert meta["provider"] == "sentence-transformers", "provider 不是 sentence-transformers"
        assert meta["model_repo_id"] == MODEL_REPO_ID
        assert meta["model_revision"] == MODEL_REVISION
        assert meta["dimension"] == 512
        assert meta["normalize_embeddings"] is True
        assert meta["query_instruction"] == QUERY_INSTRUCTION
        print("  [PASS] 模型 metadata 验证通过")

    except EmbeddingError as e:
        print(f"  [FAIL] 模型加载失败: {e}")
        sys.exit(1)
    except AssertionError as e:
        print(f"  [FAIL] 模型 metadata 校验失败: {e}")
        sys.exit(1)

    # ---- 2. Passage & Query 编码 ----
    print()
    print("=" * 60)
    print("[2/5] Passage & Query 编码测试 …")
    print("=" * 60)

    try:
        p_vecs = provider.encode_passages(["测试文本", "另一段文本"])
        q_vecs = provider.encode_queries(["查询问题"])

        assert p_vecs.dtype == np.float32, f"passage dtype: {p_vecs.dtype}"
        assert q_vecs.dtype == np.float32, f"query dtype: {q_vecs.dtype}"
        assert p_vecs.shape == (2, 512), f"passage shape: {p_vecs.shape}"
        assert q_vecs.shape == (1, 512), f"query shape: {q_vecs.shape}"

        p_norms = np.linalg.norm(p_vecs, axis=1)
        q_norms = np.linalg.norm(q_vecs, axis=1)
        assert np.allclose(p_norms, 1.0, atol=1e-4), f"passage norms: {p_norms}"
        assert np.allclose(q_norms, 1.0, atol=1e-4), f"query norms: {q_norms}"

        assert not np.isnan(p_vecs).any(), "passage 含 NaN"
        assert not np.isnan(q_vecs).any(), "query 含 NaN"
        assert not np.isinf(p_vecs).any(), "passage 含 Inf"
        assert not np.isinf(q_vecs).any(), "query 含 Inf"

        print(f"  dtype: float32 [PASS]")
        print(f"  dimension: 512 [PASS]")
        print(f"  L2 normalized: True [PASS]")
        print(f"  NaN/Inf: 无 [PASS]")
    except AssertionError as e:
        print(f"  [FAIL] 编码验证失败: {e}")
        sys.exit(1)

    # ---- 3. 加载 Dense Index ----
    print()
    print("=" * 60)
    print("[3/5] 加载 Dense Index …")
    print("=" * 60)

    golden_case_dir = (
        _REPO_ROOT / "examples" / "engineering_review_v1" / "golden_case"
    )
    index_dir = Path(args.index_dir) if args.index_dir else (
        _REPO_ROOT / "examples" / "engineering_review_v1" / "eval_indexes" / "bge-small-zh-v1.5"
    )

    if not index_dir.exists():
        print(f"  [FAIL] 索引目录不存在: {index_dir}")
        sys.exit(1)

    corpus = build_corpus(golden_case_dir)
    chunk_ids_corpus_order = [c["chunk_id"] for c in corpus]

    # 计算 corpus_sha256（与 runner 中 _corpus_sha256 逻辑一致）
    corpus_sha = hashlib.sha256()
    for chunk in sorted(corpus, key=lambda c: c["chunk_id"]):
        corpus_sha.update(chunk["text"].encode("utf-8"))
    corpus_sha256 = corpus_sha.hexdigest()

    try:
        t0 = time.perf_counter()
        corpus_embeddings, loaded_ids, idx_meta = load_dense_index(
            index_dir=index_dir,
            corpus_sha256=corpus_sha256,
            expected_chunk_ids=chunk_ids_corpus_order,
            expected_model_revision=MODEL_REVISION,
            expected_dimension=512,
            expected_model_repo_id=MODEL_REPO_ID,
            expected_chunking_version=CHUNKING_VERSION,
            expected_provider_meta=provider.metadata(),
        )
        load_time = (time.perf_counter() - t0) * 1000

        print(f"  index_sha256: {idx_meta.get('index_sha256', '?')[:16]}...")
        print(f"  chunk_count: {idx_meta.get('chunk_count')}")
        print(f"  dtype: {idx_meta.get('dtype')}")
        print(f"  加载耗时: {load_time:.0f} ms")
        print(f"  [PASS] 索引加载与契约校验通过")
    except DenseIndexError as e:
        print(f"  [FAIL] 索引加载失败: {e}")
        sys.exit(1)

    # ---- 4. Dense Retrieval ----
    print()
    print("=" * 60)
    print("[4/5] Dense 检索测试 …")
    print("=" * 60)

    try:
        def encode_query_fn(q):
            return provider.encode_queries([q])[0]

        dense_retrieve = make_dense_retriever(
            corpus_embeddings, encode_query_fn, chunk_ids_corpus_order
        )
        results = dense_retrieve("SYN-TENDER-001 财务要求", corpus, top_k=5)
        assert len(results) > 0, "Dense 检索无结果"
        assert all(r["retrieval_mode"] == "dense" for r in results)

        print(f"  top-5 结果:")
        for r in results:
            print(f"    {r['chunk_id']} ({r['file_role']}): score={r['score']:.4f}")
        print(f"  [PASS] Dense 检索通过")
    except Exception as e:
        print(f"  [FAIL] Dense 检索失败: {e}")
        sys.exit(1)

    # ---- 5. Hybrid RRF Retrieval ----
    print()
    print("=" * 60)
    print("[5/5] Hybrid RRF 检索测试 …")
    print("=" * 60)

    try:
        results = hybrid_rrf_retrieve(
            "SYN-TENDER-001 财务要求", corpus, top_k=5,
            bm25_retrieve_fn=bm25_retrieve,
            dense_retrieve_fn=dense_retrieve,
        )
        assert len(results) > 0, "Hybrid 检索无结果"
        assert all(r["retrieval_mode"] == "hybrid_rrf" for r in results)
        assert all("rrf_score" in r for r in results)
        assert all("bm25_rank" in r for r in results)
        assert all("dense_rank" in r for r in results)

        print(f"  top-5 结果:")
        for r in results:
            print(f"    {r['chunk_id']} ({r['file_role']}): rrf={r['rrf_score']:.4f} "
                  f"(bm25_r={r['bm25_rank']}, dense_r={r['dense_rank']})")
        print(f"  [PASS] Hybrid RRF 检索通过")
    except Exception as e:
        print(f"  [FAIL] Hybrid RRF 检索失败: {e}")
        sys.exit(1)

    # ---- 总结 ----
    print()
    print("=" * 60)
    print("[PASS] 所有检查通过！Stage 4B 真实模型验证成功。")
    print(f"  model: {MODEL_REPO_ID} @ {MODEL_REVISION[:8]}")
    print(f"  dimension: 512, dtype: float32, normalized: True")
    print(f"  index SHA: {idx_meta.get('index_sha256', '?')[:16]}...")
    print(f"  index reused: True")
    print("=" * 60)


if __name__ == "__main__":
    main()
