"""V3 检索评测基线运行器。

用法：
    # Stage 4A（仅 keyword/tfidf/bm25）
    cd backend
    .venv/Scripts/python.exe -m app.evaluation.v3_retrieval_runner \
        --case-dir ../examples/engineering_review_v1/golden_case \
        --output-dir ../examples/engineering_review_v1/eval_results \
        --split all --mode all --stage 4a

    # Stage 4B（全部 5 种模式，含 dense/hybrid_rrf）
    .venv/Scripts/python.exe -m app.evaluation.v3_retrieval_runner \
        --case-dir ../examples/engineering_review_v1/golden_case \
        --output-dir ../examples/engineering_review_v1/eval_results \
        --split all --mode all

输出目录结构（Stage 4B）：
    eval_results/stage4b/
      all/   retrieval_report.json, retrieval_report.md, failures.json
      dev/   ...
      test/  ...
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.evaluation.v3_corpus import CHUNKING_VERSION, build_corpus
from app.evaluation.v3_metrics import (
    aggregate_answerable,
    aggregate_by_category,
    aggregate_no_answer,
    compute_answerable_metrics,
    compute_no_answer_metrics,
    verify_toy_case,
)
from app.evaluation.v3_query_set import load_query_set
from app.evaluation.v3_retrieval import (
    bm25_retrieve,
    keyword_retrieve,
    make_dense_retriever,
    tfidf_retrieve,
)
from app.evaluation.v3_hybrid import hybrid_rrf_retrieve, RRF_K

# tokenizer 版本常量
TOKENIZER_NAME = "v3_tokenizer"
TOKENIZER_VERSION = "1.0.0"

# 基础检索器（不需要额外初始化）
_BASE_RETRIEVERS: dict[str, tuple[str, Any]] = {
    "keyword": ("关键词检索", keyword_retrieve),
    "tfidf": ("TF-IDF", tfidf_retrieve),
    "bm25": ("Okapi BM25", bm25_retrieve),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行 V3 检索评测基线（keyword / TF-IDF / BM25 / Dense / Hybrid RRF）"
    )
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--split", choices=["all", "dev", "test"], default="all",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "keyword", "tfidf", "bm25", "dense", "hybrid_rrf"],
        default="all",
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument(
        "--rebuild-index", action="store_true",
        help="强制重建 Dense Index（忽略已有索引）",
    )
    parser.add_argument(
        "--model-cache-dir", type=str, default=None,
        help="Hugging Face 模型缓存目录",
    )
    parser.add_argument(
        "--stage", choices=["4a", "4b"], default="4b",
        help="评测阶段（决定输出子目录和模式范围）",
    )
    args = parser.parse_args(argv)

    # -- 0. 玩具案例验证 --
    toy = verify_toy_case()
    checks = [
        ("recall@3_correct", "recall@3"),
        ("recall@5_correct", "recall@5"),
        ("mrr_correct", "mrr"),
        ("no_answer_fp_correct", "no-answer false_positive"),
        ("answerable_count_correct", "answerable count"),
        ("no_answer_count_correct", "no_answer count"),
        ("no_answer_fp_rate_correct", "no-answer fp_rate"),
    ]
    failed = []
    for check_key, label in checks:
        if not toy.get(check_key):
            failed.append(label)
    if failed:
        print(f"[FAIL] 玩具案例验证失败: {', '.join(failed)}")
        return 1
    print("[PASS] 玩具案例公式验证通过")

    # -- 1. 构建语料 --
    print(f"\n[corpus] 构建检索语料")
    corpus = build_corpus(args.case_dir)
    print(f"   共 {len(corpus)} 个分块")
    corpus_sha256 = _corpus_sha256(corpus)
    print(f"   语料 SHA-256: {corpus_sha256}")

    # -- 2. 加载查询集并验证 corpus SHA --
    query_path = args.case_dir / "retrieval_queries.json"
    if not query_path.exists():
        print(f"[FAIL] 查询集文件不存在: {query_path}")
        return 1

    all_queries, query_file_sha256, raw_data = load_query_set(query_path)
    dataset_version = raw_data.get("version", "1.0.0")
    expected_corpus_sha = raw_data.get("corpus_sha256", "")
    if expected_corpus_sha and expected_corpus_sha != corpus_sha256:
        print(f"[FAIL] corpus SHA 不一致！")
        print(f"  查询集声明: {expected_corpus_sha}")
        print(f"  实际构建:   {corpus_sha256}")
        return 1

    if args.split != "all":
        queries = [q for q in all_queries if q["split"] == args.split]
    else:
        queries = all_queries

    _print_query_stats(queries, all_queries)

    # -- 3. 校验 chunk_id 引用 --
    corpus_ids = {c["chunk_id"] for c in corpus}
    for q in queries:
        for cid in q["relevant_chunk_ids"]:
            if cid not in corpus_ids:
                print(f"[FAIL] 查询 {q['query_id']} 引用不存在的分块: {cid}")
                return 1

    # -- 4. 确定检索模式与输出目录 --
    all_stage_modes = ["keyword", "tfidf", "bm25"]
    stage4b_modes = ["dense", "hybrid_rrf"]
    if args.stage == "4b":
        all_stage_modes = all_stage_modes + stage4b_modes

    if args.mode == "all":
        modes_to_run = all_stage_modes
    else:
        modes_to_run = [args.mode]

    # 输出子目录：stage4b 模式使用 stage4b/ 子目录
    uses_stage4b = args.stage == "4b" and any(
        m in stage4b_modes for m in modes_to_run
    )
    output_base = args.output_dir
    if uses_stage4b:
        output_base = args.output_dir / "stage4b"

    # -- 5. Dense Index 与 Hybrid 设置 --
    retriever_map: dict[str, tuple[str, Any]] = dict(_BASE_RETRIEVERS)
    dense_index_info: dict[str, Any] | None = None
    embedding_meta: dict[str, Any] | None = None
    model_dimension: int | None = None

    needs_dense = any(m in ("dense", "hybrid_rrf") for m in modes_to_run)

    if needs_dense:
        from app.evaluation.v3_embedding import (
            FakeEmbeddingProvider,
            LocalEmbeddingProvider,
            MODEL_REPO_ID,
            MODEL_REVISION,
            QUERY_INSTRUCTION,
            EmbeddingError,
        )
        from app.evaluation.v3_dense_index import (
            build_dense_index,
            load_dense_index,
            validate_index_exists,
            DenseIndexError,
        )

        # 索引目录
        index_dir = args.case_dir.parent / "eval_indexes" / "bge-small-zh-v1.5"

        # 加载 embedding provider
        print(f"\n[embedding] 加载模型: {MODEL_REPO_ID} @ {MODEL_REVISION[:8]}...")
        load_start = time.perf_counter()
        try:
            provider = LocalEmbeddingProvider(
                model_repo_id=MODEL_REPO_ID,
                model_revision=MODEL_REVISION,
                cache_dir=args.model_cache_dir,
                batch_size=8,
            )
            provider._ensure_loaded()
            embedding_meta = provider.metadata()
            model_dimension = embedding_meta["dimension"]
            load_time_ms = (time.perf_counter() - load_start) * 1000
            print(f"   模型维度: {model_dimension}, 加载耗时: {load_time_ms:.0f} ms")
        except EmbeddingError as e:
            print(f"[FAIL] 模型加载失败: {e}")
            return 1

        # 索引处理
        index_reused = False
        index_build_time_ms: float = 0.0
        index_load_time_ms: float = 0.0

        if args.rebuild_index or not validate_index_exists(index_dir):
            # 构建新索引
            if args.rebuild_index:
                print(f"\n[index] 强制重建 Dense Index...")
            else:
                print(f"\n[index] 索引不存在，开始构建...")

            chunk_ids_corpus_order = [c["chunk_id"] for c in corpus]
            corpus_texts = [c["text"] for c in corpus]
            print(f"   编码 {len(corpus_texts)} 个 Corpus chunk...")
            encode_start = time.perf_counter()
            corpus_embeddings = provider.encode_passages(corpus_texts)
            encode_time_ms = (time.perf_counter() - encode_start) * 1000
            print(f"   编码耗时: {encode_time_ms:.0f} ms, shape: {corpus_embeddings.shape}")

            build_result = build_dense_index(
                embeddings=corpus_embeddings,
                chunk_ids=chunk_ids_corpus_order,
                corpus_sha256=corpus_sha256,
                provider_meta=embedding_meta,
                output_dir=index_dir,
                chunking_version=CHUNKING_VERSION,
            )
            index_build_time_ms = build_result["build_time_ms"]
            index_sha256 = build_result["index_sha256"]
            print(f"   索引 SHA-256: {index_sha256[:16]}...")
            print(f"   构建耗时: {index_build_time_ms:.0f} ms")
        else:
            # 加载已有索引
            print(f"\n[index] 检测到已有索引，尝试复用...")
            load_idx_start = time.perf_counter()
            chunk_ids_corpus_order = [c["chunk_id"] for c in corpus]
            try:
                corpus_embeddings, loaded_ids, idx_meta = load_dense_index(
                    index_dir=index_dir,
                    corpus_sha256=corpus_sha256,
                    expected_chunk_ids=chunk_ids_corpus_order,
                    expected_model_revision=MODEL_REVISION,
                    expected_dimension=model_dimension,
                    expected_model_repo_id=MODEL_REPO_ID,
                    expected_chunking_version=CHUNKING_VERSION,
                    expected_provider_meta=embedding_meta,
                )
                index_load_time_ms = (time.perf_counter() - load_idx_start) * 1000
                index_reused = True
                index_sha256 = idx_meta.get("index_sha256", "")
                print(f"   索引复用成功: SHA-256={index_sha256[:16]}..., 加载耗时: {index_load_time_ms:.0f} ms")
            except DenseIndexError as e:
                print(f"[FAIL] 索引校验失败: {e}")
                print(f"   请使用 --rebuild-index 重建索引")
                return 1

        # 记录索引信息
        npz_stat = (index_dir / "dense_index.npz").stat()
        meta_stat = (index_dir / "dense_index_meta.json").stat()
        dense_index_info = {
            "index_dir": str(index_dir),
            "index_file_sha256": index_sha256,
            "index_metadata_sha256": _file_sha256(index_dir / "dense_index_meta.json"),
            "index_reused": index_reused,
            "index_build_time_ms": round(index_build_time_ms, 1),
            "index_load_time_ms": round(index_load_time_ms, 1),
            "npz_mtime": datetime.fromtimestamp(npz_stat.st_mtime, tz=timezone.utc).isoformat(),
            "meta_mtime": datetime.fromtimestamp(meta_stat.st_mtime, tz=timezone.utc).isoformat(),
        }

        # 构建 dense retriever（闭包预绑定 corpus embeddings 和 query 编码函数）
        def _encode_single_query(q_text: str) -> np.ndarray:
            return provider.encode_queries([q_text])[0]

        dense_fn = make_dense_retriever(
            corpus_embeddings=corpus_embeddings,
            encode_query_fn=_encode_single_query,
            chunk_ids_corpus_order=chunk_ids_corpus_order,
        )
        retriever_map["dense"] = ("Dense (BGE-small-zh)", dense_fn)

        # 构建 hybrid RRF retriever
        def _hybrid_fn(query: str, corpus_l: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
            return hybrid_rrf_retrieve(
                query, corpus_l, top_k,
                bm25_retrieve_fn=bm25_retrieve,
                dense_retrieve_fn=dense_fn,
                rrf_k=RRF_K,
            )
        retriever_map["hybrid_rrf"] = ("BM25+Dense RRF (k=60)", _hybrid_fn)

    # -- 6. 运行检索评测 --
    print(f"\n[eval] 运行检索评测 (split={args.split}, mode={args.mode}, top_k={args.top_k})")
    all_results: dict[str, dict[str, Any]] = {}
    all_failures: list[dict[str, Any]] = []

    for mode_key in modes_to_run:
        mode_label, retriever_fn = retriever_map[mode_key]
        print(f"\n   {mode_label} ({mode_key}):")

        ans_metrics, na_metrics, failures = _run_one_retriever(
            retriever_fn, queries, corpus, mode_key, args.top_k,
        )
        all_results[mode_key] = {
            "label": mode_label,
            "answerable_aggregate": ans_metrics,
            "no_answer_aggregate": na_metrics,
            "per_query_answerable": ans_metrics.get("_per_query", []),
            "per_query_no_answer": na_metrics.get("_per_query", []),
        }
        all_failures.extend(failures)

        # 可回答指标
        print(f"     Recall@3:  {ans_metrics.get('recall@3_mean', 0):.4f}")
        print(f"     Recall@5:  {ans_metrics.get('recall@5_mean', 0):.4f}")
        print(f"     MRR:       {ans_metrics.get('mrr_mean', 0):.4f}")
        print(f"     延迟均值:  {ans_metrics.get('latency_mean_ms', 0):.1f} ms")
        print(f"     延迟 P50:  {ans_metrics.get('latency_p50_ms', 0):.1f} ms")
        print(f"     延迟 P95:  {ans_metrics.get('latency_p95_ms', 0):.1f} ms")
        # 无答案指标
        print(f"     no-answer FP 率: {na_metrics.get('false_positive_rate', 0):.4f}")
        print(f"     no-answer 个数:  {na_metrics.get('no_answer_count', 0)}")

    # -- 7. 计算 category 级别指标 --
    cat_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for mode_key in modes_to_run:
        per_query_ans = all_results[mode_key].get("per_query_answerable", [])
        cat_metrics[mode_key] = aggregate_by_category(per_query_ans, queries)

    # -- 8. 生成报告 --
    split_label = args.split  # all, dev, test
    out_dir = output_base / split_label
    out_dir.mkdir(parents=True, exist_ok=True)

    git_commit = _get_git_commit()
    git_branch = _get_git_branch()
    git_dirty = _get_git_dirty()
    manifest_path = args.case_dir / "manifest.json"
    manifest_sha = _file_sha256(manifest_path)

    # repo root：从 case_dir 向上找到包含 .git 的目录
    repo_root = _find_repo_root(args.case_dir)
    eval_source_files = _get_evaluation_source_files(repo_root)
    eval_code_sha = _eval_code_sha256(eval_source_files)

    report = _build_report(
        queries=queries,
        corpus=corpus,
        corpus_sha256=corpus_sha256,
        query_file_sha256=query_file_sha256,
        manifest_sha=manifest_sha,
        all_results=all_results,
        cat_metrics=cat_metrics,
        failures=all_failures,
        top_k=args.top_k,
        split=split_label,
        modes=modes_to_run,
        git_commit=git_commit,
        git_branch=git_branch,
        git_dirty=git_dirty,
        dataset_version=dataset_version,
        eval_code_sha256=eval_code_sha,
        eval_source_files=eval_source_files,
        embedding_meta=embedding_meta,
        dense_index_info=dense_index_info,
        rrf_k=RRF_K if any(m == "hybrid_rrf" for m in modes_to_run) else None,
        uses_stage4b=uses_stage4b,
    )

    # JSON 报告
    json_path = out_dir / "retrieval_report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\n[report] JSON: {json_path}")

    # Markdown 报告
    md_path = out_dir / "retrieval_report.md"
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"[report] Markdown: {md_path}")

    # 失败案例
    fail_path = out_dir / "failures.json"
    fail_path.write_text(
        json.dumps(all_failures, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    unique_fail_qids = len({f["query_id"] for f in all_failures})
    print(f"[report] 失败案例: {fail_path} ({len(all_failures)} 条 mode-query, {unique_fail_qids} 个唯一 query)")

    # -- 8. 摘要 --
    _print_summary(all_results, modes_to_run)

    return 0


# -- 单检索器运行 --


def _run_one_retriever(
    retriever_fn,
    queries: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    mode_key: str,
    top_k: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    per_query_ans: list[dict[str, Any]] = []
    per_query_na: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    answerable = [q for q in queries if q.get("answerable")]
    no_answer = [q for q in queries if not q.get("answerable")]

    # 可回答查询
    for q in answerable:
        start = time.perf_counter()
        try:
            retrieved = retriever_fn(q["query_text"], corpus, top_k=top_k)
        except Exception as exc:
            print(f"     [WARN] {q['query_id']} 检索异常: {exc}")
            retrieved = []
        latency_ms = (time.perf_counter() - start) * 1000

        retrieved_ids = [r["chunk_id"] for r in retrieved]
        metrics = compute_answerable_metrics(
            q["query_id"], retrieved_ids, q["relevant_chunk_ids"], latency_ms,
        )
        per_query_ans.append(metrics)

        # 失败检测
        if metrics.get("recall@5", 1.0) == 0.0:
            failures.append({
                "query_id": q["query_id"],
                "split": q["split"],
                "category": q["category"],
                "retrieval_mode": mode_key,
                "failure_type": "recall_at_5_miss",
                "recall@5": metrics["recall@5"],
                "mrr": metrics["mrr"],
                "relevant_chunk_ids": q["relevant_chunk_ids"],
                "retrieved_chunk_ids": retrieved_ids[:5],
                "manual_failure_category": None,
            })

    # 无答案查询
    for q in no_answer:
        start = time.perf_counter()
        try:
            retrieved = retriever_fn(q["query_text"], corpus, top_k=top_k)
        except Exception as exc:
            print(f"     [WARN] {q['query_id']} 检索异常: {exc}")
            retrieved = []
        latency_ms = (time.perf_counter() - start) * 1000

        retrieved_ids = [r["chunk_id"] for r in retrieved]
        scores = [r["score"] for r in retrieved]
        metrics = compute_no_answer_metrics(
            q["query_id"], retrieved_ids, scores, latency_ms,
        )
        per_query_na.append(metrics)

        # 误报检测
        if metrics["false_positive"]:
            failures.append({
                "query_id": q["query_id"],
                "split": q["split"],
                "category": q["category"],
                "retrieval_mode": mode_key,
                "failure_type": "no_answer_false_positive",
                "recall@5": 0.0,
                "mrr": 0.0,
                "relevant_chunk_ids": [],
                "retrieved_chunk_ids": retrieved_ids[:5],
                "manual_failure_category": None,
            })

    ans_agg = aggregate_answerable(per_query_ans)
    ans_agg["_per_query"] = per_query_ans
    na_agg = aggregate_no_answer(per_query_na)
    na_agg["_per_query"] = per_query_na

    return ans_agg, na_agg, failures


# -- 报告构建 --


def _build_report(
    queries: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    corpus_sha256: str,
    query_file_sha256: str,
    manifest_sha: str,
    all_results: dict[str, dict[str, Any]],
    cat_metrics: dict[str, dict[str, dict[str, Any]]],
    failures: list[dict[str, Any]],
    top_k: int,
    split: str,
    modes: list[str],
    git_commit: str,
    git_branch: str = "",
    git_dirty: bool | None = None,
    dataset_version: str = "1.1.0",
    eval_code_sha256: str = "",
    eval_source_files: list[dict[str, str]] | None = None,
    embedding_meta: dict[str, Any] | None = None,
    dense_index_info: dict[str, Any] | None = None,
    rrf_k: int | None = None,
    uses_stage4b: bool = False,
) -> dict[str, Any]:
    answerable = [q for q in queries if q.get("answerable")]
    no_answer = [q for q in queries if not q.get("answerable")]

    meta: dict[str, Any] = {
        "dataset_name": "engineering-review-v1",
        "dataset_version": dataset_version,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "合成演示数据，不作为真实招投标、工程、资质或法律判断依据。",
        "query_file_sha256": query_file_sha256,
        "corpus_sha256": corpus_sha256,
        "manifest_sha256": manifest_sha,
        "tokenizer": TOKENIZER_NAME,
        "tokenizer_version": TOKENIZER_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "python_version": platform.python_version(),
        "git_commit": git_commit,
        "git_branch": git_branch,
        "git_dirty": git_dirty,
        "evaluation_code_sha256": eval_code_sha256,
        "evaluation_source_files": eval_source_files or [],
        "stage": "4b" if uses_stage4b else "4a",
        "split": split,
        "retrieval_modes": modes,
        "top_k": top_k,
        "query_count": len(queries),
        "answerable_count": len(answerable),
        "no_answer_count": len(no_answer),
        "platform": platform.platform(),
    }

    # Stage 4B 扩展元数据
    if uses_stage4b and embedding_meta:
        import sentence_transformers
        import torch as _torch_module
        meta.update({
            "embedding_provider": embedding_meta.get("provider", "sentence-transformers"),
            "model_repo_id": embedding_meta.get("model_repo_id", ""),
            "model_revision": embedding_meta.get("model_revision", ""),
            "model_dimension": embedding_meta.get("dimension", 0),
            "normalize_embeddings": embedding_meta.get("normalize_embeddings", True),
            "query_instruction": embedding_meta.get("query_instruction", ""),
            "sentence_transformers_version": sentence_transformers.__version__,
            "torch_version": _torch_module.__version__,
            "numpy_version": np.__version__,
            "device": "cpu",
        })
        if dense_index_info:
            meta.update({
                "index_file_sha256": dense_index_info.get("index_file_sha256", ""),
                "index_metadata_sha256": dense_index_info.get("index_metadata_sha256", ""),
                "index_reused": dense_index_info.get("index_reused", False),
                "dense_index_build_time_ms": dense_index_info.get("index_build_time_ms", 0),
                "dense_index_load_time_ms": dense_index_info.get("index_load_time_ms", 0),
            })
        if rrf_k is not None:
            meta.update({
                "rrf_k": rrf_k,
                "fusion_sources": ["bm25", "dense"],
            })

    return {
        "meta": meta,
        "corpus": {
            "chunk_count": len(corpus),
            "sha256": corpus_sha256,
            "chunks": [
                {
                    "chunk_id": c["chunk_id"],
                    "file_role": c["file_role"],
                    "file_name": c["file_name"],
                    "locator_type": c["locator_type"],
                    "page_number": c.get("page_number"),
                    "sheet_name": c.get("sheet_name"),
                    "cell_range": c.get("cell_range"),
                    "text_chunk_index": c.get("text_chunk_index"),
                    "section_title": c.get("section_title"),
                    "text_length": len(c["text"]),
                    "content_hash": c["content_hash"],
                }
                for c in sorted(corpus, key=lambda x: x["chunk_id"])
            ],
        },
        "baselines": {
            mode: {
                "label": all_results[mode]["label"],
                "answerable": {
                    k: v for k, v in all_results[mode]["answerable_aggregate"].items()
                    if k != "_per_query"
                },
                "no_answer": {
                    k: v for k, v in all_results[mode]["no_answer_aggregate"].items()
                    if k != "_per_query"
                },
                "by_category": cat_metrics.get(mode, {}),
                "per_query_answerable": all_results[mode]["per_query_answerable"],
                "per_query_no_answer": all_results[mode]["per_query_no_answer"],
            }
            for mode in modes
        },
        "failures": {
            "total_records": len(failures),
            "unique_query_count": len({f["query_id"] for f in failures}),
            "by_mode": {
                mode: len([f for f in failures if f["retrieval_mode"] == mode])
                for mode in modes
            },
            "by_failure_type": {
                t: len([f for f in failures if f["failure_type"] == t])
                for t in sorted({f["failure_type"] for f in failures})
            },
            "items": failures,
        },
        "toy_case_verification": verify_toy_case(),
    }


# -- Markdown 渲染 --


def _render_markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    corpus = report["corpus"]
    bl = report["baselines"]
    failures = report["failures"]
    toy = report["toy_case_verification"]

    L: list[str] = []
    L.append("# V3 检索评测基线报告")
    L.append("")
    L.append(f"> 数据集: {meta['dataset_name']} v{meta['dataset_version']}")
    L.append(f"> 评测时间: {meta['evaluated_at']}")
    L.append(f"> split: {meta['split']} | modes: {', '.join(meta['retrieval_modes'])}")
    L.append(f"> {meta['disclaimer']}")
    L.append("")

    # 元数据
    L.append("## 1. 元数据")
    L.append("")
    L.append(f"- 数据集名称: {meta['dataset_name']}")
    L.append(f"- 数据集版本: v{meta['dataset_version']}")
    L.append(f"- 查询集 SHA-256: `{meta['query_file_sha256']}`")
    L.append(f"- 语料 SHA-256: `{meta['corpus_sha256']}`")
    L.append(f"- manifest SHA-256: `{meta['manifest_sha256']}`")
    L.append(f"- tokenizer: {meta['tokenizer']} v{meta['tokenizer_version']}")
    L.append(f"- chunking: v{meta['chunking_version']}")
    L.append("")
    L.append("### 运行环境 / 可追溯信息")
    L.append("")
    L.append(f"- Python: {meta['python_version']}")
    L.append(f"- Platform: {meta.get('platform', 'N/A')}")
    L.append(f"- Git commit: `{meta['git_commit'][:8] if meta['git_commit'] else 'N/A'}`")
    L.append(f"- Git branch: {meta.get('git_branch') or 'N/A'}")
    git_dirty_label = _git_dirty_label(meta.get("git_dirty"))
    L.append(f"- Git working tree: {git_dirty_label}")
    if meta.get("git_dirty") is True:
        L.append("  > ⚠ 当前工作树存在未提交改动，报告由未提交源码生成，`git_commit` 不包含 Stage 4A 评测代码。")
    elif meta.get("git_dirty") is False:
        pass
    else:
        L.append("  > Git 不可用，无法确认工作树状态。")
    L.append(f"- Evaluation code SHA-256: `{meta.get('evaluation_code_sha256', 'N/A')}`")
    L.append(f"- Query file SHA-256: `{meta['query_file_sha256']}`")
    L.append(f"- Corpus SHA-256: `{meta['corpus_sha256']}`")
    L.append(f"- Manifest SHA-256: `{meta['manifest_sha256']}`")
    L.append("")
    # 评测源码文件清单
    eval_files = meta.get("evaluation_source_files", [])
    if eval_files:
        L.append("### 评测源码文件")
        L.append("")
        L.append("| 文件 | SHA-256 |")
        L.append("| --- | --- |")
        for ef in eval_files:
            sha = ef["sha256"][:16] + "..." if ef["sha256"] else "MISSING"
            L.append(f"| `{ef['path']}` | `{sha}` |")
        L.append("")

    # Stage 4B 扩展元数据
    if meta.get("stage") == "4b":
        L.append("### 模型与索引信息")
        L.append("")
        L.append(f"- Embedding provider: {meta.get('embedding_provider', 'N/A')}")
        L.append(f"- 模型: {meta.get('model_repo_id', 'N/A')}")
        L.append(f"- 模型 revision: `{meta.get('model_revision', 'N/A')}`")
        L.append(f"- 维度: {meta.get('model_dimension', 'N/A')}")
        L.append(f"- 归一化: {meta.get('normalize_embeddings', 'N/A')}")
        L.append(f"- Query instruction: `{meta.get('query_instruction', 'N/A')}`")
        L.append(f"- Device: {meta.get('device', 'N/A')}")
        L.append(f"- sentence-transformers: {meta.get('sentence_transformers_version', 'N/A')}")
        L.append(f"- torch: {meta.get('torch_version', 'N/A')}")
        L.append(f"- numpy: {meta.get('numpy_version', 'N/A')}")
        L.append(f"- Index SHA-256: `{meta.get('index_file_sha256', 'N/A')[:16]}...`")
        L.append(f"- Index reused: {meta.get('index_reused', False)}")
        L.append(f"- Index build time: {meta.get('dense_index_build_time_ms', 0):.0f} ms")
        L.append(f"- Index load time: {meta.get('dense_index_load_time_ms', 0):.0f} ms")
        if meta.get("rrf_k") is not None:
            L.append(f"- RRF: k={meta['rrf_k']}, sources={meta.get('fusion_sources', [])}")
        L.append("")

    # 语料
    L.append("## 2. 语料概览")
    L.append("")
    L.append(f"- 分块总数: {corpus['chunk_count']}")
    L.append("")
    L.append("| chunk_id | file_role | file_name | locator | len | content_hash |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for c in corpus["chunks"]:
        loc = c["locator_type"]
        if c["page_number"]:
            loc += f" p{c['page_number']}"
        if c["sheet_name"]:
            loc += f" [{c['sheet_name']}]"
        if c["cell_range"]:
            loc += f" {c['cell_range']}"
        if c["text_chunk_index"] is not None:
            loc += f" idx={c['text_chunk_index']}"
        L.append(
            f"| {c['chunk_id']} | {c['file_role']} | {c['file_name']} | {loc} | {c['text_length']} | `{c['content_hash'][:16]}...` |"
        )
    L.append("")

    # 查询统计
    L.append("## 3. 查询统计")
    L.append("")
    L.append(f"- 总数: {meta['query_count']} (可回答: {meta['answerable_count']}, 无答案: {meta['no_answer_count']})")
    L.append(f"- top_k: {meta['top_k']}")
    L.append("")

    # 基线对比
    L.append("## 4. 基线对比（可回答查询）")
    L.append("")
    Header = "| 指标 |"
    for mode in meta["retrieval_modes"]:
        Header += f" {bl[mode]['label']} |"
    L.append(Header)
    Sep = "| --- |"
    for _ in meta["retrieval_modes"]:
        Sep += " --- |"
    L.append(Sep)

    for key, label in [
        ("recall@3_mean", "Recall@3"),
        ("recall@5_mean", "Recall@5"),
        ("mrr_mean", "MRR"),
        ("latency_mean_ms", "延迟均值 (ms)"),
        ("latency_p50_ms", "延迟 P50 (ms)"),
        ("latency_p95_ms", "延迟 P95 (ms)"),
    ]:
        row = f"| {label} |"
        for mode in meta["retrieval_modes"]:
            v = bl[mode]["answerable"].get(key, 0)
            if "latency" in key:
                row += f" {v:.1f} |"
            else:
                row += f" {v:.4f} |"
        L.append(row)
    L.append("")

    # 无答案
    L.append("## 5. 无答案查询指标")
    L.append("")
    L.append("| 指标 |" + "|".join(f" {bl[m]['label']} " for m in meta["retrieval_modes"]) + "|")
    L.append("| --- |" + " --- |" * len(meta["retrieval_modes"]))
    for key, label in [
        ("no_answer_count", "查询数"),
        ("abstained_count", "拒绝数"),
        ("false_positive_count", "误报数"),
        ("false_positive_rate", "误报率"),
    ]:
        row = f"| {label} |"
        for mode in meta["retrieval_modes"]:
            v = bl[mode]["no_answer"].get(key, 0)
            row += f" {v:.4f} |" if isinstance(v, float) else f" {v} |"
        L.append(row)
    L.append("")
    L.append("> 当前阶段无阈值机制，所有方法对所有查询返回结果，false_positive_rate 预期为 1.0。")
    L.append("")

    # 按类别
    L.append("## 6. 按类别指标")
    L.append("")
    all_categories = sorted(set(
        cat for mode in meta["retrieval_modes"]
        for cat in bl[mode].get("by_category", {}).keys()
    ))
    if all_categories:
        for mode in meta["retrieval_modes"]:
            L.append(f"### {bl[mode]['label']}")
            L.append("")
            L.append("| category | count | Recall@3 | Recall@5 | MRR |")
            L.append("| --- | --- | --- | --- | --- |")
            by_cat = bl[mode].get("by_category", {})
            for cat in sorted(by_cat.keys()):
                c = by_cat[cat]
                L.append(
                    f"| {cat} | {c.get('answerable_count', 0)} | "
                    f"{c.get('recall@3_mean', 0):.4f} | "
                    f"{c.get('recall@5_mean', 0):.4f} | "
                    f"{c.get('mrr_mean', 0):.4f} |"
                )
            L.append("")
    else:
        L.append("*(无法生成 — 可回答查询数为 0)*")
        L.append("")

    # 失败案例
    L.append("## 7. 失败案例")
    L.append("")
    L.append(f"- 总记录: {failures['total_records']} (mode-query)")
    L.append(f"- 唯一失败 query: {failures['unique_query_count']}")
    L.append("")
    if failures["items"]:
        L.append("| query_id | split | mode | failure_type | recall@5 | mrr | retrieved |")
        L.append("| --- | --- | --- | --- | --- | --- | --- |")
        for f in failures["items"][:50]:
            retrieved = ", ".join(f["retrieved_chunk_ids"][:3])
            L.append(
                f"| {f['query_id']} | {f['split']} | {f['retrieval_mode']} | "
                f"{f['failure_type']} | {f['recall@5']:.4f} | {f['mrr']:.4f} | "
                f"{retrieved} |"
            )
        L.append("")

    # 玩具案例
    L.append("## 8. 玩具案例公式验证")
    L.append("")
    L.append(f"- Recall@3: {'[PASS]' if toy['recall@3_correct'] else '[FAIL]'} "
             f"({round(toy['recall@3'],4)} vs 期望 {toy['recall@3_expected']})")
    L.append(f"- Recall@5: {'[PASS]' if toy['recall@5_correct'] else '[FAIL]'} "
             f"({round(toy['recall@5'],4)} vs 期望 {toy['recall@5_expected']})")
    L.append(f"- MRR: {'[PASS]' if toy['mrr_correct'] else '[FAIL]'} "
             f"({round(toy['mrr'],4)} vs 期望 {toy['mrr_expected']})")
    L.append(f"- no-answer FP: {'[PASS]' if toy.get('no_answer_fp_correct') else '[FAIL]'}")
    L.append(f"- answerable/no-answer 分母互不污染: "
             f"{'[PASS]' if (toy.get('answerable_count_correct') and toy.get('no_answer_count_correct') and toy.get('no_answer_fp_rate_correct')) else '[FAIL]'}")
    L.append("")

    L.append("---")
    L.append(f"*报告生成时间: {meta['evaluated_at']}*")
    return "\n".join(L)


# -- 内部工具 --


def _corpus_sha256(corpus: list[dict[str, Any]]) -> str:
    hasher = hashlib.sha256()
    for chunk in sorted(corpus, key=lambda c: c["chunk_id"]):
        hasher.update(chunk["text"].encode("utf-8"))
    return hasher.hexdigest()


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_git_dirty() -> bool | None:
    """检查 Git 工作区是否 dirty。

    返回 True（有未提交改动），False（干净），None（Git 不可用）。
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        # 如果有任何输出（tracked 或 untracked 改动），就是 dirty
        return len(result.stdout.strip()) > 0
    except Exception:
        return None


