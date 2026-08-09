"""阶段 6A：端到端评测离线测试（确定性，Fake Provider，不访问公网）。

- 数据集冻结：版本/SHA/划分断言
- 指标稳定定义：空集无 NaN、answerable/no-answer 分母隔离
- runner 集成：FakeEmbedding 下检索评测 44 条查询可运行、输出可写
- 存储隔离由 conftest 会话级 fixture 保证，默认资产不变
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.evaluation.v4_metrics as metrics_mod
from app.evaluation.v3_embedding import FakeEmbeddingProvider
from app.evaluation.v4_end_to_end_runner import (
    collect_retrieval_eval,
    freeze_engineering_review_v1,
    write_eval_outputs,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
CASE_DIR = REPO_ROOT / "examples" / "engineering_review_v1" / "golden_case"
QUERY_PATH = CASE_DIR / "retrieval_queries.json"


# ── 冻结 ────────────────────────────────────────────────────────────


def test_freeze_dataset_version_and_shas() -> None:
    freeze = freeze_engineering_review_v1(CASE_DIR, REPO_ROOT)
    assert freeze["dataset_name"] == "engineering-review-v1"
    assert freeze["dataset_version"] == "1.1.0"
    assert freeze["case_id"] == "SYN-ENG-2026-001"
    # 五份黄金材料
    for name in ("01_合成招标要求.pdf", "02_合成投标响应.pdf", "03_人员设备清单.xlsx",
                 "04_合成资质附件.pdf", "05_项目澄清.md"):
        entry = freeze["files"].get(name)
        assert entry and entry["sha256"] and len(entry["sha256"]) == 64, name
    # 数据文件
    for name in ("manifest.json", "ground_truth.json", "retrieval_queries.json", "review_brief.json"):
        entry = freeze.get(name)
        assert entry and entry["sha256"] and len(entry["sha256"]) == 64, name
    # 规则包
    assert freeze["rule_pack"]["sha256"] and len(freeze["rule_pack"]["sha256"]) == 64
    # 评测源码
    assert freeze["evaluation_code_sha256"] and len(freeze["evaluation_code_sha256"]) == 64
    assert freeze["evaluation_source_files"]


def test_freeze_splits_match_query_set() -> None:
    freeze = freeze_engineering_review_v1(CASE_DIR, REPO_ROOT)
    # 阶段 6A 冻结层契约：原 test 16 不变；原 dev 28 拆为 development 20 + validation 8
    assert freeze["splits"]["development"] == 20
    assert freeze["splits"]["validation"] == 8
    assert freeze["splits"]["test"] == 16
    assert freeze["total_queries"] == 44
    assert freeze["answerable_queries"] == 38
    assert freeze["no_answer_queries"] == 6
    assert freeze["evaluation_split_version"] == "1.0.0"
    # source dataset_version 仍为 1.1.0，不伪造查询集版本
    assert freeze["dataset_version"] == "1.1.0"


def test_freeze_split_mapping_lists_and_sha() -> None:
    freeze = freeze_engineering_review_v1(CASE_DIR, REPO_ROOT)
    sm = freeze["split_mapping"]
    assert sm["file_name"] == "split_mapping.json"
    assert len(sm["sha256"]) == 64
    assert len(sm["development_query_ids"]) == 20
    assert len(sm["validation_query_ids"]) == 8
    assert len(sm["test_query_ids"]) == 16
    # 三集合互斥且并集 = 全部 44 条
    all_ids = set(sm["development_query_ids"]) | set(sm["validation_query_ids"]) | set(sm["test_query_ids"])
    assert len(all_ids) == 44
    assert len(set(sm["development_query_ids"]) & set(sm["validation_query_ids"])) == 0
    # 与查询集原始 split 一致：test 名单与文件标注完全一致
    queries_raw = json.loads(QUERY_PATH.read_text(encoding="utf-8"))["queries"]
    file_test = sorted(q["query_id"] for q in queries_raw if q["split"] == "test")
    assert sm["test_query_ids"] == file_test


def test_split_mapping_deterministic_and_stratified() -> None:
    """同一输入重复生成必须逐字节一致；分层数量符合契约。"""
    from app.evaluation.v4_end_to_end_runner import (
        compute_evaluation_split_mapping,
        split_mapping_document,
    )

    queries_raw = json.loads(QUERY_PATH.read_text(encoding="utf-8"))["queries"]
    m1 = compute_evaluation_split_mapping(queries_raw)
    m2 = compute_evaluation_split_mapping(queries_raw)
    assert m1 == m2
    assert split_mapping_document(m1) == split_mapping_document(m2)
    dev_ids = [qid for qid in m1 if m1[qid] == "development"]
    val_ids = [qid for qid in m1 if m1[qid] == "validation"]
    assert len(dev_ids) == 20 and len(val_ids) == 8
    ans_dev = sum(1 for q in queries_raw if m1[q["query_id"]] == "development" and q["answerable"])
    no_dev = sum(1 for q in queries_raw if m1[q["query_id"]] == "development" and not q["answerable"])
    ans_val = sum(1 for q in queries_raw if m1[q["query_id"]] == "validation" and q["answerable"])
    no_val = sum(1 for q in queries_raw if m1[q["query_id"]] == "validation" and not q["answerable"])
    assert ans_dev == 18 and no_dev == 2
    assert ans_val == 7 and no_val == 1
    # 精确 query_id 清单（与冻结文件一致，防止漂移）
    assert val_ids == ["Q012", "Q014", "Q016", "Q018", "Q020", "Q021", "Q022", "Q039"]


def test_freeze_git_meta_present() -> None:
    freeze = freeze_engineering_review_v1(CASE_DIR, REPO_ROOT)
    assert freeze["git_commit"] and len(freeze["git_commit"]) == 40
    assert freeze["git_branch"]
    assert isinstance(freeze["git_dirty"], bool)
    assert freeze["python_version"]


def test_freeze_does_not_mutate_dataset() -> None:
    """冻结不得修改任何数据集文件（只读 SHA 计算）。"""
    before = {p.name: p.read_bytes() for p in CASE_DIR.iterdir() if p.is_file()}
    freeze_engineering_review_v1(CASE_DIR, REPO_ROOT)
    after = {p.name: p.read_bytes() for p in CASE_DIR.iterdir() if p.is_file()}
    assert before == after


# ── 指标稳定定义 ────────────────────────────────────────────────────


def test_metrics_empty_sets_no_nan() -> None:
    # 空列表聚合 → None + empty 标记，绝不 NaN
    assert metrics_mod.latency_summary([]) == {
        "count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None}
    assert metrics_mod.aggregate_classification([])["precision"] is None
    assert metrics_mod.match_accuracy([])["accuracy"] is None
    agg = metrics_mod.aggregate_retrieval([], [])
    assert agg["answerable"]["recall@3_mean"] is None
    assert agg["no_answer"]["false_positive_rate"] is None
    for obj in (agg, metrics_mod.safe_summary("dev", {"x": None})):
        text = json.dumps(obj, ensure_ascii=False)
        assert "NaN" not in text and math.isnan(0.0) is False


def test_metrics_answerable_no_answer_denominator_isolated() -> None:
    per_a = [
        {"query_id": "Q1", "latency_ms": 1.0, "recall@3": 1.0, "recall@5": 1.0, "mrr": 0.5},
        {"query_id": "Q2", "latency_ms": 2.0, "recall@3": 0.0, "recall@5": 0.5, "mrr": 0.25},
    ]
    per_n = [{"query_id": "Q3", "false_positive": True}]
    agg = metrics_mod.aggregate_retrieval(per_a, per_n)
    assert agg["answerable"]["answerable_count"] == 2
    assert agg["answerable"]["recall@3_mean"] == 0.5
    assert agg["no_answer"]["no_answer_count"] == 1
    assert agg["no_answer"]["false_positive_rate"] == 1.0
    # no-answer 不进入 answerable 分母
    assert agg["answerable"]["recall@5_mean"] == 0.75


def test_classification_metrics_edge_cases() -> None:
    # 空预期 + 空实际 → 1.0/1.0/1.0
    assert metrics_mod.classification_metrics([], [])["f1"] == 1.0
    # 空预期 + 非空实际 → P=0
    assert metrics_mod.classification_metrics([], ["X"])["precision"] == 0.0
    # 正常
    m = metrics_mod.classification_metrics(["A", "B"], ["A", "C"])
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["f1"] == 0.5


def test_recall_mrr_stable_definitions() -> None:
    assert metrics_mod.recall_at_k(["C1"], [], 3) == 1.0
    assert metrics_mod.mrr(["C1"], []) == 1.0
    assert metrics_mod.mrr(["C9"], ["C1"]) == 0.0
    assert abs(metrics_mod.recall_at_k(["C1", "C2"], ["C1", "C2", "C3"], 5) - 2 / 3) < 1e-3


# ── runner 集成（FakeEmbedding，离线）──────────────────────────────


def test_retrieval_eval_runs_full_query_set_offline(tmp_path) -> None:
    """FakeEmbedding 下 44 条查询全部可执行，answerable/no-answer 隔离。"""
    fake = FakeEmbeddingProvider(dimension=512, seed=42)
    result = collect_retrieval_eval(
        CASE_DIR, QUERY_PATH,
        encode_query=lambda texts: fake.encode_passages(texts),
        top_k=5,
    )
    assert len(result.per_query_answerable) == 38
    assert len(result.per_query_no_answer) == 6
    for q in result.per_query_answerable:
        assert 0.0 <= q["recall@3"] <= 1.0
        assert 0.0 <= q["recall@5"] <= 1.0
        assert 0.0 <= q["mrr"] <= 1.0
        assert q["latency_ms"] >= 0
    for q in result.per_query_no_answer:
        assert "false_positive" in q


def test_validation_split_metrics_not_empty() -> None:
    """validation 指标不得为空：按冻结 mapping 切出的 8 条必须有真实聚合。"""
    from app.evaluation.v4_end_to_end_runner import (
        compute_evaluation_split_mapping,
        split_mapping_document,
    )
    from app.evaluation.v4_metrics import aggregate_retrieval

    fake = FakeEmbeddingProvider(dimension=512, seed=42)
    result = collect_retrieval_eval(
        CASE_DIR, QUERY_PATH,
        encode_query=lambda texts: fake.encode_passages(texts),
        top_k=5,
    )
    queries_raw = json.loads(QUERY_PATH.read_text(encoding="utf-8"))["queries"]
    mapping = compute_evaluation_split_mapping(queries_raw)
    assert split_mapping_document(mapping)  # 确定性文档可生成

    per_a = [q for q in result.per_query_answerable if mapping.get(q["query_id"]) == "validation"]
    per_n = [q for q in result.per_query_no_answer if mapping.get(q["query_id"]) == "validation"]
    assert len(per_a) == 7 and len(per_n) == 1
    agg = aggregate_retrieval(per_a, per_n)
    assert agg["answerable"]["answerable_count"] == 7
    assert agg["answerable"]["recall@3_mean"] is not None
    assert agg["answerable"]["recall@5_mean"] is not None
    assert agg["answerable"]["mrr_mean"] is not None
    assert agg["no_answer"]["no_answer_count"] == 1
    assert agg["no_answer"]["false_positive_rate"] is not None
    assert not agg.get("empty")
    # development 也必须有真实聚合
    dev_a = [q for q in result.per_query_answerable if mapping.get(q["query_id"]) == "development"]
    dev_n = [q for q in result.per_query_no_answer if mapping.get(q["query_id"]) == "development"]
    assert len(dev_a) == 18 and len(dev_n) == 2
    dev_agg = aggregate_retrieval(dev_a, dev_n)
    assert dev_agg["answerable"]["answerable_count"] == 18
    assert dev_agg["answerable"]["recall@3_mean"] is not None
    assert dev_agg["no_answer"]["no_answer_count"] == 2


def test_write_eval_outputs_creates_three_files(tmp_path) -> None:
    out_dir = tmp_path / "stage6a" / "dev"
    meta = {"dataset_name": "engineering-review-v1", "dataset_version": "1.1.0",
            "case_id": "SYN-ENG-2026-001", "git_commit": "a" * 40, "git_branch": "codex/stage-6a",
            "git_dirty": False, "python_version": "3", "platform": "x", "evaluated_at": "now",
            "files": {"01.pdf": {"sha256": "b" * 64}}, "rule_pack": {"sha256": "c" * 64},
            "evaluation_code_sha256": "d" * 64}
    metrics = {"retrieval": {"answerable": {"recall@3_mean": 0.5}}}
    failures = [{"failure_type": "RETRIEVAL_MISS", "manual_failure_category": "RECALL",
                 "item_id": "Q001", "detail": "top5 未覆盖相关块"}]
    summary = write_eval_outputs(out_dir, meta=meta, metrics=metrics, failures=failures)
    assert (out_dir / "evaluation_report.json").is_file()
    assert (out_dir / "evaluation_report.md").is_file()
    assert (out_dir / "failures.json").is_file()
    data = json.loads((out_dir / "evaluation_report.json").read_text(encoding="utf-8"))
    assert data["metrics"]["retrieval"]["answerable"]["recall@3_mean"] == 0.5
    assert data["failures_count"] == 1
    assert summary["report_sha256"] and len(summary["report_sha256"]) == 64


def test_ground_truth_contract_untouched() -> None:
    """数据集契约断言：禁止修改 ground truth 的预期（防漂移）。"""
    gt = json.loads((CASE_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    assert len(gt["expected_findings"]) == 12
    assert len(gt["expected_fields"]) == 13
    assert gt["expected_passed_rules"] == ["SYN-DOC-001", "SYN-DOC-002"]
    assert gt["rule_pack_version"] == "1.1.0"
