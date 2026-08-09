"""审查规则服务 — YAML 规则包加载、校验、哈希与快照。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from app.schemas.review import ReviewRulePack

RULES_DIR = Path(__file__).resolve().parent.parent / "review_rules"

SUPPORTED_RULE_TYPES = frozenset({
    "required_field",
    "cross_file_equal",
    "numeric_threshold",
    "date_order",
    "document_presence",
    "evidence_required",
})

VALID_OPERATORS = frozenset({"gte", "gt", "lte", "lt", "eq"})


class RuleLoadError(Exception):
    """规则包加载或校验失败。"""


def load_rule_pack(pack_id: str) -> ReviewRulePack:
    """从 YAML 文件加载规则包，经 Pydantic 校验后返回。

    仅允许首版支持的 pack_id：engineering_bid_review_v1。
    """
    if pack_id != "engineering_bid_review_v1":
        raise RuleLoadError(f"不支持的规则包：{pack_id}")

    yaml_path = RULES_DIR / f"{pack_id}.yaml"
    if not yaml_path.is_file():
        raise RuleLoadError(f"规则包文件不存在：{yaml_path}")

    raw = yaml_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise RuleLoadError(f"YAML 解析失败：{exc}") from exc

    if not isinstance(data, dict):
        raise RuleLoadError("YAML 顶层必须为 mapping")

    try:
        pack = ReviewRulePack.model_validate(data)
    except Exception as exc:
        raise RuleLoadError(f"规则包 Pydantic 校验失败：{exc}") from exc

    # 逐条规则额外校验
    for rule in pack.rules:
        _validate_rule_parameters(rule.type, rule.parameters, rule.rule_id)

    return pack


def load_rule_pack_from_snapshot(
    snapshot_json: str, expected_hash: str | None = None
) -> ReviewRulePack:
    """从 ReviewRun 固化的规则快照解析并严格校验规则包（阶段 5A-1）。

    历史 Run 的事实来源必须是其不可变快照，而不是磁盘上最新规则文件。
    - 快照 JSON 损坏或校验失败 → RuleLoadError
    - expected_hash 提供时校验 sha256(snapshot_json) 一致，不一致 → RuleLoadError
    - 不做任何对磁盘规则文件的回退
    """
    if expected_hash is not None:
        actual = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        if actual != expected_hash:
            raise RuleLoadError("规则快照哈希不一致")

    try:
        data = json.loads(snapshot_json)
        pack = ReviewRulePack.model_validate(data)
    except Exception as exc:
        raise RuleLoadError(f"规则快照解析失败: {exc}") from exc

    for rule in pack.rules:
        _validate_rule_parameters(rule.type, rule.parameters, rule.rule_id)
    return pack


def _validate_rule_parameters(rule_type: str, parameters: dict, rule_id: str) -> None:
    """对每条规则的 parameters 做类型专属校验。"""
    if rule_type == "required_field":
        # 无强制参数
        return

    if rule_type == "cross_file_equal":
        # 无强制参数
        return

    if rule_type == "numeric_threshold":
        if "threshold" not in parameters:
            raise RuleLoadError(f"numeric_threshold 规则 {rule_id} 缺少 threshold")
        if not isinstance(parameters["threshold"], (int, float)):
            raise RuleLoadError(f"numeric_threshold 规则 {rule_id} threshold 必须为数值")
        op = parameters.get("operator", "gte")
        if op not in VALID_OPERATORS:
            raise RuleLoadError(
                f"numeric_threshold 规则 {rule_id} operator 不合法：{op}，允许：{sorted(VALID_OPERATORS)}"
            )

    if rule_type == "date_order":
        if "reference_date" not in parameters:
            raise RuleLoadError(f"date_order 规则 {rule_id} 缺少 reference_date")
        operator = parameters.get("operator", "gte")
        if operator not in ("gte", "gt", "lte", "lt", "eq"):
            raise RuleLoadError(
                f"date_order 规则 {rule_id} operator 不合法：{operator}"
            )

    if rule_type == "document_presence":
        roles = parameters.get("required_roles")
        if not roles or not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            raise RuleLoadError(
                f"document_presence 规则 {rule_id} 缺少 required_roles（非空字符串列表）"
            )

    if rule_type == "evidence_required":
        # 无强制参数
        return


def compute_rule_snapshot(pack: ReviewRulePack) -> str:
    """生成规范化的规则快照 JSON 字符串。

    使用 sort_keys 确保相同内容得到相同输出。
    """
    return json.dumps(
        pack.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_rule_pack_hash(snapshot: str) -> str:
    """对规范化的规则快照计算 SHA256 哈希。"""
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


def validate_structured_input(
    input_data: dict,
    required_fields: list[str],
) -> None:
    """校验结构化输入是否包含规则所需的所有字段路径。

    Raises ValueError 当字段缺失。
    """
    available = set(input_data.get("fields", {}).keys())
    missing = [f for f in required_fields if f not in available]
    if missing:
        raise ValueError(f"结构化输入缺少字段：{missing}")
