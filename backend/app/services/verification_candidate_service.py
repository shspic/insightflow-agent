"""工程 Verification 候选证据人工采纳闭环（阶段 4C-3）。

职责：
- 从成功 Retrieval ToolCall 输出组装候选证据（服务端组装，不接受客户端正文）
- 接受候选前对当前真实 Corpus 重新校验（不信任 ReviewToolCall.output_json）
- 接受：创建/复用正式 Evidence + 绑定 Finding + 写决策，单事务原子提交
- 拒绝：只写决策（evidence_id=null），不触碰 Evidence / Finding / 报告

安全边界：
- 未经用户明确接受，不创建 Evidence、不修改 Finding.evidence_ids_json
- 接受/拒绝均不改变 Finding 的 status/severity/conclusion/suggestion
- 不自动确认、驳回、解决或降低风险；不自动生成新报告
- 不信任前端提交的 file_id / finding_id / locator / quote / hash / parser 信息
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.engineering_tool_registry import ENGINEERING_TOOL_HYBRID_RETRIEVAL
from app.models.evidence import Evidence
from app.models.file import File
from app.models.review_candidate_decision import ReviewCandidateDecision
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.review_tool_call import ReviewToolCall
from app.models.review_verification_run import ReviewVerificationRun
from app.models.workspace_file import WorkspaceFile
from app.retrieval.schemas import CorpusChunk
from app.schemas.review import EvidenceCreate
from app.services.engineering_retrieval_service import (
    build_workspace_corpus,
    get_index_status,
)
from app.services.review_action_service import create_evidence

COMPLETED_VERIFICATION_STATUSES = ("completed", "completed_with_warnings")

REVIEW_NOTE_MAX_LENGTH = 500


class CandidateDecisionError(Exception):
    """候选决策服务异常（带稳定错误码与 HTTP 状态）。"""

    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ── 归属装载 ────────────────────────────────────────────────────────


def _load_owned_run(
    db: Session, workspace_id: int, owner_user_id: int, review_run_id: int
) -> ReviewRun:
    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == owner_user_id,
        )
    )
    if run is None:
        raise CandidateDecisionError(
            "REVIEW_RUN_NOT_FOUND", "ReviewRun 不存在或无权访问", status_code=404
        )
    return run


def _load_owned_verification(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    verification_run_id: int,
) -> ReviewVerificationRun:
    _load_owned_run(db, workspace_id, owner_user_id, review_run_id)
    verification = db.scalar(
        select(ReviewVerificationRun).where(
            ReviewVerificationRun.id == verification_run_id,
            ReviewVerificationRun.review_run_id == review_run_id,
            ReviewVerificationRun.workspace_id == workspace_id,
            ReviewVerificationRun.owner_user_id == owner_user_id,
        )
    )
    if verification is None:
        raise CandidateDecisionError(
            "VERIFICATION_RUN_NOT_FOUND",
            "VerificationRun 不存在或无权访问",
            status_code=404,
        )
    return verification


# ── 候选组装（只读取成功 Retrieval ToolCall） ────────────────────────


def _success_retrieval_calls(
    db: Session, verification: ReviewVerificationRun
) -> list[ReviewToolCall]:
    """只取成功的 hybrid 检索 ToolCall；prepare 与失败 attempt 不产生候选。"""
    return list(
        db.scalars(
            select(ReviewToolCall)
            .where(
                ReviewToolCall.verification_run_id == verification.id,
                ReviewToolCall.tool_name == ENGINEERING_TOOL_HYBRID_RETRIEVAL,
                ReviewToolCall.status == "success",
            )
            .order_by(ReviewToolCall.id.asc())
        ).all()
    )


def _parse_tool_output(tool_call: ReviewToolCall) -> tuple[dict[str, Any] | None, str | None]:
    """安全解析 ToolCall 输出；损坏时返回 (None, warning)，不泄露原始异常。"""
    if not tool_call.output_json:
        return None, f"tool_call#{tool_call.id} 输出为空"
    try:
        data = json.loads(tool_call.output_json)
    except json.JSONDecodeError:
        return None, f"tool_call#{tool_call.id} 输出 JSON 损坏，已跳过"
    if not isinstance(data, dict):
        return None, f"tool_call#{tool_call.id} 输出结构非法，已跳过"
    return data, None


def _extract_candidates(output: dict[str, Any]) -> list[dict[str, Any]]:
    results = output.get("results")
    if not isinstance(results, list):
        return []
    return [r for r in results if isinstance(r, dict)]


def _decision_map(
    db: Session, verification: ReviewVerificationRun
) -> dict[tuple[int, int], ReviewCandidateDecision]:
    rows = list(
        db.scalars(
            select(ReviewCandidateDecision).where(
                ReviewCandidateDecision.verification_run_id == verification.id
            )
        ).all()
    )
    return {(r.review_tool_call_id, r.candidate_rank): r for r in rows}


def list_candidates(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    verification_run_id: int,
) -> dict[str, Any]:
    """组装候选证据列表。

    返回 {"candidates": [...], "warnings": [...]}。
    ToolCall JSON 损坏时跳过该调用并给出安全 warning。
    """
    verification = _load_owned_verification(
        db, workspace_id, owner_user_id, review_run_id, verification_run_id
    )
    decisions = _decision_map(db, verification)
    finding_issue_codes: dict[int, str] = {
        f.id: f.issue_code
        for f in db.scalars(
            select(ReviewFinding).where(ReviewFinding.review_run_id == review_run_id)
        ).all()
    }

    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    for tool_call in _success_retrieval_calls(db, verification):
        output, warning = _parse_tool_output(tool_call)
        if warning:
            warnings.append(warning)
            continue
        assert output is not None
        if not (output.get("candidate_only") and output.get("requires_human_confirmation")):
            warnings.append(f"tool_call#{tool_call.id} 缺少候选边界标记，已跳过")
            continue
        for result in _extract_candidates(output):
            rank = result.get("rank")
            if not isinstance(rank, int) or rank < 1:
                continue
            decision = decisions.get((tool_call.id, rank))
            candidates.append(
                {
                    "verification_run_id": verification.id,
                    "tool_call_id": tool_call.id,
                    "finding_id": tool_call.review_finding_id,
                    "issue_code": finding_issue_codes.get(tool_call.review_finding_id),
                    "candidate_rank": rank,
                    "chunk_id": result.get("chunk_id"),
                    "file_id": result.get("file_id"),
                    "file_name": result.get("file_name"),
                    "file_role": result.get("file_role"),
                    "locator_type": result.get("locator_type"),
                    "page_number": result.get("page_number"),
                    "sheet_name": result.get("sheet_name"),
                    "cell_range": result.get("cell_range"),
                    "quote": result.get("quote"),
                    "score": result.get("score"),
                    "bm25_rank": result.get("bm25_rank"),
                    "dense_rank": result.get("dense_rank"),
                    "content_hash": result.get("content_hash"),
                    "parser_name": result.get("parser_name"),
                    "parser_version": result.get("parser_version"),
                    "index_sha256": tool_call.index_sha256 or output.get("index_sha256") or "",
                    "corpus_sha256": tool_call.corpus_sha256 or output.get("corpus_sha256") or "",
                    "candidate_only": True,
                    "requires_human_confirmation": True,
                    "decision": decision.decision if decision else None,
                    "evidence_id": decision.evidence_id if decision else None,
                    "review_note": decision.review_note if decision else None,
                    "decision_created_at": (
                        decision.created_at.isoformat() if decision else None
                    ),
                }
            )
    # 同一 ToolCall 内候选顺序由 rank 保证稳定；整体按 tool_call id + rank 稳定排序
    candidates.sort(key=lambda c: (c["tool_call_id"], c["candidate_rank"]))
    return {"candidates": candidates, "warnings": warnings}


def list_candidate_decisions(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    verification_run_id: int,
) -> list[dict[str, Any]]:
    """列出某 VerificationRun 的全部人工决策（只追加，不提供修改/删除）。"""
    verification = _load_owned_verification(
        db, workspace_id, owner_user_id, review_run_id, verification_run_id
    )
    rows = list(
        db.scalars(
            select(ReviewCandidateDecision)
            .where(ReviewCandidateDecision.verification_run_id == verification.id)
            .order_by(ReviewCandidateDecision.id.asc())
        ).all()
    )
    return [_decision_response(r) for r in rows]


def _decision_response(row: ReviewCandidateDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "verification_run_id": row.verification_run_id,
        "tool_call_id": row.review_tool_call_id,
        "finding_id": row.review_finding_id,
        "review_run_id": row.review_run_id,
        "candidate_rank": row.candidate_rank,
        "candidate_chunk_id": row.candidate_chunk_id,
        "candidate_content_hash": row.candidate_content_hash,
        "decision": row.decision,
        "evidence_id": row.evidence_id,
        "review_note": row.review_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── 接受前服务端重新校验 ────────────────────────────────────────────


def _verified_quote(text: str, max_len: int = 300) -> str:
    """quote 只能来自当前真实 Corpus chunk 文本（与检索输出同一截断规则）。"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _find_current_chunk(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    chunk_id: str,
) -> CorpusChunk | None:
    corpus, _warnings = build_workspace_corpus(db, workspace_id, owner_user_id)
    for chunk in corpus:
        if chunk.chunk_id == chunk_id:
            return chunk
    return None