_EVAL_SOURCE_FILES_POSIX = [
    "backend/app/evaluation/v3_corpus.py",
    "backend/app/evaluation/v3_dense_index.py",
    "backend/app/evaluation/v3_embedding.py",
    "backend/app/evaluation/v3_hybrid.py",
    "backend/app/evaluation/v3_metrics.py",
    "backend/app/evaluation/v3_query_set.py",
    "backend/app/evaluation/v3_retrieval.py",
    "backend/app/evaluation/v3_retrieval_runner.py",
    "backend/app/evaluation/v3_tokenizer.py",
]


def _get_evaluation_source_files(
    repo_root: Path,
) -> list[dict[str, str]]:
    """记录评测源码文件的路径与 SHA-256。

    返回按 path 排序的列表；缺失文件记录 sha256=""。
    """
    entries: list[dict[str, str]] = []
    for rel in sorted(_EVAL_SOURCE_FILES_POSIX):
        fpath = repo_root / rel
        if fpath.exists():
            sha = _file_sha256(fpath)
        else:
            sha = ""
        entries.append({"path": rel, "sha256": sha})
    return entries


def _eval_code_sha256(source_files: list[dict[str, str]]) -> str:
    """对 evaluation_source_files 生成确定性聚合 SHA-256。

    拼接规则：path + "\x00" + sha256 + "\n"，按 path 排序后依次拼接。
    """
    hasher = hashlib.sha256()
    for entry in source_files:
        hasher.update(entry["path"].encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(entry["sha256"].encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _find_repo_root(case_dir: Path) -> Path:
    """从 case_dir 向上查找包含 .git 的目录，返回仓库根目录。"""
    d = case_dir.resolve()
    for _ in range(10):
        if (d / ".git").exists():
            return d
        parent = d.parent
        if parent == d:
            break
        d = parent
    # 回退：假设 repo root 是当前工作目录的上级
    return Path.cwd().resolve()


def _git_dirty_label(git_dirty: bool | None) -> str:
    """将 git_dirty 值转为可读标签。"""
    if git_dirty is True:
        return "dirty"
    if git_dirty is False:
        return "clean"
    return "unavailable"


def _print_query_stats(
    queries: list[dict[str, Any]],
    all_queries: list[dict[str, Any]],
) -> None:
    ans = [q for q in queries if q.get("answerable")]
    na = [q for q in queries if not q.get("answerable")]
    dev = [q for q in queries if q["split"] == "dev"]
    test = [q for q in queries if q["split"] == "test"]

    all_ans = [q for q in all_queries if q.get("answerable")]
    all_na = [q for q in all_queries if not q.get("answerable")]
    all_dev = [q for q in all_queries if q["split"] == "dev"]
    all_test = [q for q in all_queries if q["split"] == "test"]

    print(f"\n[queries] 当前 split: {len(queries)} 条 (可回答:{len(ans)} 无答案:{len(na)} dev:{len(dev)} test:{len(test)})")
    print(f"[queries] 全量: {len(all_queries)} 条 (可回答:{len(all_ans)} 无答案:{len(all_na)} dev:{len(all_dev)} test:{len(all_test)})")


def _print_summary(
    all_results: dict[str, dict[str, Any]],
    modes: list[str],
) -> None:
    print(f"\n{'='*70}")
    print("评测对比摘要")
    print(f"{'='*70}")
    metrics_keys = [
        ("recall@3_mean", "Recall@3"),
        ("recall@5_mean", "Recall@5"),
        ("mrr_mean", "MRR"),
        ("latency_mean_ms", "延迟均值(ms)"),
        ("latency_p50_ms", "延迟P50(ms)"),
        ("latency_p95_ms", "延迟P95(ms)"),
    ]
    header = f"{'指标':<20}"
    for m in modes:
        header += f" {all_results[m]['label']:>18}"
    print(header)
    print("-" * 70)
    for key, label in metrics_keys:
        row = f"{label:<20}"
        for m in modes:
            v = all_results[m]["answerable_aggregate"].get(key, 0)
            if "latency" in key:
                row += f" {v:>18.1f}"
            else:
                row += f" {v:>18.4f}"
        print(row)


if __name__ == "__main__":
    raise SystemExit(main())
