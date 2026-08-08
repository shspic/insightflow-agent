from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_action import ReviewAction
from app.models.review_finding import ReviewFinding
from app.models.review_report import ReviewReport
from app.models.review_report_asset import ReviewReportAsset
from app.models.review_run import ReviewRun
from app.models.workspace_file import WorkspaceFile


GENERATOR_NAME = "engineering_review_report"
GENERATOR_VERSION = "1.0.0"
REPORT_DECLARATION = (
    "当前工程审查规则包为合成演示规则，仅用于功能演示和技术验证，"
    "不作为真实招投标、工程、资质或法律判断依据。"
    "如使用项目附带的 golden_case，相关材料也属于合成演示数据；"
    "用户自行上传材料的真实性、完整性和适用性仍须由专业人员确认。"
    "本报告仅用于辅助审查、风险提示和证据定位，"
    "不构成自动合规判断或投标有效性认定，最终由专业人员确认。"
)

SEVERITY_LABELS = {"high": "高风险", "medium": "中风险", "low": "低风险"}
STATUS_LABELS = {
    "pending_review": "待复核",
    "confirmed": "已确认",
    "rejected": "已驳回",
    "modified": "已修改",
    "resolved": "已解决",
}
ACTION_LABELS = {
    "confirm": "确认",
    "reject": "驳回",
    "modify": "修改",
    "resolve": "解决",
}


class ReviewReportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_json_bytes(value: Any) -> bytes:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR",
            f"报告快照无法规范化序列化：{exc}",
        ) from exc
    return serialized.encode("utf-8")


def review_state_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()


def generate_review_report(
    db: Session,
    *,
    run: ReviewRun,
    workspace_id: int,
    owner_user_id: int,
) -> tuple[ReviewReport, bool]:
    if run.status != "completed":
        raise ReviewReportError(
            "REVIEW_REPORT_RUN_NOT_COMPLETED",
            "ReviewRun 尚未完成，不能生成工程审查报告",
        )

    snapshot, quality_gate, statistics = _build_review_snapshot(
        db,
        run=run,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
    )
    state_hash = review_state_hash(snapshot)
    existing = db.scalar(
        select(ReviewReport).where(
            ReviewReport.review_run_id == run.id,
            ReviewReport.workspace_id == workspace_id,
            ReviewReport.owner_user_id == owner_user_id,
            ReviewReport.review_state_hash == state_hash,
        )
    )
    if existing is not None:
        return existing, True

    latest_version = db.scalar(
        select(func.max(ReviewReport.version)).where(
            ReviewReport.review_run_id == run.id,
            ReviewReport.workspace_id == workspace_id,
            ReviewReport.owner_user_id == owner_user_id,
        )
    )
    version = int(latest_version or 0) + 1
    status = "ready_with_warnings" if quality_gate["warnings"] else "ready"
    report = ReviewReport(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        review_run_id=run.id,
        version=version,
        status=status,
        review_state_hash=state_hash,
        review_snapshot_json=canonical_json_bytes(snapshot).decode("utf-8"),
        quality_gate_json=canonical_json_bytes(quality_gate).decode("utf-8"),
        warning_count=len(quality_gate["warnings"]),
        finding_count=statistics["finding_count"],
        high_count=statistics["high_count"],
        medium_count=statistics["medium_count"],
        low_count=statistics["low_count"],
        confirmed_count=statistics["confirmed_count"],
        rejected_count=statistics["rejected_count"],
        modified_count=statistics["modified_count"],
        resolved_count=statistics["resolved_count"],
        pending_review_count=statistics["pending_review_count"],
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
    )

    written_paths: list[Path] = []
    temporary_paths: list[Path] = []
    try:
        db.add(report)
        db.flush()
        markdown = render_review_report_markdown(report, snapshot, quality_gate)
        for asset_type, suffix, mime_type in (
            ("markdown", "md", "text/markdown; charset=utf-8"),
            ("pdf", "pdf", "application/pdf"),
        ):
            storage_path = _asset_storage_path(report, suffix)
            destination = _resolve_storage_path(storage_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f"{destination.name}.tmp")
            temporary_paths.append(temporary)
            if asset_type == "markdown":
                temporary.write_bytes(markdown.encode("utf-8"))
            else:
                _write_pdf(report, markdown, temporary)
            temporary.replace(destination)
            written_paths.append(destination)
            asset = ReviewReportAsset(
                review_report_id=report.id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                asset_type=asset_type,
                file_name=_asset_file_name(report, suffix),
                storage_path=storage_path,
                mime_type=mime_type,
                size_bytes=destination.stat().st_size,
                content_hash=_file_hash(destination),
            )
            db.add(asset)
        db.commit()
        db.refresh(report)
        return report, False
    except ReviewReportError:
        db.rollback()
        _remove_written_files(written_paths + temporary_paths)
        raise
    except Exception as exc:
        db.rollback()
        _remove_written_files(written_paths + temporary_paths)
        raise ReviewReportError(
            "REVIEW_REPORT_GENERATION_ERROR", f"工程审查报告资产生成失败：{exc}"
        ) from exc


