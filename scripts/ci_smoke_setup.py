#!/usr/bin/env python3
"""CI 浏览器冒烟数据生成脚本（阶段 6C）。

在隔离的临时数据库 + 临时存储中自动创建：
- 两个测试账号（主用户/第二用户，用于跨用户隔离验证）；
- engineering 工作区 + 5 份黄金案例材料（真实文件副本）+ 角色确认 + Profile；
- confirmed ReviewBrief + ReviewRun + 确定性 pipeline（Finding/Evidence）。

不依赖本机 app.db、不依赖 Stage 6B 已准备好的本地项目；
不调用 DeepSeek、不加载真实 BGE（pipeline 为确定性解析，无模型依赖）。

用法（cwd=backend，环境变量 DATABASE_URL/UPLOAD_DIR 等由 CI 或调用方提供）：
    python ../scripts/ci_smoke_setup.py

输出：末尾打印 `WORKSPACE_ID=<id>`，供 CI 注入 Playwright 环境变量。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.models  # noqa: F401,E402
from app.core.config import settings
from app.db.base import Base
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

ROLES = ("tender_requirement", "bid_response", "personnel_equipment_data",
         "qualification_attachment", "clarification_document")
GOLDEN_FILES = {
    "tender_requirement": "01_合成招标要求.pdf",
    "bid_response": "02_合成投标响应.pdf",
    "personnel_equipment_data": "03_人员设备清单.xlsx",
    "qualification_attachment": "04_合成资质附件.pdf",
    "clarification_document": "05_项目澄清.md",
}
CASE_DIR = _REPO_ROOT / "examples" / "engineering_review_v1" / "golden_case"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    import argparse

    parser = argparse.ArgumentParser(description="CI 冒烟数据生成")
    parser.add_argument("--fresh", action="store_true",
                        help="重建数据库 schema（本地重复运行用；CI 全新 runner 不需要）")
    args = parser.parse_args()

    from app.models.file import File
    from app.models.file_profile import FileProfile
    from app.models.review_brief import ReviewBrief
    from app.models.review_run import ReviewRun
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.workspace_file import WorkspaceFile
    from app.services.security_service import hash_password

    upload_root = Path(settings.upload_dir)
    if not upload_root.is_absolute():
        upload_root = (_BACKEND / upload_root).resolve()
    upload_root.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):  # noqa: ARG001
        conn.execute("PRAGMA foreign_keys=ON")

    if args.fresh:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = S()

    # ── 1. 两个测试账号 ──
    primary = User(username="alice_smoke",
                   password_hash=hash_password("SmokePassword!2026"),
                   role="user", status="active", must_change_password=False)
    db.add(primary); db.commit()
    secondary = User(username="bob_smoke",
                     password_hash=hash_password("SmokePassword!2026"),
                     role="user", status="active", must_change_password=False)
    db.add(secondary); db.commit()

    # ── 2. engineering 工作区 + 黄金材料 ──
    ws = Workspace(owner_user_id=primary.id, name="CI 冒烟审查项目",
                   workspace_type="engineering",
                   review_template_key="engineering_bid_review_v1", status="active")
    db.add(ws); db.commit()

    for role in ROLES:
        src = CASE_DIR / GOLDEN_FILES[role]
        dst = upload_root / f"ci_{role}{src.suffix}"
        dst.write_bytes(src.read_bytes())
        fl = File(owner_user_id=primary.id, filename=GOLDEN_FILES[role], file_type={
            "pdf": "pdf", "xlsx": "xlsx", "md": "markdown"}[src.suffix.lstrip(".")],
            file_path=str(dst), status="ready")
        db.add(fl); db.commit()
        db.add(WorkspaceFile(workspace_id=ws.id, file_id=fl.id,
                             user_confirmed_role=role)); db.commit()
        db.add(FileProfile(workspace_id=ws.id, file_id=fl.id, owner_user_id=primary.id,
                           profile_version=1, status="ready", confirmed_role=role,
                           suggested_role=role, file_category="document", language="zh",
                           title=role, summary=role, confidence=0.9,
                           parser_name="ci_setup", parser_version="1")); db.commit()

    # ── 3. ReviewBrief + ReviewRun + 确定性 pipeline ──
    brief = ReviewBrief(workspace_id=ws.id, owner_user_id=primary.id, version=1,
                        raw_requirements="CI 冒烟审查", interpreted_json="{}",
                        status="confirmed", interpreter_type="deterministic_fixture",
                        content_hash="a" * 64)
    db.add(brief); db.commit()

    from app.services.review_rule_service import (
        compute_rule_pack_hash,
        compute_rule_snapshot,
        load_rule_pack,
    )

    rule_pack = load_rule_pack("engineering_bid_review_v1")
    snap = compute_rule_snapshot(rule_pack)
    brief_snap = json.dumps({"id": brief.id, "version": 1, "content_hash": "a" * 64,
                             "raw_requirements": "CI 冒烟审查", "interpreted_json": "{}"})
    run = ReviewRun(workspace_id=ws.id, owner_user_id=primary.id,
                    review_template_key="engineering_bid_review_v1", status="pending",
                    rule_pack_id="engineering_bid_review_v1", rule_pack_version="1.1.0",
                    rule_pack_hash=compute_rule_pack_hash(snap),
                    rule_snapshot_json=snap,
                    review_brief_id=brief.id, review_brief_version=1,
                    review_brief_hash=hashlib.sha256(brief_snap.encode()).hexdigest(),
                    review_brief_snapshot_json=brief_snap)
    db.add(run); db.commit()

    from app.services.engineering_review_pipeline_service import run_engineering_review

    result = run_engineering_review(db, run=run, workspace=ws, owner_user_id=primary.id)
    assert result["status"] == "completed", result
    print(f"冒烟数据就绪：workspace={ws.id} run={run.id} "
          f"findings={result['finding_count']} evidence={result['evidence_count']}")
    print(f"WORKSPACE_ID={ws.id}")
    db.close()
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
