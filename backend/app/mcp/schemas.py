"""Review Tools MCP 输入/输出严格 Schema（阶段 5A-1）。

全部输入 Schema 使用 extra="forbid"：任何额外字段一律拒绝。
禁止客户端传入磁盘路径、SQL、URL、Python 代码或任意规则文件路径。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


class SearchReviewRulesInput(BaseModel):
    """search_review_rules 输入。"""

    model_config = ConfigDict(extra="forbid")

    workspace_id: int = Field(ge=1)
    review_run_id: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    request_id: str = Field(min_length=1, max_length=100)

    @field_validator("query")
    @classmethod
    def _query_strip_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query 去除首尾空格后不能为空")
        return stripped


class SearchReviewRulesResultItem(BaseModel):
    """单条规则检索结果。"""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    rule_id: str
    title: str
    description: str
    severity: str
    evidence_required: bool = False
    source_hash: str = ""


class SearchReviewRulesOutput(BaseModel):
    """search_review_rules 输出。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    request_id: str
    tool_name: str = "search_review_rules"
    status: str = "ok"
    latency_ms: int = Field(ge=0)
    rule_pack_id: str = ""
    rule_pack_version: str = ""
    results: list[SearchReviewRulesResultItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None


class RunBidConsistencyChecksInput(BaseModel):
    """run_bid_consistency_checks 输入。

    只接受工作区、ReviewRun 等持久化 ID 与 request_id；
    不允许任意表达式、文件路径、URL 或大段材料原文。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: int = Field(ge=1)
    review_run_id: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=100)


class ConsistencyCheck(BaseModel):
    """单条一致性检查结果（仅审查辅助信息，candidate_only）。"""

    model_config = ConfigDict(extra="forbid")

    check_code: str
    status: str  # pass | warn | fail
    message: str
    finding_ids: list[int] = Field(default_factory=list)
    evidence_ids: list[int] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    requires_human_confirmation: bool = True


class RunBidConsistencyChecksOutput(BaseModel):
    """run_bid_consistency_checks 输出。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    request_id: str
    tool_name: str = "run_bid_consistency_checks"
    status: str = "ok"
    latency_ms: int = Field(ge=0)
    review_run_id: int
    checks: list[ConsistencyCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None
