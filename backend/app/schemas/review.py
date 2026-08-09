"""V3 工程审查 Pydantic schemas — 规则、证据、发现、人工操作、Brief 和意图解释。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

# ── 允许的检查类型与输出要求白名单 ─────────────────────────────────

ALLOWED_CHECK_TYPES = frozenset({
    "required_field",
    "cross_file_equal",
    "numeric_threshold",
    "date_order",
    "document_presence",
    "evidence_required",
})

ALLOWED_OUTPUT_REQUIREMENTS = frozenset({
    "high_risk_requires_evidence",
    "include_unreviewed_scope",
    "group_by_severity",
})

FORBIDDEN_FIELD_NAMES = frozenset({
    "tool_name", "command", "code", "url", "prompt",
    "sql", "shell", "eval", "exec", "import", "script",
})


# ── 规则包 ──────────────────────────────────────────────────────


class RuleInputField(BaseModel):
    """规则引用的输入字段路径，如 bid_response.project_name。"""

    path: str = Field(min_length=1, max_length=200)


class RuleParameter(BaseModel):
    """规则参数，结构因 rule type 不同而异，通过服务层进一步校验。"""

    threshold: float | None = None
    operator: str | None = None
    reference_date: str | None = None
    normalize: bool | None = None
    case_sensitive: bool | None = None
    allow_whitespace_only: bool | None = None
    required_roles: list[str] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ReviewRuleDef(BaseModel):
    """单条审查规则定义，由 YAML 加载后逐一校验。"""

    rule_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    type: Literal[
        "required_field",
        "cross_file_equal",
        "numeric_threshold",
        "date_order",
        "document_presence",
        "evidence_required",
    ]
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=2000)
    severity: Literal["high", "medium", "low"]
    inputs: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    source_kind: Literal["synthetic_tender_clause", "synthetic_clarification_clause"]
    source_locator: str = Field(min_length=1, max_length=500)
    suggestion: str = Field(min_length=1, max_length=2000)


class ReviewRulePack(BaseModel):
    """YAML 规则包顶层结构，加载后通过 Pydantic 校验。"""

    pack_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=3000)
    disclaimer: str = Field(min_length=1, max_length=2000)
    rules: list[ReviewRuleDef] = Field(min_length=1, max_length=500)

    @field_validator("rules")
    @classmethod
    def no_duplicate_rule_ids(cls, value: list[ReviewRuleDef]) -> list[ReviewRuleDef]:
        seen: set[str] = set()
        for rule in value:
            key = f"{rule.rule_id}@{rule.version}"
            if key in seen:
                raise ValueError(f"重复的 rule_id + version：{key}")
            seen.add(key)
        return value


# ── 结构化输入 ──────────────────────────────────────────────────


class StructuredFieldValue(BaseModel):
    """审查引擎结构化输入中的单个字段值。"""

    value: Any = None
    evidence_ids: list[int] = Field(default_factory=list)


class StructuredReviewInput(BaseModel):
    """确定性规则引擎的结构化输入。

    fields: 字段路径 → 值和证据映射
    document_roles: 已确认文件角色 → 文件 ID 列表
    """

    fields: dict[str, StructuredFieldValue] = Field(default_factory=dict)
    document_roles: dict[str, list[int]] = Field(default_factory=dict)


# ── Evidence ────────────────────────────────────────────────────


class EvidenceCreate(BaseModel):
    """创建单条证据的输入。"""

    file_id: int
    locator_type: Literal["pdf_page", "spreadsheet_cell", "text_chunk"]
    page_number: int | None = None
    sheet_name: str | None = Field(default=None, max_length=500)
    cell_range: str | None = Field(default=None, max_length=200)
    chunk_id: int | None = None
    quote: str = Field(min_length=1, max_length=2000)
    parser_name: str = Field(min_length=1, max_length=120)
    parser_version: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def check_locator_fields(self) -> EvidenceCreate:
        lt = self.locator_type
        if lt == "pdf_page":
            if self.page_number is None:
                raise ValueError("pdf_page 定位必须提供 page_number")
            if self.page_number < 1:
                raise ValueError("page_number 必须 ≥ 1")
        if lt == "spreadsheet_cell":
            if not self.sheet_name or not self.sheet_name.strip():
                raise ValueError("spreadsheet_cell 定位必须提供非空 sheet_name")
            if not self.cell_range or not self.cell_range.strip():
                raise ValueError("spreadsheet_cell 定位必须提供非空 cell_range")
        if lt == "text_chunk":
            if self.chunk_id is None:
                raise ValueError("text_chunk 定位必须提供 chunk_id")
            if self.chunk_id < 1:
                raise ValueError("chunk_id 必须 ≥ 1")
        return self


class EvidenceResponse(BaseModel):
    id: int
    review_run_id: int
    workspace_id: int
    owner_user_id: int
    file_id: int
    locator_type: str
    page_number: int | None
    sheet_name: str | None
    cell_range: str | None
    chunk_id: int | None
    quote: str
    content_hash: str
    parser_name: str
    parser_version: str
    created_at: datetime


# ── ReviewFinding ────────────────────────────────────────────────


class ReviewFindingResponse(BaseModel):
    id: int
    review_run_id: int
    workspace_id: int
    owner_user_id: int
    issue_code: str
    title: str
    category: str
    severity: str
    conclusion: str
    suggestion: str
    rule_id: str
    rule_version: str
    evidence_ids: list[int]
    status: str
    source_step_id: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: int | None
    review_note: str | None


# ── ReviewAction ─────────────────────────────────────────────────


class ReviewActionResponse(BaseModel):
    id: int
    review_finding_id: int
    review_run_id: int
    workspace_id: int
    owner_user_id: int
    action_type: str
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    review_note: str | None
    created_at: datetime


# ── ReviewRun ────────────────────────────────────────────────────


class ReviewRunResponse(BaseModel):
    id: int
    workspace_id: int
    owner_user_id: int
    review_template_key: str
    review_brief_id: int | None = None
    review_brief_version: int | None = None
    review_brief_hash: str | None = None
    status: str
    rule_pack_id: str
    rule_pack_version: str
    rule_pack_hash: str
    input_snapshot_hash: str | None
    model_provider: str | None
    model_name: str | None
    prompt_version: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── 结构化意图解释 ───────────────────────────────────────────────


class InterpretedIntent(BaseModel):
    """结构化意图解释 — 从 raw_requirements 规范化后的完整快照。

    禁止额外字段，禁止可执行控制字段。
    """

    model_config = {"extra": "forbid"}

    objectives: list[str] = Field(min_length=1, max_length=20)
    required_check_types: list[str] = Field(min_length=1, max_length=20)
    excluded_check_types: list[str] = Field(default_factory=list, max_length=20)
    excluded_scopes: list[str] = Field(default_factory=list, max_length=50)
    priority_fields: list[str] = Field(default_factory=list, max_length=100)
    output_requirements: list[str] = Field(default_factory=list, max_length=20)
    clarification_questions: list[str] = Field(default_factory=list, max_length=50)
    unsupported_requests: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("required_check_types", "excluded_check_types")
    @classmethod
    def check_types_must_be_allowed(cls, value: list[str]) -> list[str]:
        for item in value:
            if item not in ALLOWED_CHECK_TYPES:
                raise ValueError(f"不允许的检查类型：{item}")
        return value

    @field_validator("output_requirements")
    @classmethod
    def output_requirements_must_be_allowed(cls, value: list[str]) -> list[str]:
        for item in value:
            if item not in ALLOWED_OUTPUT_REQUIREMENTS:
                raise ValueError(f"不允许的输出要求：{item}")
        return value

    @field_validator("priority_fields")
    @classmethod
    def priority_fields_format(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item or len(item) > 200:
                raise ValueError(f"priority_field 长度非法：{item}")
            if not item.replace(".", "").replace("_", "").isalnum():
                raise ValueError(f"priority_field 包含非法字符：{item}")
        return value

    @field_validator("objectives")
    @classmethod
    def check_no_forbidden_fields(cls, value: list[str]) -> list[str]:
        for obj in value:
            lower = obj.lower()
            for forbidden in FORBIDDEN_FIELD_NAMES:
                if forbidden in lower:
                    raise ValueError(f"objectives 包含禁止字段「{forbidden}」")
        return value


class ReviewBriefCreate(BaseModel):
    """创建 ReviewBrief 的输入 — raw_requirements 原样留档。"""

    raw_requirements: str = Field(min_length=1, max_length=10000)
    interpreted: InterpretedIntent
    interpreter_type: Literal["manual", "deterministic_fixture"] = "deterministic_fixture"


class ReviewBriefResponse(BaseModel):
    id: int
    workspace_id: int
    owner_user_id: int
    version: int
    raw_requirements: str
    status: str
    interpreter_type: str
    clarification_questions_json: str | None
    content_hash: str
    created_at: datetime
    confirmed_at: datetime | None
    confirmed_by: int | None


# ── Supervisor 启动（阶段 5B）──────────────────────────────────


class SupervisorRunCreate(BaseModel):
    """Supervisor 启动请求：严格类型，拒绝未知字段。

    - 字符串 "false"/"true"、整数 1/0 冒充 bool → 422
    - 浮点冒充整数 → 422
    - 未知字段 → 422
    """

    model_config = ConfigDict(extra="forbid")

    use_deepseek: StrictBool = False
    generate_report: StrictBool = False
    max_verification_tool_calls: StrictInt = Field(default=5, ge=1, le=5)
    max_step_retries: StrictInt = Field(default=1, ge=0, le=2)
