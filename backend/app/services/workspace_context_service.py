import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file import File
from app.models.file_relation import FileRelation
from app.models.workspace_file import WorkspaceFile
from app.schemas.workspace_context import WorkspaceContextResponse
from app.services.file_understanding_service import get_latest_profile
from app.services.workspace_service import get_owned_workspace, safe_public_text


CONTEXT_VERSION = "2.03"


class WorkspaceContextError(Exception):
    def __init__(self, message: str, code: str = "WORKSPACE_CONTEXT_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def build_workspace_context(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    selected_file_ids: list[int] | None = None,
) -> WorkspaceContextResponse:
    workspace = get_owned_workspace(
        db,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
    )
    if workspace is None:
        raise WorkspaceContextError("工作区不存在或无权访问", "WORKSPACE_NOT_FOUND")
    requested_ids = list(dict.fromkeys(selected_file_ids or []))
    statement = (
        select(File, WorkspaceFile)
        .join(WorkspaceFile, WorkspaceFile.file_id == File.id)
        .where(
            WorkspaceFile.workspace_id == workspace_id,
            File.owner_user_id == owner_user_id,
        )
    )
    if selected_file_ids is not None:
        statement = statement.where(File.id.in_(requested_ids))
    rows = list(db.execute(statement).all())
    if selected_file_ids is not None and len(rows) != len(requested_ids):
        raise WorkspaceContextError(
            "包含无权访问或不属于当前工作区的文件",
            "INVALID_FILE_SCOPE",
        )

    ranked_rows = sorted(
        rows,
        key=lambda row: (
            0 if row[1].user_confirmed_role else 1,
            0 if row[0].status == "ready" else 1,
            -row[0].id,
        ),
    )
    max_files = max(1, settings.workspace_context_max_files)
    included_rows = ranked_rows[:max_files]
    omitted_file_ids = [row[0].id for row in ranked_rows[max_files:]]
    file_items = [
        _context_file(db, workspace_id, owner_user_id, file_record, association)
        for file_record, association in included_rows
    ]
    file_items, size_omitted_ids = _trim_context_files(file_items)
    omitted_file_ids.extend(size_omitted_ids)
    included_ids = [item["file_id"] for item in file_items]
    relation_rows = _context_relations(
        db,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        file_ids=included_ids,
    )
    confirmed_relations = [
        _context_relation(item) for item in relation_rows if item.status == "confirmed"
    ]
    pending_relations = [
        _context_relation(item)
        for item in relation_rows
        if item.status == "suggested"
        and item.confidence >= settings.relation_high_confidence
    ]
    quality_issues = [
        {
            "file_id": item["file_id"],
            "filename": item["filename"],
            **issue,
        }
        for item in file_items
        for issue in item.get("quality_issues", [])
    ]
    unready_files = [
        {
            "file_id": item["file_id"],
            "filename": item["filename"],
            "status": item["status"],
            "profile_status": item["profile_status"],
        }
        for item in file_items
        if item["profile_status"] != "ready"
    ]
    context_dict = {
        "context_version": CONTEXT_VERSION,
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "status": workspace.status,
        },
        "user_goal": safe_public_text(workspace.description),
        "selected_file_ids": included_ids,
        "files": file_items,
        "confirmed_relations": confirmed_relations,
        "pending_high_confidence_relations": pending_relations,
        "data_quality_issues": quality_issues,
        "available_tools": _available_tools(file_items),
        "unready_files": unready_files,
        "limits": {
            "requested_file_count": len(rows),
            "included_file_count": len(file_items),
            "max_files": max_files,
            "max_chars": max(1000, settings.workspace_context_max_chars),
            "truncated": bool(omitted_file_ids),
            "omitted_file_ids": list(dict.fromkeys(omitted_file_ids)),
            "full_file_content_included": False,
        },
    }
    context_dict["limits"]["serialized_chars"] = len(
        json.dumps(context_dict, ensure_ascii=False, default=str)
    )
    return WorkspaceContextResponse.model_validate(context_dict)