def list_owned_review_reports(
    db: Session, *, workspace_id: int, run_id: int, owner_user_id: int
) -> list[ReviewReport]:
    return list(
        db.scalars(
            select(ReviewReport)
            .where(
                ReviewReport.workspace_id == workspace_id,
                ReviewReport.review_run_id == run_id,
                ReviewReport.owner_user_id == owner_user_id,
            )
            .order_by(ReviewReport.version.desc())
        ).all()
    )


def get_owned_review_report(
    db: Session,
    *,
    workspace_id: int,
    run_id: int,
    report_id: int,
    owner_user_id: int,
) -> ReviewReport | None:
    return db.scalar(
        select(ReviewReport).where(
            ReviewReport.id == report_id,
            ReviewReport.workspace_id == workspace_id,
            ReviewReport.review_run_id == run_id,
            ReviewReport.owner_user_id == owner_user_id,
        )
    )


def list_owned_review_report_assets(
    db: Session, *, report: ReviewReport
) -> list[ReviewReportAsset]:
    return list(
        db.scalars(
            select(ReviewReportAsset)
            .where(
                ReviewReportAsset.review_report_id == report.id,
                ReviewReportAsset.workspace_id == report.workspace_id,
                ReviewReportAsset.owner_user_id == report.owner_user_id,
            )
            .order_by(ReviewReportAsset.asset_type.asc())
        ).all()
    )


def get_owned_review_report_asset(
    db: Session,
    *,
    report: ReviewReport,
    asset_id: int,
) -> ReviewReportAsset | None:
    return db.scalar(
        select(ReviewReportAsset).where(
            ReviewReportAsset.id == asset_id,
            ReviewReportAsset.review_report_id == report.id,
            ReviewReportAsset.workspace_id == report.workspace_id,
            ReviewReportAsset.owner_user_id == report.owner_user_id,
        )
    )


def resolve_review_report_asset_path(asset: ReviewReportAsset) -> Path:
    return _resolve_storage_path(asset.storage_path)


def review_report_response(db: Session, report: ReviewReport) -> dict[str, Any]:
    try:
        quality_gate = json.loads(report.quality_gate_json)
    except json.JSONDecodeError:
        quality_gate = {"warnings": [], "error": "quality_gate_json 无法解析"}
    return {
        "id": report.id,
        "workspace_id": report.workspace_id,
        "review_run_id": report.review_run_id,
        "version": report.version,
        "status": report.status,
        "review_state_hash": report.review_state_hash,
        "quality_gate": quality_gate,
        "warning_count": report.warning_count,
        "finding_count": report.finding_count,
        "high_count": report.high_count,
        "medium_count": report.medium_count,
        "low_count": report.low_count,
        "confirmed_count": report.confirmed_count,
        "rejected_count": report.rejected_count,
        "modified_count": report.modified_count,
        "resolved_count": report.resolved_count,
        "pending_review_count": report.pending_review_count,
        "generator_name": report.generator_name,
        "generator_version": report.generator_version,
        "created_at": report.created_at,
        "assets": [
            review_report_asset_response(item)
            for item in list_owned_review_report_assets(db, report=report)
        ],
    }


def review_report_asset_response(asset: ReviewReportAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "review_report_id": asset.review_report_id,
        "asset_type": asset.asset_type,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "content_hash": asset.content_hash,
        "created_at": asset.created_at,
    }


