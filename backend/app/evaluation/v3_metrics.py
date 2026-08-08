"""V3 检索评测指标。

实现：Recall@K、MRR、延迟统计（均值/P50/P95）、no-answer 指标。
包含玩具案例公式验证，含 answerable/no-answer 分母互不污染检查。
"""

from statistics import mean, median
from typing import Any


def recall_at_k(
    retrieved_chunk_ids: list[str],
    relevant_chunk_ids: list[str],
    k: int,
) -> float:
    """Recall@K = |检索到的相关分块| / |全部相关分块|。

    无相关分块 → 1.0。
    """
    if not relevant_chunk_ids:
        return 1.0
    top_k = retrieved_chunk_ids[:k]
    relevant_set = set(relevant_chunk_ids)
    hits = sum(1 for cid in top_k if cid in relevant_set)
    return hits / len(relevant_chunk_ids)


def mrr(
    retrieved_chunk_ids: list[str],
    relevant_chunk_ids: list[str],
) -> float:
    """MRR = 1 / 第一个相关分块的排名位置。

    排名从 1 开始。无相关分块 → 1.0。无命中 → 0.0。
    """
    if not relevant_chunk_ids:
        return 1.0
    relevant_set = set(relevant_chunk_ids)
    for rank, cid in enumerate(retrieved_chunk_ids, start=1):
        if cid in relevant_set:
            return 1.0 / rank
    return 0.0


def compute_answerable_metrics(
    query_id: str,
    retrieved_chunk_ids: list[str],
    relevant_chunk_ids: list[str],
    latency_ms: float,
    ks: tuple[int, ...] = (3, 5),
) -> dict[str, Any]:
    """为单条可回答查询计算指标。"""
    result: dict[str, Any] = {"query_id": query_id, "latency_ms": round(latency_ms, 2)}
    for k in ks:
        result[f"recall@{k}"] = round(
            recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, k), 4
        )
    result["mrr"] = round(mrr(retrieved_chunk_ids, relevant_chunk_ids), 4)
    return result


def compute_no_answer_metrics(
    query_id: str,
    retrieved_chunk_ids: list[str],
    retrieved_scores: list[float],
    latency_ms: float,
) -> dict[str, Any]:
    """为单条无答案查询计算指标。

    abstained: 是否拒绝回答（当前阶段无阈值机制，所有方法都返回结果 → 一律 false）
    false_positive: 返回了任何结果即视为误报
    top1_score: 最高分数（无结果时为 0.0）
    result_count: 返回结果数
    """
    return {
        "query_id": query_id,
        "latency_ms": round(latency_ms, 2),
        "abstained": False,  # 当前阶段无阈值机制
        "false_positive": len(retrieved_chunk_ids) > 0,
        "top1_score": round(retrieved_scores[0], 6) if retrieved_scores else 0.0,
        "result_count": len(retrieved_chunk_ids),
    }


def aggregate_answerable(
    per_query: list[dict[str, Any]],
    ks: tuple[int, ...] = (3, 5),
) -> dict[str, Any]:
    """汇总可回答查询的指标。"""
    if not per_query:
        return {
            "answerable_count": 0,
            "latency_mean_ms": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
        }

    agg: dict[str, Any] = {"answerable_count": len(per_query)}

    for k in ks:
        key = f"recall@{k}"
        values = [m[key] for m in per_query if key in m]
        agg[f"{key}_mean"] = round(mean(values), 4) if values else 0.0

    mrr_values = [m["mrr"] for m in per_query if "mrr" in m]
    agg["mrr_mean"] = round(mean(mrr_values), 4) if mrr_values else 0.0

    _latency_stats(per_query, agg)
    return agg


def aggregate_no_answer(
    per_query: list[dict[str, Any]],
) -> dict[str, Any]:
    """汇总无答案查询的指标。"""
    if not per_query:
        return {"no_answer_count": 0}

    fp_count = sum(1 for m in per_query if m.get("false_positive"))
    return {
        "no_answer_count": len(per_query),
        "abstained_count": sum(1 for m in per_query if m.get("abstained")),
        "false_positive_count": fp_count,
        "false_positive_rate": round(fp_count / len(per_query), 4),
        "top1_score_mean": round(mean(
            m.get("top1_score", 0) for m in per_query
        ), 6),
        "result_count_mean": round(mean(
            m.get("result_count", 0) for m in per_query
        ), 1),
    }


