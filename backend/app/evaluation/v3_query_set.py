"""V3 检索评测查询集加载与校验。"""

import hashlib
import json
from pathlib import Path
from typing import Any


class QuerySetError(Exception):
    """查询集加载或校验失败。"""


def load_query_set(query_path: Path) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """从 JSON 文件加载查询集。

    校验：查询数量、必需字段、split 分布、answerable 约束、chunk_id 格式。

    返回：(queries, file_sha256, raw_data)
    """
    if not query_path.exists():
        raise QuerySetError(f"查询集文件不存在: {query_path}")

    raw_text = query_path.read_text("utf-8")
    file_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    data = json.loads(raw_text)

    queries = data.get("queries", [])
    if not queries:
        raise QuerySetError("查询集为空")

    total = len(queries)
    if not (30 <= total <= 50):
        raise QuerySetError(f"查询总数 {total} 不在 30～50 范围内")

    seen_ids: set[str] = set()
    answerable_count = 0
    no_answer_count = 0
    dev_count = 0
    test_count = 0

    for q in queries:
        qid = q.get("query_id", "")
        if not qid:
            raise QuerySetError("查询缺少 query_id")
        if qid in seen_ids:
            raise QuerySetError(f"查询 ID 重复: {qid}")
        seen_ids.add(qid)

        if not q.get("query_text"):
            raise QuerySetError(f"{qid}: query_text 为空")

        split = q.get("split", "")
        if split not in ("dev", "test"):
            raise QuerySetError(f"{qid}: split 必须是 dev 或 test")
        if split == "dev":
            dev_count += 1
        else:
            test_count += 1

        answerable = q.get("answerable")
        if answerable is None:
            raise QuerySetError(f"{qid}: 缺少 answerable 字段")

        chunk_ids = q.get("relevant_chunk_ids", [])

        if answerable:
            answerable_count += 1
            if not chunk_ids:
                raise QuerySetError(
                    f"{qid}: answerable=true 但 relevant_chunk_ids 为空"
                )
            for cid in chunk_ids:
                if not cid.startswith("C") or not cid[1:].isdigit():
                    raise QuerySetError(f"{qid}: 无效 chunk_id 格式: {cid}")
        else:
            no_answer_count += 1
            if chunk_ids:
                raise QuerySetError(
                    f"{qid}: answerable=false 但 relevant_chunk_ids 非空"
                )

    if dev_count < 10:
        raise QuerySetError(f"开发集查询数量 {dev_count} 过少")
    if test_count < 10:
        raise QuerySetError(f"测试集查询数量 {test_count} 过少")
    if no_answer_count < 4:
        raise QuerySetError(
            f"无答案查询数量 {no_answer_count} 不足（至少需要 4 条）"
        )

    dev_na = sum(1 for q in queries if q["split"] == "dev" and not q["answerable"])
    test_na = sum(1 for q in queries if q["split"] == "test" and not q["answerable"])
    if dev_na < 2:
        raise QuerySetError(f"开发集无答案查询 {dev_na} 不足（至少 2 条）")
    if test_na < 2:
        raise QuerySetError(f"测试集无答案查询 {test_na} 不足（至少 2 条）")

    return queries, file_sha256, data
