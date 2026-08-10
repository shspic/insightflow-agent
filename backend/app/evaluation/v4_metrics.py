"""Stage 6A 端到端评测指标（纯函数，可离线单测）。

覆盖：检索 Recall@3/5、MRR；字段抽取 P/R/F1；问题识别 P/R/F1；
引用定位正确率；content_hash 正确率；无证据结论率；Quality Gate 拦截率；
MCP 暂时故障局部重试成功率；Supervisor 完成率/needs_human 率；
报告双资产生成成功率；延迟 mean/P50/P95；工具调用计数。

空集稳定定义（不产生 NaN）：
- 空分母的比率类指标返回 None（聚合时显式标记 empty，不参与均值）
- 汇总层对 None 字段输出 null 并附 count=0，绝不输出 NaN
- answerable 与 no-answer（或可自动完成/需人工）分母严格隔离
"""

from __future__ import annotations

import statistics
from typing import Any


def _safe_ratio(hits: int, total: int) -> float | None:
    """比率；total==0 返回 None（空集稳定定义）。"""
    if total <= 0:
        return None
    return round(hits / total, 4)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.mean(values), 4)


def _safe_p(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(percentile) - 1], 2)


def latency_summary(latencies_ms: list[float]) -> dict[str, Any]:
    """延迟 mean/P50/P95；空列表全部 None（不产生 NaN）。"""
    return {
        "count": len(latencies_ms),
        "mean_ms": _safe_mean(latencies_ms),
        "p50_ms": _safe_p(latencies_ms, 50),
        "p95_ms": _safe_p(latencies_ms, 95),
    }


# ── 检索 ─────────────────────────────────────────────────────────────


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Recall@K；无相关分块 → 1.0（稳定定义）。"""
    if not relevant:
        return 1.0
    hits = sum(1 for cid in retrieved[:k] if cid in set(relevant))
    return round(hits / len(relevant), 4)


def mrr(retrieved: list[str], relevant: list[str]) -> float:
    """MRR；无相关 → 1.0；无命中 → 0.0。"""
    if not relevant:
        return 1.0
    relevant_set = set(relevant)
    for rank, cid in enumerate(retrieved, start=1):
        if cid in relevant_set:
            return round(1.0 / rank, 4)
    return 0.0


# ── 分类指标（字段抽取 / 问题识别共用）──────────────────────────────


def classification_metrics(
    expected_ids: list[str],
    actual_ids: list[str],
) -> dict[str, Any]:
    """P/R/F1；空预期 → 仅定义 abstain 语义：空预期且未输出 → 1.0/1.0/1.0。

    expected_ids 为空视为"没有该类别"，actual 也空 → 完美；actual 非空 → P=0。
    """
    expected_set = set(expected_ids)
    actual_set = set(actual_ids)
    true_positives = len(expected_set & actual_set)
    if not expected_set:
        if not actual_set:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0}
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0, "tp": 0, "fp": len(actual_set), "fn": 0}
    precision = true_positives / len(actual_set) if actual_set else 0.0
    recall = true_positives / len(expected_set)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": true_positives,
        "fp": len(actual_set) - true_positives,
        "fn": len(expected_set) - true_positives,
    }


def aggregate_classification(per_item: list[dict[str, Any]]) -> dict[str, Any]:
    """按 (tp, fp, fn) 微观聚合。空列表 → 全 None + empty 标记。"""
    if not per_item:
        return {"precision": None, "recall": None, "f1": None, "tp": 0, "fp": 0, "fn": 0, "empty": True}
    tp = sum(x["tp"] for x in per_item)
    fp = sum(x["fp"] for x in per_item)
    fn = sum(x["fn"] for x in per_item)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn, "empty": False}


# ── 数值正确率类（引用定位 / content_hash）──────────────────────────


def match_accuracy(per_item: list[bool]) -> dict[str, Any]:
    """正确数/总数/正确率；空列表 → None + empty。"""
    if not per_item:
        return {"count": 0, "correct": 0, "accuracy": None, "empty": True}
    correct = sum(1 for ok in per_item if ok)
    return {"count": len(per_item), "correct": correct,
            "accuracy": _safe_ratio(correct, len(per_item)), "empty": False}


# ── 检索聚合（answerable 与 no-answer 分母隔离）────────────────────


def aggregate_retrieval(
    per_query_answerable: list[dict[str, Any]],
    per_query_no_answer: list[dict[str, Any]],
    ks: tuple[int, ...] = (3, 5),
) -> dict[str, Any]:
    """answerable：Recall@3/5、MRR 均值；no-answer：false_positive 率。"""
    answerable = {
        "answerable_count": len(per_query_answerable),
    }
    for k in ks:
        values = [q.get(f"recall@{k}") for q in per_query_answerable]
        answerable[f"recall@{k}_mean"] = _safe_mean(values)
    answerable["mrr_mean"] = _safe_mean([q.get("mrr") for q in per_query_answerable])
    latencies = [q.get("latency_ms", 0.0) for q in per_query_answerable]
    answerable.update(latency_summary(latencies))

    no_answer = {
        "no_answer_count": len(per_query_no_answer),
        "false_positive_count": sum(1 for q in per_query_no_answer if q.get("false_positive")),
    }
    no_answer["false_positive_rate"] = _safe_ratio(
        no_answer["false_positive_count"], no_answer["no_answer_count"])
    return {"answerable": answerable, "no_answer": no_answer}


def safe_summary(label: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """汇总行包装：None 字段保留为 null，附 empty 标记，不产生 NaN。"""
    return {"split": label, **metrics}
