from sqlalchemy import Index, UniqueConstraint

from app.db.session import Base
from app.models import (
    AuditLog,
    AuthSession,
    AuthRateLimit,
    FileProcessingRun,
    FileProfile,
    FileRelation,
    InviteCode,
    PasswordResetRequest,
    User,
    Workspace,
    WorkspaceFile,
)


V2_TABLES = {
    "users",
    "auth_sessions",
    "invite_codes",
    "password_reset_requests",
    "workspaces",
    "workspace_files",
    "audit_logs",
    "auth_rate_limits",
    "file_profiles",
    "file_relations",
    "file_processing_runs",
}


def test_v2_models_can_import_and_register_metadata() -> None:
    assert all(
        model is not None
        for model in (
            AuditLog,
            AuthSession,
            AuthRateLimit,
            FileProcessingRun,
            FileProfile,
            FileRelation,
            InviteCode,
            PasswordResetRequest,
            User,
            Workspace,
            WorkspaceFile,
        )
    )
    assert V2_TABLES.issubset(Base.metadata.tables)


def test_sensitive_identifiers_have_unique_indexes() -> None:
    assert _has_unique_index("users", ("username",))
    assert _has_unique_index("auth_sessions", ("token_hash",))
    assert _has_unique_index("invite_codes", ("code_hash",))


def test_workspace_file_pair_has_unique_constraint() -> None:
    table = Base.metadata.tables["workspace_files"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("workspace_id", "file_id") in unique_columns


def test_file_profile_version_and_relation_current_indexes_exist() -> None:
    profile_table = Base.metadata.tables["file_profiles"]
    profile_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in profile_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("workspace_id", "file_id", "profile_version") in profile_unique_columns

    relation_table = Base.metadata.tables["file_relations"]
    relation_index = next(
        index
        for index in relation_table.indexes
        if index.name == "uq_file_relations_current_direction_type"
    )
    assert relation_index.unique
    assert tuple(column.name for column in relation_index.columns) == (
        "workspace_id",
        "source_file_id",
        "target_file_id",
        "relation_type",
        "direction",
    )


def test_legacy_ownership_columns_remain_nullable() -> None:
    assert Base.metadata.tables["files"].c.owner_user_id.nullable
    assert Base.metadata.tables["tasks"].c.owner_user_id.nullable
    assert Base.metadata.tables["tasks"].c.workspace_id.nullable


def _has_unique_index(table_name: str, columns: tuple[str, ...]) -> bool:
    table = Base.metadata.tables[table_name]
    return any(
        isinstance(index, Index)
        and index.unique
        and tuple(column.name for column in index.columns) == columns
        for index in table.indexes
    )