def _latency_stats(
    per_query: list[dict[str, Any]],
    agg: dict[str, Any],
) -> None:
    """将延迟统计写入 agg 字典。"""
    latencies = sorted(
        [m["latency_ms"] for m in per_query if "latency_ms" in m]
    )
    if not latencies:
        agg["latency_mean_ms"] = 0.0
        agg["latency_p50_ms"] = 0.0
        agg["latency_p95_ms"] = 0.0
        return

    agg["latency_mean_ms"] = round(mean(latencies), 2)
    agg["latency_p50_ms"] = round(median(latencies), 2)
    p95_idx = max(0, int(len(latencies) * 0.95 + 0.999) - 1)
    agg["latency_p95_ms"] = round(latencies[p95_idx], 2)


def aggregate_by_category(
    per_query_answerable: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    ks: tuple[int, ...] = (3, 5),
) -> dict[str, dict[str, Any]]:
    """按类别汇总可回答查询的指标。"""
    # 建立 query_id → metrics 映射
    by_id: dict[str, dict[str, Any]] = {
        m["query_id"]: m for m in per_query_answerable
    }
    # 建立 query_id → category 映射
    cat_map: dict[str, str] = {}
    for q in queries:
        if q.get("answerable"):
            cat_map[q["query_id"]] = q["category"]

    # 按类别分组
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for qid, metrics in by_id.items():
        cat = cat_map.get(qid, "unknown")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(metrics)

    result: dict[str, dict[str, Any]] = {}
    for cat in sorted(by_cat.keys()):
        result[cat] = aggregate_answerable(by_cat[cat], ks)

    return result


# -- 玩具案例公式验证 --


def verify_toy_case() -> dict[str, Any]:
    """使用手算案例验证指标公式正确性。

    包含 answerable 和 no-answer 查询的分母互不污染验证。
    """
    # -- 可回答查询 --
    relevant = ["C01", "C03", "C05"]
    retrieved = ["C02", "C01", "C04", "C03", "C06", "C05"]

    r3 = recall_at_k(retrieved, relevant, 3)
    r5 = recall_at_k(retrieved, relevant, 5)
    m = mrr(retrieved, relevant)

    expected_r3 = 1 / 3
    expected_r5 = 2 / 3
    expected_mrr = 0.5

    # -- 无答案查询：检索返回了结果 → false_positive=true --
    na_metrics = compute_no_answer_metrics(
        "Q_NA", ["C07", "C08"], [0.6, 0.4], 1.5
    )

    # -- 聚合验证：可回答和无答案分母互不污染 --
    ans_agg = aggregate_answerable([
        compute_answerable_metrics("Q1", retrieved, relevant, 1.0),
    ])
    na_agg = aggregate_no_answer([na_metrics])

    return {
        # 可回答公式验证
        "recall@3": round(r3, 4),
        "recall@3_expected": round(expected_r3, 4),
        "recall@3_correct": round(r3, 4) == round(expected_r3, 4),
        "recall@5": round(r5, 4),
        "recall@5_expected": round(expected_r5, 4),
        "recall@5_correct": round(r5, 4) == round(expected_r5, 4),
        "mrr": round(m, 4),
        "mrr_expected": expected_mrr,
        "mrr_correct": round(m, 4) == round(expected_mrr, 4),
        # no-answer 验证
        "no_answer_false_positive": na_metrics["false_positive"],
        "no_answer_abstained": na_metrics["abstained"],
        "no_answer_fp_expected": True,
        "no_answer_fp_correct": na_metrics["false_positive"] is True,
        # 分母互不污染
        "answerable_count": ans_agg["answerable_count"],
        "answerable_count_expected": 1,
        "answerable_count_correct": ans_agg["answerable_count"] == 1,
        "no_answer_count": na_agg["no_answer_count"],
        "no_answer_count_expected": 1,
        "no_answer_count_correct": na_agg["no_answer_count"] == 1,
        "no_answer_false_positive_rate": na_agg["false_positive_rate"],
        "no_answer_fp_rate_expected": 1.0,
        "no_answer_fp_rate_correct": na_agg["false_positive_rate"] == 1.0,
    }
