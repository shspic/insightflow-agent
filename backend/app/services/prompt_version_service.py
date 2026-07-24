import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.prompt_registry import PROMPTS, PromptDefinition
from app.models.prompt_version import PromptVersion


_SENSITIVE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|secret|token|password)\s*[:=]\s*\S+|(?:sk|ds)-[A-Za-z0-9_-]{12,}"
)


def get_active_prompt(db: Session, prompt_name: str) -> PromptVersion:
    if prompt_name not in PROMPTS:
        raise ValueError("Prompt 名称不在受控注册表中")
    record = db.scalar(
        select(PromptVersion).where(
            PromptVersion.prompt_name == prompt_name,
            PromptVersion.status == "active",
        )
    )
    if record is not None:
        _validate_prompt(record)
        return record
    definition = PROMPTS[prompt_name]
    record = db.scalar(
        select(PromptVersion).where(
            PromptVersion.prompt_name == prompt_name,
            PromptVersion.version == definition.version,
        )
    )
    if record is None:
        record = _from_definition(definition)
        db.add(record)
    else:
        record.status = "active"
        record.activated_at = datetime.utcnow()
    db.flush()
    return record


def activate_prompt(db: Session, prompt_id: int, admin_user_id: int) -> PromptVersion:
    target = db.get(PromptVersion, prompt_id)
    if target is None:
        raise ValueError("Prompt 版本不存在")
    if target.prompt_name not in PROMPTS:
        raise ValueError("Prompt 名称不在受控注册表中")
    _validate_prompt(target)
    now = datetime.utcnow()
    active_records = db.scalars(
        select(PromptVersion).where(
            PromptVersion.prompt_name == target.prompt_name,
            PromptVersion.status == "active",
            PromptVersion.id != target.id,
        )
    ).all()
    for item in active_records:
        item.status = "retired"
        item.retired_at = now
    target.status = "active"
    target.activated_at = now
    target.retired_at = None
    target.created_by_user_id = target.created_by_user_id or admin_user_id
    db.flush()
    return target


def _from_definition(definition: PromptDefinition) -> PromptVersion:
    return PromptVersion(
        prompt_name=definition.prompt_name,
        version=definition.version,
        status="active",
        purpose=definition.purpose,
        template_text=definition.template_text,
        input_schema_json=json.dumps({"schema": definition.input_schema}),
        output_schema_json=json.dumps({"schema": definition.output_schema}),
        content_hash=hashlib.sha256(definition.template_text.encode("utf-8")).hexdigest(),
        activated_at=datetime.utcnow(),
    )


def _validate_prompt(record: PromptVersion) -> None:
    if _SENSITIVE_PATTERN.search(record.template_text):
        raise ValueError("Prompt 内容包含疑似密钥或敏感字段")
    expected_hash = hashlib.sha256(record.template_text.encode("utf-8")).hexdigest()
    if record.content_hash != expected_hash:
        raise ValueError("Prompt 内容哈希不匹配")