def _build_review_snapshot(
    db: Session,
    *,
    run: ReviewRun,
    workspace_id: int,
    owner_user_id: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    rule_snapshot = _validated_stored_snapshot(
        run.rule_snapshot_json,
        run.rule_pack_hash,
        "规则",
    )
    brief_snapshot = _validated_stored_snapshot(
        run.review_brief_snapshot_json,
        run.review_brief_hash,
        "ReviewBrief",
    )
    rules = rule_snapshot.get("rules")
    if (
        not isinstance(rules, list)
        or not rules
        or rule_snapshot.get("pack_id") != run.rule_pack_id
        or rule_snapshot.get("version") != run.rule_pack_version
    ):
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR",
            "规则快照缺少规则列表，或规则包 ID/版本与 ReviewRun 不一致",
        )
    if (
        brief_snapshot.get("id") != run.review_brief_id
        or brief_snapshot.get("version") != run.review_brief_version
        or not brief_snapshot.get("content_hash")
        or not isinstance(brief_snapshot.get("raw_requirements"), str)
    ):
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR",
            "ReviewBrief 快照缺少必要字段，或 ID/版本与 ReviewRun 不一致",
        )
    interpreted = _parse_nested_json(
        brief_snapshot.get("interpreted_json"), "ReviewBrief interpreted intent"
    )
    retrieval_snapshot = _parse_optional_json(
        run.retrieval_snapshot_json, "retrieval_snapshot_json"
    )

    findings = list(
        db.scalars(
            select(ReviewFinding)
            .where(
                ReviewFinding.review_run_id == run.id,
                ReviewFinding.workspace_id == workspace_id,
                ReviewFinding.owner_user_id == owner_user_id,
            )
            .order_by(ReviewFinding.id.asc())
        ).all()
    )
    actions = list(
        db.scalars(
            select(ReviewAction)
            .where(
                ReviewAction.review_run_id == run.id,
                ReviewAction.workspace_id == workspace_id,
                ReviewAction.owner_user_id == owner_user_id,
            )
            .order_by(ReviewAction.created_at.asc(), ReviewAction.id.asc())
        ).all()
    )
    actions_by_finding: dict[int, list[ReviewAction]] = defaultdict(list)
    finding_ids = {finding.id for finding in findings}
    for action in actions:
        if action.review_finding_id not in finding_ids:
            raise ReviewReportError(
                "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR",
                f"ReviewAction {action.id} 未关联当前 ReviewRun 的 Finding",
            )
        actions_by_finding[action.review_finding_id].append(action)

    evidence_ids_by_finding: dict[int, list[int]] = {}
    all_evidence_ids: set[int] = set()
    for finding in findings:
        if not finding.rule_id or not finding.rule_version:
            raise ReviewReportError(
                "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR",
                f"Finding {finding.id} 缺少规则 ID 或规则版本",
            )
        try:
            evidence_ids = json.loads(finding.evidence_ids_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReviewReportError(
                "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
                f"Finding {finding.id} 的 Evidence 引用无法解析",
            ) from exc
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(not isinstance(item, int) for item in evidence_ids)
        ):
            raise ReviewReportError(
                "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
                f"Finding {finding.id} 必须引用至少一条有效 Evidence",
            )
        stable_ids = sorted(set(evidence_ids))
        evidence_ids_by_finding[finding.id] = stable_ids
        all_evidence_ids.update(stable_ids)

    evidences = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.id.in_(sorted(all_evidence_ids)))
            .order_by(Evidence.id.asc())
        ).all()
    ) if all_evidence_ids else []
    evidence_map = {item.id: item for item in evidences}
    missing_evidence_ids = sorted(all_evidence_ids - set(evidence_map))
    if missing_evidence_ids:
        raise ReviewReportError(
            "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
            f"Finding 引用了不存在的 Evidence：{missing_evidence_ids}",
        )

    file_ids = sorted({item.file_id for item in evidences})
    files = list(db.scalars(select(File).where(File.id.in_(file_ids))).all()) if file_ids else []
    file_map = {item.id: item for item in files}
    workspace_file_ids = set(
        db.scalars(
            select(WorkspaceFile.file_id).where(
                WorkspaceFile.workspace_id == workspace_id,
                WorkspaceFile.file_id.in_(file_ids),
            )
        ).all()
    ) if file_ids else set()

    evidence_snapshots: list[dict[str, Any]] = []
    for evidence in evidences:
        if (
            evidence.review_run_id != run.id
            or evidence.workspace_id != workspace_id
            or evidence.owner_user_id != owner_user_id
        ):
            raise ReviewReportError(
                "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
                f"Evidence {evidence.id} 不属于当前 ReviewRun、workspace 或用户",
            )
        source_file = file_map.get(evidence.file_id)
        if source_file is None or evidence.file_id not in workspace_file_ids:
            raise ReviewReportError(
                "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
                f"Evidence {evidence.id} 的来源文件不存在或不属于当前 workspace",
            )
        _validate_evidence_locator(evidence)
        if not evidence.quote or not evidence.parser_name or not evidence.parser_version:
            raise ReviewReportError(
                "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
                f"Evidence {evidence.id} 缺少 quote 或解析器元数据",
            )
        evidence_snapshots.append(
            {
                "id": evidence.id,
                "file_id": evidence.file_id,
                "file_name": source_file.filename,
                "locator_type": evidence.locator_type,
                "page_number": evidence.page_number,
                "sheet_name": evidence.sheet_name,
                "cell_range": evidence.cell_range,
                "chunk_id": evidence.chunk_id,
                "quote": evidence.quote,
                "content_hash": evidence.content_hash,
                "parser_name": evidence.parser_name,
                "parser_version": evidence.parser_version,
                "created_at": _iso(evidence.created_at),
            }
        )

    finding_snapshots: list[dict[str, Any]] = []
    for finding in findings:
        action_snapshots = [
            {
                "id": action.id,
                "action_type": action.action_type,
                "before": _parse_optional_json(action.before_json, "Action before_json"),
                "after": _parse_optional_json(action.after_json, "Action after_json"),
                "review_note": action.review_note,
                "created_at": _iso(action.created_at),
            }
            for action in actions_by_finding.get(finding.id, [])
        ]
        finding_snapshots.append(
            {
                "id": finding.id,
                "issue_code": finding.issue_code,
                "title": finding.title,
                "category": finding.category,
                "severity": finding.severity,
                "conclusion": finding.conclusion,
                "suggestion": finding.suggestion,
                "rule_id": finding.rule_id,
                "rule_version": finding.rule_version,
                "evidence_ids": evidence_ids_by_finding[finding.id],
                "source_step_id": finding.source_step_id,
                "status": finding.status,
                "reviewed_at": _iso(finding.reviewed_at),
                "reviewed_by": finding.reviewed_by,
                "review_note": finding.review_note,
                "created_at": _iso(finding.created_at),
                "actions": action_snapshots,
            }
        )

    rule_ids = sorted(
        {
            rule.get("rule_id")
            for rule in rules
            if isinstance(rule, dict) and rule.get("rule_id")
        }
    )
    failed_rule_ids = sorted({item["rule_id"] for item in finding_snapshots})
    passed_rule_ids = sorted(set(rule_ids) - set(failed_rule_ids))
    severity_counts = Counter(item["severity"] for item in finding_snapshots)
    status_counts = Counter(item["status"] for item in finding_snapshots)
    statistics = {
        "finding_count": len(finding_snapshots),
        "high_count": severity_counts["high"],
        "medium_count": severity_counts["medium"],
        "low_count": severity_counts["low"],
        "confirmed_count": status_counts["confirmed"],
        "rejected_count": status_counts["rejected"],
        "modified_count": status_counts["modified"],
        "resolved_count": status_counts["resolved"],
        "pending_review_count": status_counts["pending_review"],
    }
    materials = _material_snapshots(
        db,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        run_created_at=run.created_at,
        evidences=evidence_snapshots,
    )
    snapshot = {
        "schema_version": "review_report_snapshot/v1",
        "run": {
            "id": run.id,
            "status": run.status,
            "rule_pack_id": run.rule_pack_id,
            "rule_pack_version": run.rule_pack_version,
            "rule_pack_hash": run.rule_pack_hash,
            "rule_snapshot": rule_snapshot,
            "review_brief_id": run.review_brief_id,
            "review_brief_version": run.review_brief_version,
            "review_brief_hash": run.review_brief_hash,
            "review_brief_snapshot": brief_snapshot,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "prompt_version": run.prompt_version,
            "retrieval_snapshot": retrieval_snapshot,
            "started_at": _iso(run.started_at),
            "completed_at": _iso(run.completed_at),
        },
        "brief": {
            "id": brief_snapshot.get("id"),
            "version": brief_snapshot.get("version"),
            "content_hash": brief_snapshot.get("content_hash"),
            "raw_requirements": brief_snapshot.get("raw_requirements"),
            "interpreter_type": brief_snapshot.get("interpreter_type"),
            "interpreted": interpreted,
        },
        "rules": {
            "pack_id": run.rule_pack_id,
            "version": run.rule_pack_version,
            "hash": run.rule_pack_hash,
            "snapshot": rule_snapshot,
            "passed_rule_ids": passed_rule_ids,
            "failed_rule_ids": failed_rule_ids,
        },
        "materials": materials,
        "findings": finding_snapshots,
        "evidences": evidence_snapshots,
        "statistics": {
            **statistics,
            "evidence_count": len(evidence_snapshots),
            "passed_rule_count": len(passed_rule_ids),
            "failed_rule_count": len(failed_rule_ids),
        },
    }
    quality_gate = _build_quality_gate(finding_snapshots, evidence_snapshots)
    return snapshot, quality_gate, statistics


