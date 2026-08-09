"""Stage 6A 端到端评测 runner：数据冻结 + 检索/抽取/问题/引用/Supervisor 指标收集。

- freeze_engineering_review_v1()：冻结数据集版本、划分与全部 SHA-256
- collect_retrieval_eval()：复用 4A/4B 检索管线（v3_corpus/v3_retrieval），
  由调用方注入 embedding 编码函数（真实 BGE 或 Fake）
- collect_supervisor_eval()：复用 pipeline._extract_all_fields 与 Supervisor 结果，
  计算抽取/问题识别/引用定位/content_hash/无证据结论率等
- write_eval_outputs()：输出 JSON + Markdown + failures

不复制业务算法；不修改 ground truth / relevant ids / Finding 预期 / 黄金材料。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.evaluation.v3_corpus import build_corpus
from app.evaluation.v3_query_set import load_query_set
from app.evaluation.v3_retrieval import bm25_retrieve, make_dense_retriever
from app.evaluation.v3_hybrid import hybrid_rrf_retrieve, RRF_K
from app.evaluation.v4_metrics import (
    aggregate_classification,
    aggregate_retrieval,
    classification_metrics,
    latency_summary,
    match_accuracy,
    mrr,
    recall_at_k,
)

DATASET_VERSION = "1.1.0"
# 阶段 6A 冻结层新增的独立划分版本：原 dev 28 条确定性、分层拆为
# development=20 + validation=8；test 16 条完全不变。
EVALUATION_SPLIT_VERSION = "1.0.0"
SPLIT_MAPPING_FILE_NAME = "split_mapping.json"
EVAL_CODE_FILES = (
    "backend/app/evaluation/v4_metrics.py",
    "backend/app/evaluation/v4_end_to_end_runner.py",
    "backend/tests/test_v6a_end_to_end_evaluation.py",
    "scripts/verify_stage6a_real_evaluation.py",
)
GOLDEN_FILES = (
    "01_合成招标要求.pdf",
    "02_合成投标响应.pdf",
    "03_人员设备清单.xlsx",
    "04_合成资质附件.pdf",
    "05_项目澄清.md",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git_meta(repo_root: Path) -> dict[str, Any]:
    def _run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    status = _run("status", "--porcelain")
    return {
        "git_commit": _run("rev-parse", "HEAD"),
        "git_branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(status),
    }


def _platform_meta() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── evaluation split 映射（阶段 6A 冻结层）──────────────────────────


def compute_evaluation_split_mapping(queries: list[dict[str, Any]]) -> dict[str, str]:
    """把原始 dev 28 条确定性、分层拆为 development=20 / validation=8。

    纯函数：同一输入必然产生逐字节一致的映射（query_id → split）。

    分层规则（按 category 与 answerable 状态尽量分层）：
    - 原 split=test 的 16 条完全不变 → test；
    - dev answerable：单查询类别（numeric、cross_file）整类进入 validation；
      双查询类别（personnel、equipment、qualification、clarification）与
      clause_ref（三查询）取 query_id 最大的一条进入 validation；
      其余大类别（tender_spec、bid_info）全部留在 development；
    - dev no-answer：取 query_id 最小的一条进入 validation，其余留在 development。
    """
    by_qid = {q["query_id"]: q for q in queries}
    qids = sorted(by_qid)
    mapping: dict[str, str] = {}
    answerable_by_category: dict[str, list[str]] = {}
    no_answer_ids: list[str] = []
    for qid in qids:
        q = by_qid[qid]
        if q.get("split") == "test":
            mapping[qid] = "test"
            continue
        mapping[qid] = "development"
        if q.get("answerable"):
            answerable_by_category.setdefault(str(q.get("category", "")), []).append(qid)
        else:
            no_answer_ids.append(qid)

    validation_answerable: set[str] = set()
    for cat_ids in answerable_by_category.values():
        if len(cat_ids) <= 1:
            validation_answerable.update(cat_ids)
        elif len(cat_ids) <= 3:
            validation_answerable.add(cat_ids[-1])
        # 更大型类别（>3 条）全部留在 development
    for qid in validation_answerable:
        mapping[qid] = "validation"
    if no_answer_ids:
        mapping[no_answer_ids[0]] = "validation"
    return mapping


def split_mapping_document(mapping: dict[str, str]) -> str:
    """映射文件的规范序列化（固定参数，重复生成逐字节一致）。"""
    doc: dict[str, Any] = {
        "evaluation_split_version": EVALUATION_SPLIT_VERSION,
        "source_dataset_version": DATASET_VERSION,
        "mapping": dict(sorted(mapping.items())),
        "query_id_lists": {
            split: [qid for qid in sorted(mapping) if mapping[qid] == split]
            for split in ("development", "validation", "test")
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def freeze_engineering_review_v1(
    case_dir: Path,
    repo_root: Path,
    *,
    code_files: tuple[str, ...] = EVAL_CODE_FILES,
) -> dict[str, Any]:
    """冻结 engineering-review-v1：材料/查询集/ground truth/brief/规则包/源码 SHA。"""
    freeze: dict[str, Any] = {
        "dataset_name": "engineering-review-v1",
        "dataset_version": DATASET_VERSION,
        "case_id": "SYN-ENG-2026-001",
        "files": {},
    }
    for name in GOLDEN_FILES:
        p = case_dir / name
        freeze["files"][name] = {
            "sha256": _sha256_file(p) if p.exists() else None,
            "size_bytes": p.stat().st_size if p.exists() else None,
        }
    for name in ("manifest.json", "ground_truth.json", "retrieval_queries.json",
                 "review_brief.json", "README.md"):
        p = case_dir / name
        freeze[name] = {"sha256": _sha256_file(p) if p.exists() else None,
                        "size_bytes": p.stat().st_size if p.exists() else None}
    # 规则包（运行时真源）
    rule_yaml = repo_root / "backend/app/review_rules/engineering_bid_review_v1.yaml"
    freeze["rule_pack"] = {
        "path": "backend/app/review_rules/engineering_bid_review_v1.yaml",
        "sha256": _sha256_file(rule_yaml) if rule_yaml.exists() else None,
    }
    # 划分：原 test 16 条不变；原 dev 28 条由冻结层 mapping 拆为
    # development=20 + validation=8（evaluation_split_version 独立于数据集版本）。
    queries, _qsha, _raw = load_query_set(case_dir / "retrieval_queries.json")
    mapping = compute_evaluation_split_mapping(queries)
    mapping_doc = split_mapping_document(mapping)
    mapping_sha256 = _sha256_bytes(mapping_doc.encode("utf-8"))
    splits = {"development": 0, "validation": 0, "test": 0}
    for qid in sorted(mapping):
        splits[mapping[qid]] = splits.get(mapping[qid], 0) + 1
    freeze["evaluation_split_version"] = EVALUATION_SPLIT_VERSION
    freeze["splits"] = splits
    freeze["split_mapping"] = {
        "file_name": SPLIT_MAPPING_FILE_NAME,
        "sha256": mapping_sha256,
        "development_query_ids": sorted(qid for qid in mapping if mapping[qid] == "development"),
        "validation_query_ids": sorted(qid for qid in mapping if mapping[qid] == "validation"),
        "test_query_ids": sorted(qid for qid in mapping if mapping[qid] == "test"),
    }
    freeze["total_queries"] = len(queries)
    freeze["answerable_queries"] = sum(1 for q in queries if q.get("answerable"))
    freeze["no_answer_queries"] = sum(1 for q in queries if not q.get("answerable"))
    # 评测源码
    freeze["evaluation_source_files"] = []
    combined = []
    for rel in code_files:
        p = repo_root / rel
        if not p.exists():
            continue
        digest = _sha256_file(p)
        freeze["evaluation_source_files"].append({"path": rel, "sha256": digest})
        combined.append(f"{rel}\t{digest}")
    freeze["evaluation_code_sha256"] = _sha256_bytes(
        "\n".join(sorted(combined)).encode("utf-8"))
    freeze.update(_git_meta(repo_root))
    freeze.update(_platform_meta())
    return freeze


# ── 检索评测（复用 4A/4B 管线）────────────────────────────────────


@dataclass
class RetrievalEvalResult:
    per_query_answerable: list[dict[str, Any]] = field(default_factory=list)
    per_query_no_answer: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def collect_retrieval_eval(
    case_dir: Path,
    query_path: Path,
    *,
    encode_query: Callable[[str], Any],
    top_k: int = 5,
    rrf_k: int = RRF_K,
) -> RetrievalEvalResult:
    """执行混合检索评测（真实或 Fake embedding 由 encode_query 决定）。

    返回每条查询的 recall@3/recall@5/mrr（answerable）与
    false_positive 判定（no-answer：top1 结果非空即视为误报）。
    """
    corpus = build_corpus(case_dir)
    queries, _qsha, _raw = load_query_set(query_path)
    corpus_embeddings = encode_query([c["text"] for c in corpus])
    # dense retriever 按 4B 契约构建（encode_query_fn 返回单条查询向量）
    dense_fn = make_dense_retriever(
        corpus_embeddings,
        encode_query_fn=lambda q_text: encode_query([q_text])[0],
    )

    def _hybrid(q_text: str) -> list[dict[str, Any]]:
        return hybrid_rrf_retrieve(
            q_text, corpus, top_k=top_k,
            bm25_retrieve_fn=bm25_retrieve, dense_retrieve_fn=dense_fn,
            rrf_k=rrf_k,
        )

    result = RetrievalEvalResult()
    for q in queries:
        qid = q["query_id"]
        relevant = q.get("relevant_chunk_ids", [])
        t0 = datetime.now()
        hits = _hybrid(q["query_text"])
        latency_ms = (datetime.now() - t0).total_seconds() * 1000
        retrieved_ids = [h["chunk_id"] for h in hits]
        if q.get("answerable"):
            result.per_query_answerable.append({
                "query_id": qid, "latency_ms": round(latency_ms, 2),
                "recall@3": recall_at_k(retrieved_ids, relevant, 3),
                "recall@5": recall_at_k(retrieved_ids, relevant, 5),
                "mrr": mrr(retrieved_ids, relevant),
                "relevant_count": len(relevant),
                "retrieved_count": len(retrieved_ids),
            })
        else:
            result.per_query_no_answer.append({
                "query_id": qid, "latency_ms": round(latency_ms, 2),
                "false_positive": bool(retrieved_ids),
                "retrieved_count": len(retrieved_ids),
            })
    result.meta = {"top_k": top_k, "rrf_k": rrf_k, "query_count": len(queries)}
    return result


# ── Supervisor / 抽取 / 问题识别 / 引用评测 ─────────────────────────


@dataclass
class SupervisorEvalResult:
    status: str
    current_step: str | None
    steps: list[dict[str, Any]]
    quality_gate: dict[str, Any]
    report_id: int | None
    report_assets: list[dict[str, Any]]
    verification_run_id: int | None
    retry_count: int
    supervisor_latency_ms: int | None
    meta: dict[str, Any] = field(default_factory=dict)


def extract_fields_from_files(db: Session, workspace_id: int, owner_user_id: int) -> dict[str, Any]:
    """复用 pipeline 的真实抽取算法（不复制业务逻辑）。"""
    from app.services.engineering_review_pipeline_service import (
        _extract_all_fields,
        _validate_materials,
    )

    files_by_role = _validate_materials(db, workspace_id, owner_user_id)
    extraction = _extract_all_fields(files_by_role)
    return {key: item.value for key, item in extraction.fields.items()}


def collect_supervisor_eval(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    supervisor_result: dict[str, Any],
    extracted_fields: dict[str, Any],
    expected: dict[str, Any],
    findings: list[Any],
    evidences: list[Any],
    reports: list[Any],
    report_assets: list[Any],
) -> dict[str, Any]:
    """由一次真实 Supervisor 运行计算全部业务指标（各 split 共享同一逻辑）。"""
    expected_findings = expected.get("expected_findings", [])
    expected_fields = expected.get("expected_fields", {})

    # 字段抽取 P/R/F1
    expected_keys = list(expected_fields.keys())
    actual_keys = [k for k, v in extracted_fields.items() if v is not None and v != ""]
    # 空值字段（""）视为"期望缺失"，命中 = 期望值为空且抽取也为空
    field_hits = []
    for key in expected_keys:
        expected_value = expected_fields[key]
        actual_value = extracted_fields.get(key)
        ok = (expected_value == "" and (actual_value is None or actual_value == "")) or (
            expected_value != "" and actual_value == expected_value)
        field_hits.append(ok)
    field_accuracy = match_accuracy(field_hits)
    field_class = classification_metrics(
        expected_keys, [k for k in actual_keys if k in expected_keys])
    field_class.update({"matched": field_accuracy["correct"],
                        "expected_count": len(expected_keys)})

    # 问题识别 P/R/F1（按 issue_code 匹配）
    actual_issue_codes = [f.issue_code for f in findings]
    expected_issue_codes = [f["issue_code"] for f in expected_findings]
    issue_class = classification_metrics(expected_issue_codes, actual_issue_codes)

    # 引用定位正确率：预期 evidence_locator 与证据 locator 规范化比较
    # （pdf_page:N、spreadsheet_cell:sheet!range、text_chunk:index）
    evidence_locs = {
        e.id: f"{e.locator_type}:{e.page_number or e.sheet_name or e.chunk_id}"
        for e in evidences
    }
    finding_evidence = {}
    for f in findings:
        ids = _parse_ids(f.evidence_ids_json)
        finding_evidence[f.issue_code] = [evidence_locs.get(eid) for eid in ids if eid in evidence_locs]

    def _norm_locator(raw: str) -> str:
        raw = (raw or "").strip()
        # 去除备注（括号内说明，如 "pdf_page:2 (扫描图片无文本层)"）
        raw = raw.split(" (", 1)[0].strip()
        if raw.startswith("pdf_page:"):
            return f"pdf_page:{raw.split(':', 1)[1]}"
        if raw.startswith("spreadsheet_cell:"):
            return f"spreadsheet_cell:{raw.split(':', 1)[1]}"
        if raw.startswith("text_chunk:"):
            return f"text_chunk:{raw.split(':', 1)[1]}"
        return raw

    locator_hits = []
    for f in expected_findings:
        raw_expected = f.get("evidence_locator", "") or ""
        # 复合 locator（"pdf_page:1 + spreadsheet_cell:人员清单!B3"）拆分为候选集合
        expected_segments = [
            _norm_locator(seg) for seg in raw_expected.split("+")
            if _norm_locator(seg)
        ]
        if not expected_segments:
            continue
        actual_locs = finding_evidence.get(f["issue_code"], [])
        locator_hits.append(
            any(_norm_locator(a) in expected_segments for a in actual_locs))
    locator_acc = match_accuracy(locator_hits)

    # content_hash 正确率：evidence.content_hash 可由其自身元数据稳定复算
    # （pipeline 证据哈希语义为元数据 JSON 哈希，评测复算一致性而非文件全文）
    from app.services.review_engine_service import _compute_evidence_hash

    hash_hits = []
    for e in evidences:
        # 与 create_evidence 完全一致的哈希输入（7 字段，见 review_action_service）
        evidence_data = {
            "file_id": e.file_id, "locator_type": e.locator_type,
            "page_number": e.page_number, "sheet_name": e.sheet_name,
            "cell_range": e.cell_range, "chunk_id": e.chunk_id,
            "quote": e.quote,
        }
        hash_hits.append(_compute_evidence_hash(evidence_data) == e.content_hash)
    hash_acc = match_accuracy(hash_hits)

    # 无证据结论率（Finding 无 evidence_id 的比例）
    findings_with_evidence = sum(1 for f in findings if _parse_ids(f.evidence_ids_json))
    no_evidence_rate = (1.0 - findings_with_evidence / len(findings)) if findings else None

    # Quality Gate
    gate = supervisor_result.get("quality_gate") or {}
    gate_status = gate.get("status")

    # Supervisor 完成率 / needs_human
    status = supervisor_result.get("status")
    steps = supervisor_result.get("steps", [])
    step_success = all(s.get("status") == "success" for s in steps)
    retry_chain = [s for s in steps if s.get("retry_of_id")]

    # 报告双资产
    asset_types = {a.asset_type for a in report_assets}
    report_ok = bool(report_assets) and {"markdown", "pdf"}.issubset(asset_types)

    return {
        "supervisor": {
            "status": status,
            "completed": status in ("completed", "completed_with_warnings", "ready_to_report"),
            "needs_human": status in ("needs_human", "failed"),
            "current_step": supervisor_result.get("current_step"),
            "step_success": step_success,
            "step_count": len(steps),
            "retry_count": supervisor_result.get("retry_count", 0),
            "retry_chain_count": len(retry_chain),
            "verification_run_id": supervisor_result.get("verification_run_id"),
            "latency_ms": supervisor_result.get("latency_ms"),
        },
        "quality_gate": {
            "status": gate_status,
            "passed": gate_status == "passed",
            "errors": gate.get("errors", []),
            "check_count": len(gate.get("checks", [])),
        },
        "field_extraction": {
            **field_class,
            "accuracy": field_accuracy.get("accuracy"),
            "matched": field_accuracy["correct"],
        },
        "issue_identification": issue_class,
        "citation_locator": locator_acc,
        "content_hash": hash_acc,
        "no_evidence_rate": no_evidence_rate,
        "report": {
            "report_id": supervisor_result.get("report_id"),
            "generated": report_ok,
            "asset_types": sorted(asset_types),
            "assets_count": len(report_assets),
        },
    }


def _parse_ids(raw: str) -> list[int]:
    try:
        data = json.loads(raw or "[]")
        return [int(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


# ── 输出 ────────────────────────────────────────────────────────────


def write_eval_outputs(
    out_dir: Path,
    *,
    meta: dict[str, Any],
    metrics: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """写 evaluation_report.json / .md / failures.json；返回汇总。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"meta": meta, "metrics": metrics, "failures_count": len(failures)}
    (out_dir / "evaluation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=1), encoding="utf-8")
    md = _render_markdown(meta, metrics, failures)
    (out_dir / "evaluation_report.md").write_text(md, encoding="utf-8")
    return {"dir": str(out_dir), "report_sha256": _sha256_file(out_dir / "evaluation_report.json")}


def _render_markdown(meta: dict[str, Any], metrics: dict[str, Any],
                     failures: list[dict[str, Any]]) -> str:
    lines = [
        "# Stage 6A 端到端评测报告",
        "",
        f"- dataset: {meta.get('dataset_name')} v{meta.get('dataset_version')}",
        f"- case: {meta.get('case_id')}",
        f"- commit: {meta.get('git_commit', '')} ({meta.get('git_branch', '')}, dirty={meta.get('git_dirty')})",
        f"- python: {meta.get('python_version')} / {meta.get('platform', '')}",
        f"- evaluated_at: {meta.get('evaluated_at', '')}",
        "",
        "## 冻结 SHA",
        "",
        "| 对象 | SHA-256 |",
        "| --- | --- |",
    ]
    for name, entry in (meta.get("files") or {}).items():
        lines.append(f"| {name} | `{entry.get('sha256')}` |")
    for name in ("manifest.json", "ground_truth.json", "retrieval_queries.json", "review_brief.json"):
        entry = meta.get(name) or {}
        lines.append(f"| {name} | `{entry.get('sha256')}` |")
    lines.append(f"| rule_pack | `{(meta.get('rule_pack') or {}).get('sha256')}` |")
    lines.append(f"| evaluation_code | `{meta.get('evaluation_code_sha256')}` |")
    lines.append("")
    lines.append("## 指标")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(metrics, ensure_ascii=False, indent=1))
    lines.append("```")
    lines.append("")
    lines.append(f"## 失败案例（{len(failures)}）")
    lines.append("")
    for f in failures[:50]:
        lines.append(f"- **{f.get('failure_type')}** ({f.get('manual_failure_category')}) "
                     f"{f.get('item_id', '')}: {f.get('detail', '')}")
    if len(failures) > 50:
        lines.append(f"- … 其余 {len(failures) - 50} 条见 failures.json")
    return "\n".join(lines)
