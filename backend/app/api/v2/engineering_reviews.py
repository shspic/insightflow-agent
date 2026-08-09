"""V3 工程审查 API — ReviewBrief, ReviewRun, Finding, Action 的创建/查询/执行。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_password_changed, require_password_changed_csrf
from app.db.session import get_db
from app.models.evidence import Evidence as EvidenceModel
from app.models.review_action import ReviewAction
from app.models.review_brief import ReviewBrief
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.review import (
    InterpretedIntent,
    ReviewBriefCreate,
    ReviewRulePack,
)
from app.services.review_action_service import (
    ReviewServiceError,
    create_review_finding,
    create_review_run,
    execute_review_action,
    list_actions_for_finding,
)
from app.services.review_brief_service import (
    BriefServiceError,
    confirm_review_brief,
    create_review_brief,
    get_confirmed_brief,
    get_review_brief,
)
from app.services.review_rule_service import (
    compute_rule_pack_hash,
    compute_rule_snapshot,
    load_rule_pack,
)
from app.services.engineering_review_pipeline_service import (
    PipelineError,
    run_engineering_review,
    _restore_rule_pack,
)
from app.services.engineering_verification_service import (
    VerificationServiceError,
    get_verification_run,
    list_verification_runs,
    list_verification_tool_calls,
    run_verification,
)
from app.services.verification_candidate_service import (
    CandidateDecisionError,
    create_candidate_decision,
    list_candidate_decisions as list_verification_candidate_decisions,
    list_candidates as list_verification_candidates,
)
from app.services.review_report_service import (
    ReviewReportError,
    generate_review_report,
    get_owned_review_report,
    get_owned_review_report_asset,
    list_owned_review_report_assets,
    list_owned_review_reports,
    resolve_review_report_asset_path,
    review_report_asset_response,
    review_report_response,
)

router = APIRouter(
    prefix="/api/v2/workspaces/{workspace_id}",
    tags=["v3-engineering-reviews"],
)


# ── 辅助 ────────────────────────────────────────────────────────────


def _ws(db: Session, workspace_id: int, user_id: int) -> Workspace:
    ws = db.scalar(select(Workspace).where(
        Workspace.id == workspace_id, Workspace.owner_user_id == user_id, Workspace.deleted_at.is_(None)))
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


def _eng_ws(db: Session, workspace_id: int, user_id: int) -> Workspace:
    ws = _ws(db, workspace_id, user_id)
    if ws.workspace_type != "engineering":
        raise HTTPException(status_code=403, detail="仅 engineering 工作区可执行审查操作")
    return ws


def _brief_or_404(db: Session, brief_id: int, workspace_id: int, user_id: int) -> ReviewBrief:
    brief = db.scalar(select(ReviewBrief).where(
        ReviewBrief.id == brief_id, ReviewBrief.workspace_id == workspace_id, ReviewBrief.owner_user_id == user_id))
    if brief is None:
        raise HTTPException(status_code=404, detail="ReviewBrief 不存在")
    return brief


def _run_or_404(db: Session, run_id: int, workspace_id: int, user_id: int) -> ReviewRun:
    run = db.scalar(select(ReviewRun).where(
        ReviewRun.id == run_id, ReviewRun.workspace_id == workspace_id, ReviewRun.owner_user_id == user_id))
    if run is None:
        raise HTTPException(status_code=404, detail="ReviewRun 不存在")
    return run


def _finding_or_404(db: Session, finding_id: int, workspace_id: int, user_id: int) -> ReviewFinding:
    f = db.scalar(select(ReviewFinding).where(
        ReviewFinding.id == finding_id, ReviewFinding.workspace_id == workspace_id, ReviewFinding.owner_user_id == user_id))
    if f is None:
        raise HTTPException(status_code=404, detail="Finding 不存在")
    return f


# ── ReviewBrief ──────────────────────────────────────────────────────


@router.post("/review-briefs", status_code=status.HTTP_201_CREATED)
def api_create_brief(
    workspace_id: int, payload: dict,
    user: User = Depends(require_password_changed_csrf), db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    raw = payload.get("raw_requirements", "")
    interpreted_data = payload.get("interpreted", {})
    itype = payload.get("interpreter_type", "deterministic_fixture")
    if itype not in ("manual", "deterministic_fixture"):
        raise HTTPException(status_code=422, detail="interpreter_type 仅允许 manual 或 deterministic_fixture")
    try:
        intent = InterpretedIntent.model_validate(interpreted_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"结构化意图校验失败: {e}") from e

    data = ReviewBriefCreate(raw_requirements=raw, interpreted=intent, interpreter_type=itype)
    try:
        brief = create_review_brief(db, workspace_id=workspace_id, owner_user_id=user.id, data=data)
    except BriefServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _brief_response(brief)


@router.get("/review-briefs/current")
def api_get_current_brief(
    workspace_id: int,
    user: User = Depends(require_password_changed), db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    brief = get_confirmed_brief(db, workspace_id=workspace_id, owner_user_id=user.id)
    if brief is None:
        raise HTTPException(status_code=404, detail="当前无已确认的 ReviewBrief")
    return _brief_response(brief)


@router.get("/review-briefs/{brief_id}")
def api_get_brief(
    workspace_id: int, brief_id: int,
    user: User = Depends(require_password_changed), db: Session = Depends(get_db),
):
    brief = _brief_or_404(db, brief_id, workspace_id, user.id)
    return _brief_response(brief)


@router.post("/review-briefs/{brief_id}/confirm")
def api_confirm_brief(
    workspace_id: int, brief_id: int,
    user: User = Depends(require_password_changed_csrf), db: Session = Depends(get_db),
):
    brief = _brief_or_404(db, brief_id, workspace_id, user.id)
    try:
        brief = confirm_review_brief(db, brief_id=brief_id, owner_user_id=user.id)
    except BriefServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _brief_response(brief)


def _brief_response(brief: ReviewBrief) -> dict:
    interpreted = None
    if brief.interpreted_json:
        try:
            interpreted = json.loads(brief.interpreted_json)
        except json.JSONDecodeError:
            pass
    return {
        "id": brief.id, "workspace_id": brief.workspace_id, "version": brief.version,
        "raw_requirements": brief.raw_requirements,
        "interpreted": interpreted,
        "status": brief.status,
        "interpreter_type": brief.interpreter_type,
        "content_hash": brief.content_hash,
        "clarification_questions": json.loads(brief.clarification_questions_json) if brief.clarification_questions_json else [],
        "created_at": brief.created_at.isoformat(),
        "confirmed_at": brief.confirmed_at.isoformat() if brief.confirmed_at else None,
        "confirmed_by": brief.confirmed_by,
    }


# ── ReviewRun ────────────────────────────────────────────────────────


@router.post("/review-runs", status_code=status.HTTP_201_CREATED)
def api_create_run(
    workspace_id: int, payload: dict,
    user: User = Depends(require_password_changed_csrf), db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    brief_id = payload.get("review_brief_id")
    if not brief_id:
        raise HTTPException(status_code=422, detail="必须指定 review_brief_id")
    template_key = payload.get("review_template_key", "engineering_bid_review_v1")
    if template_key != "engineering_bid_review_v1":
        raise HTTPException(status_code=422, detail="仅支持 engineering_bid_review_v1")

    rule_pack = load_rule_pack(template_key)
    snapshot = compute_rule_snapshot(rule_pack)
    pack_hash = compute_rule_pack_hash(snapshot)
    try:
        run = create_review_run(db, workspace_id=workspace_id, owner_user_id=user.id,
                                rule_pack=rule_pack, rule_snapshot=snapshot, rule_pack_hash=pack_hash,
                                review_brief_id=brief_id)
    except ReviewServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _run_detail(db, run)


@router.get("/review-runs")
def api_list_runs(workspace_id: int, user: User = Depends(require_password_changed), db: Session = Depends(get_db)):
    _eng_ws(db, workspace_id, user.id)
    runs = list(db.scalars(select(ReviewRun).where(
        ReviewRun.workspace_id == workspace_id, ReviewRun.owner_user_id == user.id).order_by(ReviewRun.created_at.desc())).all())
    return [_run_summary(db, r) for r in runs]


@router.get("/review-runs/{run_id}")
def api_get_run(workspace_id: int, run_id: int, user: User = Depends(require_password_changed), db: Session = Depends(get_db)):
    _eng_ws(db, workspace_id, user.id)
    run = _run_or_404(db, run_id, workspace_id, user.id)
    return _run_detail(db, run)


@router.post("/review-runs/{run_id}/execute")
def api_execute_run(
    workspace_id: int, run_id: int,
    user: User = Depends(require_password_changed_csrf), db: Session = Depends(get_db),
):
    ws = _eng_ws(db, workspace_id, user.id)
    run = _run_or_404(db, run_id, workspace_id, user.id)

    # 幂等
    if run.status == "completed":
        findings = list(db.scalars(select(ReviewFinding).where(ReviewFinding.review_run_id == run.id)).all())
        ev_count = db.scalar(select(sa_func.count()).select_from(EvidenceModel).where(EvidenceModel.review_run_id == run.id)) or 0
        return {"status": "completed", "finding_count": len(findings), "evidence_count": ev_count, "message": "Run 已完成，返回现有结果（幂等）"}

    try:
        result = run_engineering_review(db, run=run, workspace=ws, owner_user_id=user.id)
    except PipelineError as e:
        raise HTTPException(status_code=422, detail={"error_code": e.code, "message": e.message}) from e
    except ReviewServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"审查执行失败: {e}") from e
    return result


@router.get("/review-runs/{run_id}/evidences")
def api_list_evidences(workspace_id: int, run_id: int, user: User = Depends(require_password_changed), db: Session = Depends(get_db)):
    _eng_ws(db, workspace_id, user.id)
    run = _run_or_404(db, run_id, workspace_id, user.id)
    evs = list(db.scalars(select(EvidenceModel).where(EvidenceModel.review_run_id == run.id)).all())
    return [{"id": e.id, "file_id": e.file_id, "locator_type": e.locator_type,
             "page_number": e.page_number, "sheet_name": e.sheet_name,
             "cell_range": e.cell_range, "chunk_id": e.chunk_id,
             "quote": e.quote, "content_hash": e.content_hash,
             "parser_name": e.parser_name, "parser_version": e.parser_version} for e in evs]


@router.get("/review-runs/{run_id}/findings")
def api_list_findings(workspace_id: int, run_id: int, user: User = Depends(require_password_changed), db: Session = Depends(get_db)):
    _eng_ws(db, workspace_id, user.id)
    run = _run_or_404(db, run_id, workspace_id, user.id)
    findings = list(db.scalars(select(ReviewFinding).where(ReviewFinding.review_run_id == run.id).order_by(ReviewFinding.id.asc())).all())
    return [_finding_response(f) for f in findings]


# ── ReviewAction ──────────────────────────────────────────────────────


@router.post("/review-findings/{finding_id}/actions", status_code=status.HTTP_201_CREATED)
def api_create_action(
    workspace_id: int, finding_id: int, payload: dict,
    user: User = Depends(require_password_changed_csrf), db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    finding = _finding_or_404(db, finding_id, workspace_id, user.id)
    atype = payload.get("action_type", "")
    try:
        finding, action = execute_review_action(db, finding_id=finding_id, owner_user_id=user.id, action_type=atype,
                                                review_note=payload.get("review_note"),
                                                modified_conclusion=payload.get("modified_conclusion"),
                                                modified_suggestion=payload.get("modified_suggestion"))
    except ReviewServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"finding": _finding_response(finding), "action": _action_response(action)}


@router.get("/review-findings/{finding_id}/actions")
def api_list_actions(workspace_id: int, finding_id: int, user: User = Depends(require_password_changed), db: Session = Depends(get_db)):
    _eng_ws(db, workspace_id, user.id)
    _finding_or_404(db, finding_id, workspace_id, user.id)
    actions = list_actions_for_finding(db, finding_id, user.id)
    return [_action_response(a) for a in actions]


# ── ReviewReport ─────────────────────────────────────────────────────────────


def _review_report_error(exc: ReviewReportError) -> HTTPException:
    status_code = 500 if exc.code == "REVIEW_REPORT_GENERATION_ERROR" else 409
    return HTTPException(
        status_code=status_code,
        detail={"error_code": exc.code, "message": exc.message},
    )


@router.post("/review-runs/{run_id}/reports")
def api_generate_review_report(
    workspace_id: int,
    run_id: int,
    response: Response,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    run = _run_or_404(db, run_id, workspace_id, user.id)
    try:
        report, reused = generate_review_report(
            db,
            run=run,
            workspace_id=workspace_id,
            owner_user_id=user.id,
        )
    except ReviewReportError as exc:
        raise _review_report_error(exc) from exc
    response.status_code = status.HTTP_200_OK if reused else status.HTTP_201_CREATED
    result = review_report_response(db, report)
    result["reused"] = reused
    return result


@router.get("/review-runs/{run_id}/reports")
def api_list_review_reports(
    workspace_id: int,
    run_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    return [
        review_report_response(db, report)
        for report in list_owned_review_reports(
            db,
            workspace_id=workspace_id,
            run_id=run_id,
            owner_user_id=user.id,
        )
    ]


@router.get("/review-runs/{run_id}/reports/{report_id}")
def api_get_review_report(
    workspace_id: int,
    run_id: int,
    report_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    report = get_owned_review_report(
        db,
        workspace_id=workspace_id,
        run_id=run_id,
        report_id=report_id,
        owner_user_id=user.id,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="工程审查报告不存在")
    return review_report_response(db, report)


@router.get("/review-runs/{run_id}/reports/{report_id}/assets")
def api_list_review_report_assets(
    workspace_id: int,
    run_id: int,
    report_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    report = get_owned_review_report(
        db,
        workspace_id=workspace_id,
        run_id=run_id,
        report_id=report_id,
        owner_user_id=user.id,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="工程审查报告不存在")
    return [
        review_report_asset_response(asset)
        for asset in list_owned_review_report_assets(db, report=report)
    ]


@router.get(
    "/review-runs/{run_id}/reports/{report_id}/assets/{asset_id}/download"
)
def api_download_review_report_asset(
    workspace_id: int,
    run_id: int,
    report_id: int,
    asset_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
) -> FileResponse:
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    report = get_owned_review_report(
        db,
        workspace_id=workspace_id,
        run_id=run_id,
        report_id=report_id,
        owner_user_id=user.id,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="工程审查报告不存在")
    asset = get_owned_review_report_asset(db, report=report, asset_id=asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="工程审查报告资产不存在")
    try:
        path = resolve_review_report_asset_path(asset)
    except ReviewReportError as exc:
        raise _review_report_error(exc) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="工程审查报告资产文件不存在")
    return FileResponse(
        path,
        media_type=asset.mime_type,
        filename=asset.file_name,
        headers={"Cache-Control": "private, no-store"},
    )


# ── Response builders ────────────────────────────────────────────────


def _run_summary(db: Session, run: ReviewRun) -> dict:
    fc = db.scalar(select(sa_func.count()).select_from(ReviewFinding).where(ReviewFinding.review_run_id == run.id)) or 0
    return {"id": run.id, "workspace_id": run.workspace_id, "status": run.status,
            "review_template_key": run.review_template_key, "rule_pack_id": run.rule_pack_id,
            "rule_pack_version": run.rule_pack_version, "finding_count": fc,
            "created_at": run.created_at.isoformat()}


def _run_detail(db: Session, run: ReviewRun) -> dict:
    findings = list(db.scalars(select(ReviewFinding).where(ReviewFinding.review_run_id == run.id)).all())
    ev_count = db.scalar(select(sa_func.count()).select_from(EvidenceModel).where(EvidenceModel.review_run_id == run.id)) or 0

    # 从快照恢复规则包以计算 passed/failed（不回退 YAML）
    failed_ids = {f.issue_code for f in findings}
    try:
        rp = _restore_rule_pack(run)
        all_ids = {r.rule_id for r in rp.rules}
        passed_ids = sorted(all_ids - failed_ids)
        integrity_error = None
    except Exception as e:
        passed_ids = []
        integrity_error = {"error_code": "REVIEW_SNAPSHOT_INTEGRITY_ERROR", "message": str(e)}

    sev = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        if f.severity in sev:
            sev[f.severity] += 1

    return {
        "id": run.id, "workspace_id": run.workspace_id, "status": run.status,
        "review_template_key": run.review_template_key,
        "rule_pack_id": run.rule_pack_id, "rule_pack_version": run.rule_pack_version,
        "rule_pack_hash": run.rule_pack_hash,
        "review_brief_id": run.review_brief_id, "review_brief_version": run.review_brief_version,
        "finding_count": len(findings), "evidence_count": ev_count,
        "severity_counts": sev,
        "passed_rule_ids": passed_ids, "failed_rule_ids": sorted(failed_ids),
        "integrity_error": integrity_error,
        "error_code": run.error_code, "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
    }


def _finding_response(f: ReviewFinding) -> dict:
    return {"id": f.id, "issue_code": f.issue_code, "title": f.title,
            "category": f.category, "severity": f.severity,
            "conclusion": f.conclusion, "suggestion": f.suggestion,
            "rule_id": f.rule_id, "rule_version": f.rule_version,
            "evidence_ids": json.loads(f.evidence_ids_json) if f.evidence_ids_json else [],
            "status": f.status, "source_step_id": f.source_step_id,
            "created_at": f.created_at.isoformat(),
            "reviewed_at": f.reviewed_at.isoformat() if f.reviewed_at else None,
            "reviewed_by": f.reviewed_by, "review_note": f.review_note}


def _action_response(a: ReviewAction) -> dict:
    return {"id": a.id, "action_type": a.action_type,
            "before_json": json.loads(a.before_json) if a.before_json else None,
            "after_json": json.loads(a.after_json) if a.after_json else None,
            "review_note": a.review_note, "created_at": a.created_at.isoformat()}


# ── Verification Agent（阶段 4C-2）────────────────────────────────────


def _verification_error(exc: VerificationServiceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error_code": exc.code, "message": exc.message},
    )


@router.post(
    "/review-runs/{run_id}/verification-runs",
    status_code=status.HTTP_201_CREATED,
)
def api_create_verification_run(
    workspace_id: int,
    run_id: int,
    payload: dict,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
):
    """运行工程 Verification Agent。

    同状态重复调用返回 200 + reused=true；新运行返回 201 + reused=false。
    """
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)

    use_deepseek = bool(payload.get("use_deepseek", False))
    try:
        max_tool_calls = int(payload.get("max_tool_calls", 5))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="max_tool_calls 必须为整数")
    if not (1 <= max_tool_calls <= 5):
        raise HTTPException(
            status_code=422, detail="max_tool_calls 必须在 1～5 之间"
        )

    try:
        result, reused = run_verification(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            review_run_id=run_id,
            use_deepseek=use_deepseek,
            max_tool_calls=max_tool_calls,
            actor_user_id=user.id,  # 阶段 5A-2：MCP 调用者身份
        )
    except VerificationServiceError as e:
        raise _verification_error(e) from e

    if reused:
        return Response(
            content=json.dumps(result, ensure_ascii=False),
            status_code=200,
            media_type="application/json",
        )
    return result


@router.get("/review-runs/{run_id}/verification-runs")
def api_list_verification_runs(
    workspace_id: int,
    run_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    try:
        return list_verification_runs(db, workspace_id, user.id, run_id)
    except VerificationServiceError as e:
        raise _verification_error(e) from e


@router.get("/review-runs/{run_id}/verification-runs/{verification_run_id}")
def api_get_verification_run(
    workspace_id: int,
    run_id: int,
    verification_run_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    try:
        return get_verification_run(
            db, workspace_id, user.id, run_id, verification_run_id
        )
    except VerificationServiceError as e:
        raise _verification_error(e) from e


@router.get(
    "/review-runs/{run_id}/verification-runs/{verification_run_id}/tool-calls"
)
def api_list_verification_tool_calls(
    workspace_id: int,
    run_id: int,
    verification_run_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    try:
        return list_verification_tool_calls(
            db, workspace_id, user.id, run_id, verification_run_id
        )
    except VerificationServiceError as e:
        raise _verification_error(e) from e


# ── 候选证据人工采纳闭环（阶段 4C-3）─────────────────────────────────


def _candidate_error(exc: CandidateDecisionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error_code": exc.code, "message": exc.message},
    )


@router.get(
    "/review-runs/{run_id}/verification-runs/{verification_run_id}/candidates"
)
def api_list_verification_candidates(
    workspace_id: int,
    run_id: int,
    verification_run_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    """组装候选证据（服务端从成功检索 ToolCall 输出读取，不接受客户端正文）。"""
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    try:
        return list_verification_candidates(
            db, workspace_id, user.id, run_id, verification_run_id
        )
    except CandidateDecisionError as e:
        raise _candidate_error(e) from e


@router.post(
    "/review-runs/{run_id}/verification-runs/{verification_run_id}/candidate-decisions",
    status_code=status.HTTP_201_CREATED,
)
def api_create_candidate_decision(
    workspace_id: int,
    run_id: int,
    verification_run_id: int,
    payload: dict,
    response: Response,
    user: User = Depends(require_password_changed_csrf),
    db: Session = Depends(get_db),
):
    """人工接受/拒绝单条候选证据。

    新建 201 + reused=false；同决定重复提交 200 + reused=true；
    相反决定 409；候选过期 409。
    """
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)

    tool_call_id = payload.get("tool_call_id")
    candidate_rank = payload.get("candidate_rank")
    decision = payload.get("decision")
    review_note = payload.get("review_note")
    if not isinstance(tool_call_id, int) or isinstance(tool_call_id, bool):
        raise HTTPException(status_code=422, detail="tool_call_id 必须为整数")
    if not isinstance(decision, str) or decision not in ("accept", "reject"):
        raise HTTPException(status_code=422, detail="decision 只能为 accept 或 reject")
    if review_note is not None and not isinstance(review_note, str):
        raise HTTPException(status_code=422, detail="review_note 必须为字符串")

    try:
        result, reused = create_candidate_decision(
            db,
            workspace_id=workspace_id,
            owner_user_id=user.id,
            review_run_id=run_id,
            verification_run_id=verification_run_id,
            tool_call_id=tool_call_id,
            candidate_rank=candidate_rank,
            decision=decision,
            review_note=review_note,
        )
    except CandidateDecisionError as e:
        raise _candidate_error(e) from e

    result["reused"] = reused
    if reused:
        response.status_code = status.HTTP_200_OK
    return result


@router.get(
    "/review-runs/{run_id}/verification-runs/{verification_run_id}/candidate-decisions"
)
def api_list_candidate_decisions(
    workspace_id: int,
    run_id: int,
    verification_run_id: int,
    user: User = Depends(require_password_changed),
    db: Session = Depends(get_db),
):
    """列出某 VerificationRun 的全部候选人工决策（只追加审计）。"""
    _eng_ws(db, workspace_id, user.id)
    _run_or_404(db, run_id, workspace_id, user.id)
    try:
        return list_verification_candidate_decisions(
            db, workspace_id, user.id, run_id, verification_run_id
        )
    except CandidateDecisionError as e:
        raise _candidate_error(e) from e