def _validated_stored_snapshot(
    raw: str | None, expected_hash: str | None, label: str
) -> dict[str, Any]:
    if not raw or not expected_hash:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label}快照或哈希缺失"
        )
    actual_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label}快照哈希不一致"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label}快照无法解析"
        ) from exc
    if not isinstance(parsed, dict):
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label}快照必须为对象"
        )
    return parsed


def _parse_nested_json(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label} 缺失"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label} 无法解析"
        ) from exc
    if not isinstance(parsed, dict):
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label} 必须为对象"
        )
    return parsed


def _parse_optional_json(value: str | None, label: str) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReviewReportError(
            "REVIEW_REPORT_SNAPSHOT_INTEGRITY_ERROR", f"{label} 无法解析"
        ) from exc


def _validate_evidence_locator(evidence: Evidence) -> None:
    valid = False
    if evidence.locator_type == "pdf_page":
        valid = isinstance(evidence.page_number, int) and evidence.page_number > 0
    elif evidence.locator_type == "spreadsheet_cell":
        valid = bool(evidence.sheet_name and evidence.cell_range)
    elif evidence.locator_type == "text_chunk":
        valid = isinstance(evidence.chunk_id, int) and evidence.chunk_id > 0
    if not valid:
        raise ReviewReportError(
            "REVIEW_REPORT_EVIDENCE_INTEGRITY_ERROR",
            f"Evidence {evidence.id} 缺少 {evidence.locator_type} 所需定位字段",
        )


