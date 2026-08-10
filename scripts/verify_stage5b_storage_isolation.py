#!/usr/bin/env python3
"""Stage 5B 最终补修：默认运行资产前后摘要对比。

用法：
    python scripts/verify_stage5b_storage_isolation.py snapshot <out.json>
    python scripts/verify_stage5b_storage_isolation.py compare <before.json> <after.json>

对比内容（backend 默认目录）：
- storage/reports：文件数 + 路径清单 SHA + 内容组合 SHA
- storage/retrieval：同上
- storage/uploads：文件数 + 路径清单 SHA + 内容组合 SHA（只读统计，内容大文件用组合 SHA 仍全读）
- data/app.db*（大小 + mtime）
- WORKSPACE_README.md、golden_case/retrieval_queries.json（SHA-256）
- v5a2_uploads_* 数量（%TEMP% 下历史残留，如实计数）

退出码：compare 发现任何差异 → 1；一致 → 0。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dir_snapshot(rel: str) -> dict:
    root = BACKEND / rel
    entries: list[tuple[str, str]] = []
    count = 0
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                count += 1
                entries.append((str(p.relative_to(root)), _file_sha(p)))
    names_blob = "\n".join(name for name, _ in entries)
    content_blob = "\n".join(f"{name}\t{digest}" for name, digest in entries)
    return {
        "count": count,
        "names_sha": hashlib.sha256(names_blob.encode("utf-8")).hexdigest(),
        "content_sha": hashlib.sha256(content_blob.encode("utf-8")).hexdigest(),
    }


def _snapshot() -> dict:
    snap: dict = {}
    for rel in ("storage/reports", "storage/retrieval", "storage/uploads"):
        snap[rel] = _dir_snapshot(rel)
    snap["app_db"] = {}
    for name in ("app.db", "app.db-shm", "app.db-wal"):
        p = BACKEND / "data" / name
        snap["app_db"][name] = (
            (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None
        )
    snap["WORKSPACE_README.md"] = _file_sha(REPO_ROOT / "WORKSPACE_README.md")
    snap["golden_case/retrieval_queries.json"] = _file_sha(
        REPO_ROOT / "examples/engineering_review_v1/golden_case/retrieval_queries.json")
    # v5a2_uploads_* 历史残留（%TEMP% 下，如实计数不归零）
    v5a2 = []
    temp_root = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
    if temp_root.is_dir():
        v5a2 = sorted(p.name for p in temp_root.iterdir() if p.name.startswith("v5a2_uploads_"))
    snap["v5a2_uploads_count"] = len(v5a2)
    snap["v5a2_uploads_names_sha"] = hashlib.sha256(
        "\n".join(v5a2).encode("utf-8")).hexdigest()
    return snap


def _main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "snapshot" and len(sys.argv) == 3:
        data = _snapshot()
        Path(sys.argv[2]).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"snapshot: reports={data['storage/reports']['count']} "
              f"retrieval={data['storage/retrieval']['count']} "
              f"uploads={data['storage/uploads']['count']} "
              f"v5a2_uploads={data['v5a2_uploads_count']}")
        return 0
    if mode == "compare" and len(sys.argv) == 4:
        before = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        after = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        diffs: list[str] = []
        for key in before:
            if before[key] != after.get(key):
                diffs.append(key)
        if diffs:
            print("[FAIL] 默认资产发生变化:")
            for key in diffs:
                print(f"  - {key}: {before[key]} -> {after.get(key)}")
            return 1
        print("[PASS] 默认资产前后一致：reports/retrieval/uploads/app.db/"
              "WORKSPACE_README/retrieval_queries/v5a2_uploads 全部未变")
        print(f"  reports count={after['storage/reports']['count']} "
              f"retrieval count={after['storage/retrieval']['count']} "
              f"uploads count={after['storage/uploads']['count']} "
              f"v5a2_uploads 总数={after['v5a2_uploads_count']}（历史残留，本轮新增应为 0）")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main())