def _context_file(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    file_record: File,
    association: WorkspaceFile,
) -> dict[str, Any]:
    profile = get_latest_profile(
        db,
        workspace_id=workspace_id,
        file_id=file_record.id,
        owner_user_id=owner_user_id,
    )
    structure: dict[str, Any] = {}
    statistics: dict[str, Any] = {}
    quality: list[dict[str, Any]] = []
    if profile is not None:
        structure = _compact_structure(_json_dict(profile.structure_json))
        statistics = _json_dict(profile.statistics_json)
        quality = _json_object_list(profile.quality_issues_json)
    confirmed_role = association.user_confirmed_role
    return {
        "file_id": file_record.id,
        "filename": file_record.filename,
        "file_type": file_record.file_type,
        "mime_type": file_record.mime_type,
        "size_bytes": file_record.size_bytes,
        "status": file_record.status,
        "profile_id": profile.id if profile else None,
        "profile_version": profile.profile_version if profile else None,
        "profile_status": profile.status if profile else "not_profiled",
        "title": profile.title if profile else None,
        "summary": safe_public_text(profile.summary) if profile else None,
        "effective_role": confirmed_role or (profile.suggested_role if profile else None),
        "role_source": "user" if confirmed_role else "system",
        "system_tags": _json_list(profile.tags_json) if profile else [],
        "user_tags": _json_list(association.tags_json),
        "structure": structure,
        "statistics": statistics,
        "quality_issues": quality,
    }


def _compact_structure(structure: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "profile_schema_version": structure.get("profile_schema_version"),
    }
    if "tables" in structure:
        compact["tables"] = [
            {
                "table_name": table.get("sheet_name") or table.get("table_name"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
                "columns": [
                    {
                        "name": column.get("name"),
                        "inferred_type": column.get("inferred_type"),
                        "missing_ratio": column.get("missing_ratio"),
                    }
                    for column in table.get("columns", [])[:50]
                    if isinstance(column, dict)
                ],
                "primary_key_candidates": table.get("primary_key_candidates", [])[:10],
            }
            for table in structure.get("tables", [])[:20]
            if isinstance(table, dict)
        ]
    for key in (
        "sheet_count",
        "page_count",
        "heading_candidates",
        "headings",
        "chunk_count",
        "citation_capability",
        "suspected_scanned",
        "width",
        "height",
        "format",
        "ocr_status",
        "image_kind",
        "heading_count",
        "code_block_count",
        "table_count",
        "link_count",
        "text_length",
    ):
        if key not in structure:
            continue
        value = structure[key]
        if key == "headings" and isinstance(value, list):
            value = value[:20]
        if key == "heading_candidates" and isinstance(value, list):
            value = value[:20]
        compact[key] = value
    return compact


def _trim_context_files(
    file_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    max_chars = max(1000, settings.workspace_context_max_chars)
    omitted: list[int] = []

    def current_size() -> int:
        return len(json.dumps(file_items, ensure_ascii=False, default=str))

    if current_size() <= max_chars:
        return file_items, omitted
    for item in reversed(file_items):
        item["statistics"] = {"truncated": True}
        if current_size() <= max_chars:
            return file_items, omitted
    for item in reversed(file_items):
        item["structure"] = {"truncated": True}
        if current_size() <= max_chars:
            return file_items, omitted
    while len(file_items) > 1 and current_size() > max_chars:
        omitted.append(file_items.pop()["file_id"])
    return file_items, omitted


def _context_relations(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    file_ids: list[int],
) -> list[FileRelation]:
    if len(file_ids) < 2:
        return []
    return list(
        db.scalars(
            select(FileRelation)
            .where(
                FileRelation.workspace_id == workspace_id,
                FileRelation.owner_user_id == owner_user_id,
                FileRelation.source_file_id.in_(file_ids),
                FileRelation.target_file_id.in_(file_ids),
                FileRelation.status.in_(["confirmed", "suggested"]),
            )
            .order_by(FileRelation.confidence.desc())
        ).all()
    )


def _context_relation(relation: FileRelation) -> dict[str, Any]:
    return {
        "relation_id": relation.id,
        "source_file_id": relation.source_file_id,
        "target_file_id": relation.target_file_id,
        "relation_type": relation.relation_type,
        "direction": relation.direction,
        "confidence": relation.confidence,
        "evidence": _json_dict(relation.evidence_json),
        "status": relation.status,
        "user_note": safe_public_text(relation.user_note),
    }


def _available_tools(files: list[dict[str, Any]]) -> list[str]:
    file_types = {item["file_type"] for item in files}
    tools = ["file_profile_lookup", "file_relation_lookup"]
    if file_types & {"csv", "xlsx"}:
        tools.extend(["safe_table_reader", "preset_pandas_analysis"])
    if "pdf" in file_types:
        tools.append("pdf_chunk_retrieval")
    if file_types & {"md", "markdown"}:
        tools.append("markdown_chunk_retrieval")
    if file_types & {"png", "jpg", "jpeg", "webp"}:
        tools.append("image_ocr")
    return tools


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_object_list(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