def _material_snapshots(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    run_created_at: datetime,
    evidences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_summary: dict[int, dict[str, Any]] = {}
    for evidence in evidences:
        record = evidence_summary.setdefault(
            evidence["file_id"],
            {
                "locator_types": set(),
                "evidence_count": 0,
            },
        )
        record["locator_types"].add(evidence["locator_type"])
        record["evidence_count"] += 1
    rows = db.execute(
        select(WorkspaceFile, File)
        .join(File, File.id == WorkspaceFile.file_id)
        .where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.created_at <= run_created_at,
            File.owner_user_id == owner_user_id,
        )
        .order_by(WorkspaceFile.file_id.asc())
    ).all()
    return [
        {
            "file_id": workspace_file.file_id,
            "file_name": source_file.filename,
            "confirmed_role": workspace_file.user_confirmed_role,
            "locator_types": sorted(
                evidence_summary.get(workspace_file.file_id, {}).get(
                    "locator_types", set()
                )
            ),
            "evidence_count": evidence_summary.get(workspace_file.file_id, {}).get(
                "evidence_count", 0
            ),
        }
        for workspace_file, source_file in rows
    ]


def _build_quality_gate(
    findings: list[dict[str, Any]], evidences: list[dict[str, Any]]
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    pending_ids = [item["id"] for item in findings if item["status"] == "pending_review"]
    if pending_ids:
        warnings.append(
            {
                "code": "REVIEW_REPORT_PENDING_REVIEW",
                "message": "报告仍包含待人工复核的问题",
                "finding_ids": pending_ids,
            }
        )
    pending_high_ids = [
        item["id"]
        for item in findings
        if item["severity"] == "high" and item["status"] == "pending_review"
    ]
    if pending_high_ids:
        warnings.append(
            {
                "code": "REVIEW_REPORT_HIGH_RISK_UNREVIEWED",
                "message": "报告仍包含尚未人工处理的高风险问题",
                "finding_ids": pending_high_ids,
            }
        )
    without_actions = [item["id"] for item in findings if not item["actions"]]
    if without_actions:
        warnings.append(
            {
                "code": "REVIEW_REPORT_ACTION_MISSING",
                "message": "部分问题尚无人工复核动作记录",
                "finding_ids": without_actions,
            }
        )
    scan_evidence_ids = [
        item["id"]
        for item in evidences
        if "扫描" in item["quote"] and "OCR" in item["quote"] and "未启用" in item["quote"]
    ]
    if scan_evidence_ids:
        warnings.append(
            {
                "code": "REVIEW_REPORT_OCR_NOT_ENABLED",
                "message": "报告包含扫描页，当前解析结果明确提示未启用 OCR",
                "evidence_ids": scan_evidence_ids,
            }
        )
    return {
        "passed": True,
        "blocking_errors": [],
        "warnings": warnings,
        "requires_professional_review": True,
    }


def render_review_report_markdown(
    report: ReviewReport,
    snapshot: dict[str, Any],
    quality_gate: dict[str, Any],
) -> str:
    run = snapshot["run"]
    brief = snapshot["brief"]
    interpreted = brief["interpreted"]
    statistics = snapshot["statistics"]
    evidence_map = {item["id"]: item for item in snapshot["evidences"]}
    generated_at = _iso(report.created_at) or ""
    lines = [
        "# 工程投标资料辅助审查报告",
        "",
        "## 1. 报告声明",
        "",
        REPORT_DECLARATION,
        "",
        "## 2. 项目与审查运行信息",
        "",
        f"- ReviewRun ID：{run['id']}",
        f"- Run 状态：{run['status']}",
        f"- 规则包：{_md(run['rule_pack_id'])} / {_md(run['rule_pack_version'])}",
        f"- ReviewBrief：v{run['review_brief_version']}（ID {run['review_brief_id']}）",
        f"- 开始时间：{run['started_at'] or '未记录'}",
        f"- 完成时间：{run['completed_at'] or '未记录'}",
        f"- 模型信息：{_md(run['model_provider'] or '未使用')} / {_md(run['model_name'] or '未使用')}",
        "",
        "## 3. 审查范围与用户特殊要求",
        "",
        f"- 原始特殊要求：{_md(brief['raw_requirements'] or '无')}",
        f"- 解释方式：{_md(brief['interpreter_type'] or '未记录')}",
        f"- 审查目标：{_md_list(interpreted.get('objectives'))}",
        f"- 必需检查类型：{_md_list(interpreted.get('required_check_types'))}",
        f"- 排除检查类型：{_md_list(interpreted.get('excluded_check_types'))}",
        f"- 排除范围：{_md_list(interpreted.get('excluded_scopes') or interpreted.get('excluded_scope'))}",
        f"- 优先字段：{_md_list(interpreted.get('priority_fields'))}",
        f"- 输出要求：{_md_list(interpreted.get('output_requirements'))}",
        "",
        "## 4. 材料清单",
        "",
        "| file_id | 文件名 | 已确认材料角色 | Evidence 类型 | Evidence 数量 |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for material in snapshot["materials"]:
        lines.append(
            f"| {material['file_id']} | {_table(material['file_name'])} | "
            f"{_table(material['confirmed_role'] or '未确认')} | "
            f"{_table(', '.join(material['locator_types']))} | {material['evidence_count']} |"
        )
    lines.extend(
        [
            "",
            "## 5. 风险概览",
            "",
            f"- Finding：{statistics['finding_count']} 条",
            f"- 风险分布：高 {statistics['high_count']} / 中 {statistics['medium_count']} / 低 {statistics['low_count']}",
            f"- 状态分布：待复核 {statistics['pending_review_count']} / 已确认 {statistics['confirmed_count']} / 已驳回 {statistics['rejected_count']} / 已修改 {statistics['modified_count']} / 已解决 {statistics['resolved_count']}",
            f"- 通过规则：{statistics['passed_rule_count']} 条（{_md_list(snapshot['rules']['passed_rule_ids'])}）",
            f"- 未通过规则：{statistics['failed_rule_count']} 条（{_md_list(snapshot['rules']['failed_rule_ids'])}）",
            "",
            "## 6. 问题清单",
            "",
            "| 序号 | issue_code | 标题 | 风险等级 | 当前状态 | 规则 ID | Evidence 数量 |",
            "| ---: | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for index, finding in enumerate(snapshot["findings"], start=1):
        lines.append(
            f"| {index} | {_table(finding['issue_code'])} | {_table(finding['title'])} | "
            f"{SEVERITY_LABELS.get(finding['severity'], finding['severity'])} | "
            f"{STATUS_LABELS.get(finding['status'], finding['status'])} | "
            f"{_table(finding['rule_id'])} | {len(finding['evidence_ids'])} |"
        )
    lines.extend(["", "## 7. 逐条问题详情", ""])
    for index, finding in enumerate(snapshot["findings"], start=1):
        lines.extend(
            [
                f"### 7.{index} {_md(finding['issue_code'])} · {_md(finding['title'])}",
                "",
                f"- 问题：{_md(finding['title'])}",
                f"- 风险等级：{SEVERITY_LABELS.get(finding['severity'], finding['severity'])}",
                f"- 结论：{_md(finding['conclusion'])}",
                f"- 处理建议：{_md(finding['suggestion'])}",
                f"- 规则：{_md(finding['rule_id'])} / {_md(finding['rule_version'])}",
                f"- 人工复核状态：{STATUS_LABELS.get(finding['status'], finding['status'])}",
                f"- 人工备注：{_md(finding['review_note'] or '无')}",
                "- 证据：",
            ]
        )
        for evidence_id in finding["evidence_ids"]:
            evidence = evidence_map[evidence_id]
            lines.extend(
                [
                    f"  - Evidence #{evidence_id}：{_md(format_evidence_locator(evidence))}",
                    f"    - quote：{_md(evidence['quote'])}",
                    f"    - parser：{_md(evidence['parser_name'])} / {_md(evidence['parser_version'])}",
                ]
            )
        lines.append("- Action 历史：")
        if not finding["actions"]:
            lines.append("  - 暂无人工复核动作。")
        for action in finding["actions"]:
            before = action["before"] or {}
            after = action["after"] or {}
            lines.append(
                f"  - {action['created_at']} · {ACTION_LABELS.get(action['action_type'], action['action_type'])}"
                f" · Before `{_inline_json(before)}` · After `{_inline_json(after)}`"
                f" · 备注：{_md(action['review_note'] or '无')}"
            )
        lines.append("")
    lines.extend(
        [
            "## 8. 证据索引",
            "",
            "| Evidence ID | 来源文件 | Locator | quote | parser | content_hash |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for evidence in snapshot["evidences"]:
        lines.append(
            f"| {evidence['id']} | {_table(evidence['file_name'])} | "
            f"{_table(format_evidence_locator(evidence))} | {_table(evidence['quote'])} | "
            f"{_table(evidence['parser_name'] + ' / ' + evidence['parser_version'])} | "
            f"{evidence['content_hash'][:12]} |"
        )
    lines.extend(["", "## 9. 人工复核记录", ""])
    action_count = 0
    for finding in snapshot["findings"]:
        for action in finding["actions"]:
            action_count += 1
            lines.append(
                f"- {_md(finding['issue_code'])} · {action['created_at']} · "
                f"{ACTION_LABELS.get(action['action_type'], action['action_type'])} · "
                f"备注：{_md(action['review_note'] or '无')}"
            )
    if action_count == 0:
        lines.append("- 暂无人工复核记录。")
    lines.extend(["", "## 10. 质量门结果与未决事项", ""])
    if quality_gate["warnings"]:
        lines.append("**仍需人工复核：本版本通过完整性质量门，但存在以下警告。**")
        lines.append("")
        for warning in quality_gate["warnings"]:
            lines.append(f"- `{warning['code']}`：{_md(warning['message'])}")
    else:
        lines.append("- 完整性质量门通过；当前未发现质量门警告。")
    lines.extend(
        [
            "",
            "## 11. 可追溯版本信息",
            "",
            f"- 报告版本：v{report.version}",
            f"- ReviewReport ID：{report.id}",
            f"- ReviewRun ID：{run['id']}",
            f"- 审查状态哈希：`{report.review_state_hash}`",
            f"- 规则快照哈希：`{run['rule_pack_hash']}`",
            f"- ReviewBrief 快照哈希：`{run['review_brief_hash']}`",
            f"- 生成器：{report.generator_name} / {report.generator_version}",
            f"- 生成时间：{generated_at}",
            "",
        ]
    )
    return "\n".join(lines)


def format_evidence_locator(evidence: dict[str, Any]) -> str:
    file_name = evidence["file_name"]
    if evidence["locator_type"] == "pdf_page":
        return f"{file_name} · 第 {evidence['page_number']} 页"
    if evidence["locator_type"] == "spreadsheet_cell":
        return f"{file_name} · {evidence['sheet_name']}!{evidence['cell_range']}"
    return f"{file_name} · 文本块 {evidence['chunk_id']}"


def _write_pdf(report: ReviewReport, markdown: str, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        LongTable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )

    font_name = _register_pdf_font(pdfmetrics, TTFont)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "EngineeringReviewNormal",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=14,
        wordWrap="CJK",
    )
    table_text = ParagraphStyle(
        "EngineeringReviewTable",
        parent=normal,
        fontSize=7.2,
        leading=10,
    )
    headings = {
        1: ParagraphStyle(
            "EngineeringReviewTitle",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=19,
            leading=25,
            alignment=TA_CENTER,
            spaceAfter=9,
        ),
        2: ParagraphStyle(
            "EngineeringReviewH2",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#17365D"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        3: ParagraphStyle(
            "EngineeringReviewH3",
            parent=styles["Heading3"],
            fontName=font_name,
            fontSize=10.5,
            leading=15,
            spaceBefore=6,
            spaceAfter=3,
        ),
    }
    story: list[Any] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("#"):
            level = min(3, len(line) - len(line.lstrip("#")))
            story.append(Paragraph(_pdf_text(_plain(line[level:].strip())), headings[level]))
        elif (
            "|" in line
            and index + 1 < len(lines)
            and re.match(r"^\|?\s*:?-{3,}", lines[index + 1].strip())
        ):
            rows = [_table_cells(line)]
            index += 2
            while index < len(lines) and "|" in lines[index]:
                rows.append(_table_cells(lines[index]))
                index += 1
            data = [
                [Paragraph(_pdf_text(_plain(cell)), table_text) for cell in row]
                for row in rows
            ]
            table = LongTable(
                data,
                colWidths=_table_widths(len(rows[0]), mm),
                repeatRows=1,
                splitByRow=1,
            )
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), font_name),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB7C4")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F6")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
                    ]
                )
            )
            story.extend([table, Spacer(1, 3 * mm)])
            continue
        else:
            text = line.lstrip("> ")
            if text.startswith(("- ", "* ")):
                text = f"• {text[2:]}"
            story.append(Paragraph(_pdf_text(_plain(text)), normal))
            story.append(Spacer(1, 1.2 * mm))
        index += 1
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title="工程投标资料辅助审查报告",
        author="InsightFlow Agent",
    )
    footer = _pdf_footer(report, font_name)
    document.build(story, onFirstPage=footer, onLaterPages=footer)


