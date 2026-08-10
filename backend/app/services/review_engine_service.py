"""确定性规则引擎 — 六种规则类型的纯函数式执行。

不接受自然语言 Prompt，不调用 LLM，不执行任何动态代码。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from app.schemas.review import ReviewRuleDef, StructuredFieldValue, StructuredReviewInput


class EngineError(Exception):
    """规则引擎执行错误。"""


# ── 公共辅助 ────────────────────────────────────────────────────


def _normalize(value: Any) -> str:
    """规范化字符串：去首尾空白、合并连续空白、转小写。"""
    if not isinstance(value, str):
        value = str(value)
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _parse_iso_date(value: Any) -> date | None:
    """尝试将值解析为 ISO 日期（YYYY-MM-DD），失败返回 None。"""
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()
    if not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_field(input_data: StructuredReviewInput, path: str) -> Any:
    """从结构化输入中按路径读取字段值。"""
    field = input_data.fields.get(path)
    if field is None:
        return None
    return field.value


def _compute_evidence_hash(evidence_data: dict) -> str:
    """计算证据内容哈希。"""
    payload = json.dumps(evidence_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── 六种规则执行函数 ─────────────────────────────────────────────


def execute_required_field(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """检查指定字段是否存在且非空。"""
    findings = []
    for path in rule.inputs.get("fields", []):
        value = _resolve_field(input_data, path)
        allow_ws = rule.parameters.get("allow_whitespace_only", False)
        is_empty = value is None or (isinstance(value, str) and not value.strip())
        if allow_ws and isinstance(value, str) and value.strip():
            is_empty = False
        if is_empty:
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」缺失或为空",
            })
    if not findings:
        return None
    return {
        "rule_type": "required_field",
        "rule_id": rule.rule_id,
        "passed": False,
        "findings": findings,
    }


def execute_cross_file_equal(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """对两个或多个字段执行规范化后相等检查。"""
    fields = rule.inputs.get("fields", [])
    if len(fields) < 2:
        raise EngineError(f"cross_file_equal 规则 {rule.rule_id} 至少需要两个字段")

    normalize = rule.parameters.get("normalize", True)
    case_sensitive = rule.parameters.get("case_sensitive", False)

    values = []
    for path in fields:
        raw = _resolve_field(input_data, path)
        if raw is None:
            return {
                "rule_type": "cross_file_equal",
                "rule_id": rule.rule_id,
                "passed": False,
                "findings": [{
                    "path": path,
                    "passed": False,
                    "message": f"字段「{path}」无值，无法比较",
                }],
            }
        if normalize:
            v = _normalize(str(raw))
            if not case_sensitive:
                v = v.casefold()
            values.append(v)
        else:
            values.append(str(raw))

    if len(set(values)) <= 1:
        return None  # 全部一致

    return {
        "rule_type": "cross_file_equal",
        "rule_id": rule.rule_id,
        "passed": False,
        "findings": [
            {"path": path, "passed": False, "value": _resolve_field(input_data, path)}
            for path in fields
        ],
    }


def execute_numeric_threshold(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """对数值字段执行阈值比较。"""
    threshold = float(rule.parameters["threshold"])
    operator = rule.parameters.get("operator", "gte")

    findings = []
    for path in rule.inputs.get("fields", []):
        raw = _resolve_field(input_data, path)
        if raw is None:
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」无值",
            })
            continue
        try:
            num = float(raw)
        except (TypeError, ValueError):
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」值「{raw}」非数值",
            })
            continue

        passed = False
        if operator == "gte":
            passed = num >= threshold
        elif operator == "gt":
            passed = num > threshold
        elif operator == "lte":
            passed = num <= threshold
        elif operator == "lt":
            passed = num < threshold
        elif operator == "eq":
            passed = num == threshold

        if not passed:
            op_label = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<", "eq": "="}[operator]
            findings.append({
                "path": path,
                "passed": False,
                "value": num,
                "message": f"字段「{path}」值 {num} {op_label} {threshold} 不满足",
            })

    if not findings:
        return None
    return {
        "rule_type": "numeric_threshold",
        "rule_id": rule.rule_id,
        "passed": False,
        "findings": findings,
    }


def execute_date_order(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """对日期字段执行顺序比较。"""
    ref_date_str = rule.parameters["reference_date"]
    ref_date = _parse_iso_date(ref_date_str)
    if ref_date is None:
        raise EngineError(f"date_order 规则 {rule.rule_id} reference_date 无法解析：{ref_date_str}")

    operator = rule.parameters.get("operator", "gte")

    findings = []
    for path in rule.inputs.get("fields", []):
        raw = _resolve_field(input_data, path)
        if raw is None:
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」无值",
            })
            continue
        field_date = _parse_iso_date(raw)
        if field_date is None:
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」值「{raw}」无法解析为日期",
            })
            continue

        passed = False
        if operator == "gte":
            passed = field_date >= ref_date
        elif operator == "gt":
            passed = field_date > ref_date
        elif operator == "lte":
            passed = field_date <= ref_date
        elif operator == "lt":
            passed = field_date < ref_date
        elif operator == "eq":
            passed = field_date == ref_date

        if not passed:
            op_label = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<", "eq": "="}[operator]
            findings.append({
                "path": path,
                "passed": False,
                "value": field_date.isoformat(),
                "message": f"字段「{path}」日期 {field_date} {op_label} {ref_date} 不满足",
            })

    if not findings:
        return None
    return {
        "rule_type": "date_order",
        "rule_id": rule.rule_id,
        "passed": False,
        "findings": findings,
    }


def execute_document_presence(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """检查已确认文件角色是否存在。"""
    required_roles = rule.parameters.get("required_roles", [])
    doc_roles = input_data.document_roles

    findings = []
    for role in required_roles:
        file_ids = doc_roles.get(role, [])
        if not file_ids:
            findings.append({
                "role": role,
                "passed": False,
                "message": f"缺少已确认角色「{role}」的文件",
            })

    if not findings:
        return None
    return {
        "rule_type": "document_presence",
        "rule_id": rule.rule_id,
        "passed": False,
        "findings": findings,
    }


def execute_evidence_required(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """检查指定字段是否具有有效 Evidence。"""
    findings = []
    for path in rule.inputs.get("fields", []):
        field = input_data.fields.get(path)
        if field is None:
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」不存在于结构化输入中",
            })
            continue
        if not field.evidence_ids:
            findings.append({
                "path": path,
                "passed": False,
                "message": f"字段「{path}」缺少证据定位",
            })

    if not findings:
        return None
    return {
        "rule_type": "evidence_required",
        "rule_id": rule.rule_id,
        "passed": False,
        "findings": findings,
    }


# ── 规则分发 ─────────────────────────────────────────────────────


RULE_EXECUTORS = {
    "required_field": execute_required_field,
    "cross_file_equal": execute_cross_file_equal,
    "numeric_threshold": execute_numeric_threshold,
    "date_order": execute_date_order,
    "document_presence": execute_document_presence,
    "evidence_required": execute_evidence_required,
}


def execute_rule(
    rule: ReviewRuleDef,
    input_data: StructuredReviewInput,
) -> dict[str, Any] | None:
    """分发到对应类型的确定性执行函数。

    Returns:
        None 表示规则通过（无发现）。
        dict 表示发现的问题详情。
    """
    executor = RULE_EXECUTORS.get(rule.type)
    if executor is None:
        raise EngineError(f"未知规则类型：{rule.type}")
    return executor(rule, input_data)


def execute_all_rules(
    rules: list[ReviewRuleDef],
    input_data: StructuredReviewInput,
) -> list[dict[str, Any]]:
    """执行全部规则，返回所有未通过的发现列表。

    每条未通过规则产生一个结果条目。
    """
    results: list[dict[str, Any]] = []
    for rule in rules:
        try:
            result = execute_rule(rule, input_data)
        except EngineError:
            # 单条规则执行异常不中断整体审查
            result = {
                "rule_type": rule.type,
                "rule_id": rule.rule_id,
                "passed": False,
                "error": "规则引擎内部错误",
            }
        if result is not None:
            results.append(result)
    return results