def _revalidate_candidate(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    tool_call: ReviewToolCall,
    candidate: dict[str, Any],
) -> tuple[CorpusChunk, str]:
    """接受前重新校验。返回 (当前 CorpusChunk, 重新生成的 quote)。

    校验失败抛出 CandidateDecisionError：
    - 环境变化（corpus/index SHA、角色、文件状态）→ VERIFICATION_CANDIDATE_STALE
    - 候选字段与当前 Corpus 不一致（篡改）→ VERIFICATION_CANDIDATE_INVALID
    """
    # 12. 当前 index/corpus SHA 必须与候选产生时一致（不静默使用旧索引）
    info = get_index_status(db, workspace_id, owner_user_id)
    recorded_corpus_sha = tool_call.corpus_sha256 or ""
    recorded_index_sha = tool_call.index_sha256 or ""
    if not recorded_corpus_sha or recorded_corpus_sha != (info.corpus_sha256 or ""):
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_STALE",
            "语料已变化，候选证据已过期，请重新运行智能核验",
            status_code=409,
        )
    if recorded_index_sha and recorded_index_sha != (info.index_sha256 or ""):
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_STALE",
            "索引已变化，候选证据已过期，请重新运行智能核验",
            status_code=409,
        )

    # 13. 从当前真实 Corpus 重新按 chunk_id 查找来源
    chunk_id = candidate.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID", "候选缺少合法 chunk_id", status_code=422
        )
    chunk = _find_current_chunk(db, workspace_id, owner_user_id, chunk_id)
    if chunk is None:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_STALE",
            "当前语料中已不存在该候选来源，候选已过期",
            status_code=409,
        )

    # 14. 当前 Corpus 中的定位/解析信息必须与候选一致
    locator_fields = (
        ("file_id", chunk.file_id),
        ("locator_type", chunk.locator_type),
        ("page_number", chunk.page_number),
        ("sheet_name", chunk.sheet_name),
        ("cell_range", chunk.cell_range),
        ("parser_name", chunk.parser_name),
        ("parser_version", chunk.parser_version),
    )
    for field, current_value in locator_fields:
        if candidate.get(field) != current_value:
            raise CandidateDecisionError(
                "VERIFICATION_CANDIDATE_INVALID",
                "候选定位信息与当前语料不一致，已拒绝采纳",
                status_code=422,
            )
    # content_hash 不一致视为语料可能已变 → stale
    if candidate.get("content_hash") != chunk.content_hash:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_STALE",
            "候选内容哈希与当前语料不一致，候选已过期",
            status_code=409,
        )

    # 9/10/11. 文件真实存在、仍关联当前 Workspace（ready/角色变化会改变 corpus SHA，
    # 在上一步 SHA 校验中已被拦截；此处兜底文件存在性）
    file_record = db.scalar(select(File).where(File.id == chunk.file_id))
    if file_record is None or file_record.owner_user_id != owner_user_id:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_STALE",
            "候选来源文件已不可用，候选已过期",
            status_code=409,
        )
    wf = db.scalar(
        select(WorkspaceFile).where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.file_id == chunk.file_id,
        )
    )
    if wf is None:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_STALE",
            "候选来源文件已不在当前工作区，候选已过期",
            status_code=409,
        )

    # 15. quote 必须来自重新读取的当前 Corpus chunk
    return chunk, _verified_quote(chunk.text)