def _register_pdf_font(pdfmetrics: Any, ttfont: Any) -> str:
    font_name = "EngineeringReviewCJK"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            pdfmetrics.registerFont(ttfont(font_name, str(candidate), subfontIndex=0))
            return font_name
        except Exception:
            continue
    raise RuntimeError("未找到 Microsoft YaHei、SimSun 或 Noto Sans CJK 中文字体")


def _pdf_footer(report: ReviewReport, font_name: str):
    generated_at = _iso(report.created_at) or ""

    def draw(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 7.5)
        canvas.drawString(
            45,
            26,
            f"工程审查报告 v{report.version} · ReviewRun {report.review_run_id} · {generated_at}",
        )
        canvas.drawRightString(550, 26, f"第 {document.page} 页")
        canvas.restoreState()

    return draw


def _table_widths(column_count: int, mm: Any) -> list[float] | None:
    widths = {
        4: [20, 75, 43, 24],
        5: [14, 54, 40, 34, 20],
        6: [15, 31, 43, 37, 23, 18],
        7: [12, 25, 47, 19, 20, 25, 14],
    }
    values = widths.get(column_count)
    return [value * mm for value in values] if values else None


def _asset_storage_path(report: ReviewReport, suffix: str) -> str:
    return (
        f"engineering/u{report.owner_user_id}/w{report.workspace_id}/"
        f"run-{report.review_run_id}/report-{report.id}-v{report.version}.{suffix}"
    )


def _asset_file_name(report: ReviewReport, suffix: str) -> str:
    return f"engineering-review-run-{report.review_run_id}-v{report.version}.{suffix}"


def _storage_root() -> Path:
    root = Path(settings.report_dir)
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return root.resolve()


def _resolve_storage_path(storage_path: str) -> Path:
    relative = Path(storage_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReviewReportError(
            "REVIEW_REPORT_GENERATION_ERROR", "工程报告资产存储路径无效"
        )
    root = _storage_root()
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ReviewReportError(
            "REVIEW_REPORT_GENERATION_ERROR", "工程报告资产超出安全存储目录"
        )
    return resolved


def _remove_written_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def _md(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _md_list(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_md(item) for item in value) or "无"
    return _md(value) if value else "无"


def _table(value: Any) -> str:
    return _md(value).replace("|", "\\|")


def _inline_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8").replace("`", "'")


def _plain(value: str) -> str:
    value = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*~`]+", "", value)
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _pdf_text(value: str) -> str:
    return html.escape(value, quote=False).replace("\n", "<br/>")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]