def _evidence_chunk_id_for(chunk: CorpusChunk) -> int:
    """text_chunk 定位使用真实 text_chunk_index；不得从字符串 chunk_id 猜数字。"""
    value = chunk.text_chunk_index
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            "无法从当前语料获得可靠的 text_chunk_index，已拒绝采纳",
            status_code=422,
        )
    return value


# ── 决策写入（accept / reject） ─────────────────────────────────────


def create_candidate_decision(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    review_run_id: int,
    verification_run_id: int,
    tool_call_id: int,
    candidate_rank: int,
    decision: str,
    review_note: str | None,
) -> tuple[dict[str, Any], bool]:
    """写入候选人工决策。返回 (决策响应, reused)。

    HTTP 语义由 API 层映射：
    - 新建：201 + reused=false
    - 同决定重复提交：200 + reused=true
    - 相反决定：409 VERIFICATION_CANDIDATE_DECISION_CONFLICT
    """
    if decision not in ("accept", "reject"):
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            "decision 只能为 accept 或 reject",
            status_code=422,
        )
    if not isinstance(candidate_rank, int) or isinstance(candidate_rank, bool) or candidate_rank < 1:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            "candidate_rank 必须为 ≥1 的整数",
            status_code=422,
        )
    if review_note is not None and len(review_note) > REVIEW_NOTE_MAX_LENGTH:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            f"review_note 长度不能超过 {REVIEW_NOTE_MAX_LENGTH}",
            status_code=422,
        )

    verification = _load_owned_verification(
        db, workspace_id, owner_user_id, review_run_id, verification_run_id
    )

    # 3. VerificationRun 必须已完成
    if verification.status not in COMPLETED_VERIFICATION_STATUSES:
        raise CandidateDecisionError(
            "VERIFICATION_RUN_NOT_COMPLETED",
            "VerificationRun 尚未完成，不能进行候选决策",
            status_code=409,
        )

    # 4/5. ToolCall 归属 + 状态 + 工具类型（prepare 不得被误认为候选）
    tool_call = db.scalar(
        select(ReviewToolCall).where(
            ReviewToolCall.id == tool_call_id,
            ReviewToolCall.verification_run_id == verification.id,
            ReviewToolCall.workspace_id == workspace_id,
            ReviewToolCall.owner_user_id == owner_user_id,
        )
    )
    if (
        tool_call is None
        or tool_call.status != "success"
        or tool_call.tool_name != ENGINEERING_TOOL_HYBRID_RETRIEVAL
    ):
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_NOT_FOUND",
            "候选来源 ToolCall 不存在或不是成功的检索调用",
            status_code=404,
        )

    output, warning = _parse_tool_output(tool_call)
    if output is None:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            "候选来源 ToolCall 输出损坏，无法安全校验",
            status_code=422,
        )
    # 6. 候选边界标记
    if not (output.get("candidate_only") and output.get("requires_human_confirmation")):
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            "候选来源缺少人工确认边界标记",
            status_code=422,
        )

    # 7. candidate_rank 在该 ToolCall 真实结果中唯一存在
    matches = [
        r for r in _extract_candidates(output) if r.get("rank") == candidate_rank
    ]
    if len(matches) != 1:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_NOT_FOUND",
            "该 ToolCall 中不存在此 candidate_rank",
            status_code=404,
        )
    candidate = matches[0]

    # 8. ToolCall 的 review_finding_id 必须对应真实 Finding
    finding = None
    if tool_call.review_finding_id is not None:
        finding = db.scalar(
            select(ReviewFinding).where(
                ReviewFinding.id == tool_call.review_finding_id,
                ReviewFinding.review_run_id == review_run_id,
                ReviewFinding.workspace_id == workspace_id,
                ReviewFinding.owner_user_id == owner_user_id,
            )
        )
    if finding is None:
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_INVALID",
            "候选来源未绑定当前 ReviewRun 的有效 Finding",
            status_code=422,
        )

    # 幂等与冲突：同一 (tool_call_id, candidate_rank) 只允许一次最终决策
    existing = db.scalar(
        select(ReviewCandidateDecision).where(
            ReviewCandidateDecision.review_tool_call_id == tool_call.id,
            ReviewCandidateDecision.candidate_rank == candidate_rank,
        )
    )
    if existing is not None:
        if existing.decision == decision:
            return _decision_response(existing), True
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_DECISION_CONFLICT",
            "该候选已有相反的人工决策，决策不可更改",
            status_code=409,
        )

    if decision == "reject":
        # 拒绝：只写决策，不创建 Evidence、不修改 Finding、不修改报告
        row = ReviewCandidateDecision(
            verification_run_id=verification.id,
            review_tool_call_id=tool_call.id,
            review_finding_id=finding.id,
            review_run_id=review_run_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            candidate_rank=candidate_rank,
            candidate_chunk_id=str(candidate.get("chunk_id") or ""),
            candidate_content_hash=str(candidate.get("content_hash") or ""),
            decision="reject",
            candidate_snapshot_json=json.dumps(
                _candidate_snapshot(candidate, tool_call), ensure_ascii=False
            ),
            evidence_id=None,
            review_note=review_note,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _decision_response(row), False

    # accept：服务端重新校验（不信任 ToolCall 输出中的 quote/定位/hash）
    chunk, quote = _revalidate_candidate(
        db,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        tool_call=tool_call,
        candidate=candidate,
    )

    # 构造 EvidenceCreate（text_chunk 使用真实 text_chunk_index）
    evidence_input = EvidenceCreate(
        file_id=chunk.file_id,
        locator_type=chunk.locator_type,
        page_number=chunk.page_number,
        sheet_name=chunk.sheet_name,
        cell_range=chunk.cell_range,
        chunk_id=(
            _evidence_chunk_id_for(chunk)
            if chunk.locator_type == "text_chunk"
            else None
        ),
        quote=quote,
        parser_name=chunk.parser_name,
        parser_version=chunk.parser_version,
    )

    from app.services.review_engine_service import _compute_evidence_hash

    evidence_hash = _compute_evidence_hash(
        {
            "file_id": evidence_input.file_id,
            "locator_type": evidence_input.locator_type,
            "page_number": evidence_input.page_number,
            "sheet_name": evidence_input.sheet_name,
            "cell_range": evidence_input.cell_range,
            "chunk_id": evidence_input.chunk_id,
            "quote": evidence_input.quote,
        }
    )

    snapshot = _candidate_snapshot(candidate, tool_call)
    snapshot["quote"] = quote  # 快照保存服务端重新校验后的 quote

    try:
        # 创建或复用同一 ReviewRun 下完全相同的 Evidence
        evidence = db.scalar(
            select(Evidence).where(
                Evidence.review_run_id == review_run_id,
                Evidence.workspace_id == workspace_id,
                Evidence.owner_user_id == owner_user_id,
                Evidence.file_id == evidence_input.file_id,
                Evidence.locator_type == evidence_input.locator_type,
                Evidence.content_hash == evidence_hash,
            )
        )
        if evidence is None:
            evidence = create_evidence(
                db,
                review_run_id=review_run_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                evidence=evidence_input,
                commit=False,
            )

        # 绑定 Finding：保留原顺序，不重复追加；
        # 不触碰 status/severity/conclusion/suggestion
        evidence_ids = _parse_evidence_ids(finding.evidence_ids_json)
        if evidence.id not in evidence_ids:
            evidence_ids.append(evidence.id)
            finding.evidence_ids_json = json.dumps(evidence_ids, ensure_ascii=False)
            db.add(finding)

        row = ReviewCandidateDecision(
            verification_run_id=verification.id,
            review_tool_call_id=tool_call.id,
            review_finding_id=finding.id,
            review_run_id=review_run_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            candidate_rank=candidate_rank,
            candidate_chunk_id=chunk.chunk_id,
            candidate_content_hash=chunk.content_hash,
            decision="accept",
            candidate_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            evidence_id=evidence.id,
            review_note=review_note,
        )
        db.add(row)
        # Evidence + Finding 绑定 + Decision 三者同一事务原子提交
        db.commit()
    except CandidateDecisionError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise CandidateDecisionError(
            "VERIFICATION_CANDIDATE_DECISION_ERROR",
            "候选采纳写入失败，已回滚全部变更",
            status_code=500,
        ) from e

    db.refresh(row)
    return _decision_response(row), False


def _candidate_snapshot(
    candidate: dict[str, Any], tool_call: ReviewToolCall
) -> dict[str, Any]:
    """服务端校验后的候选快照；不保存磁盘路径、密钥或原始模型输出。"""
    return {
        "tool_call_id": tool_call.id,
        "candidate_rank": candidate.get("rank"),
        "chunk_id": candidate.get("chunk_id"),
        "file_id": candidate.get("file_id"),
        "file_name": candidate.get("file_name"),
        "file_role": candidate.get("file_role"),
        "locator_type": candidate.get("locator_type"),
        "page_number": candidate.get("page_number"),
        "sheet_name": candidate.get("sheet_name"),
        "cell_range": candidate.get("cell_range"),
        "quote": candidate.get("quote"),
        "score": candidate.get("score"),
        "bm25_rank": candidate.get("bm25_rank"),
        "dense_rank": candidate.get("dense_rank"),
        "content_hash": candidate.get("content_hash"),
        "parser_name": candidate.get("parser_name"),
        "parser_version": candidate.get("parser_version"),
        "index_sha256": tool_call.index_sha256 or "",
        "corpus_sha256": tool_call.corpus_sha256 or "",
    }


def _parse_evidence_ids(raw: str) -> list[int]:
    try:
        data = json.loads(raw or "[]")
        return [int(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []
