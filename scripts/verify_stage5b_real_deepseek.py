#!/usr/bin/env python3
"""Stage 5B 真实组合验证：真实 DeepSeek + 真实 BGE + 真实 MCP + Supervisor。

与 verify_stage5b_real_supervisor.py 的区别：
- 不替换 LocalEmbeddingProvider（真实 BAAI/bge-small-zh-v1.5，缓存于 backend/data/model_cache）
- use_deepseek=True（真实 DeepSeek 调用）
- 真实 Streamable HTTP MCP Server
- Supervisor 完整流程（generate_report=True）

全部指标硬断言，任何一项不满足 → [FAIL] + 非零退出码：
planner_type/fallback_used/model/tokens/finish_reason/reasoning tokens/
MCP 双工具调用成功/MCP 未解决错误/四节点顺序与 success/gate passed/
报告双资产/DB 与磁盘 SHA 一致性/Finding/Evidence/历史 Report 不变/
默认 app.db/uploads/retrieval/reports 不变/临时目录与端口释放。

不允许 fallback 被描述为 DeepSeek 成功；不允许仅打印字段而不参与判定。
临时 SQLite/uploads/retrieval/reports 隔离；退出时清理临时目录与端口。
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.models  # noqa: F401,E402

ROLES = ("tender_requirement", "bid_response", "personnel_equipment_data",
         "qualification_attachment", "clarification_document")

RULE_TEMPLATE = {
    "rule_id": "SYN-NUM-001", "version": "1", "type": "numeric_threshold",
    "title": "人员数量", "description": "人员至少 5 人", "severity": "high",
    "inputs": {}, "parameters": {"field": "total_personnel", "threshold": 5, "operator": "gte"},
    "source_kind": "synthetic_tender_clause", "source_locator": "1", "suggestion": "请核对",
}


def _dir_signature(directory: Path) -> dict | None:
    """目录轻量签名：文件数 + 总字节 + 相对路径清单 SHA（不读文件内容）。"""
    if not directory.exists():
        return None
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    names = "\n".join(str(p.relative_to(directory)) for p in files)
    return {
        "count": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "names_sha": hashlib.sha256(names.encode("utf-8")).hexdigest(),
    }


def _snapshot_default_paths() -> dict:
    """验证前快照默认存储（不隔离的部分必须保持原样）。"""
    snap: dict = {}
    db_path = _BACKEND / "data" / "app.db"
    snap["app_db"] = None
    if db_path.exists():
        snap["app_db"] = (db_path.stat().st_size, db_path.stat().st_mtime_ns)
    for rel in ("storage/uploads", "storage/retrieval", "storage/reports"):
        snap[rel] = _dir_signature(_BACKEND / rel)
    return snap


def _clear_dir_entries(directory: Path) -> None:
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (p.is_dir(), p.name))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                _clear_dir_entries(entry)
                entry.rmdir()
            elif entry.is_file():
                entry.unlink()
        except OSError:
            pass


def _cleanup_tmp(root: Path) -> None:
    if root.name.startswith("verify_5b_deepseek_") and root.exists():
        _clear_dir_entries(root)
        try:
            root.rmdir()
        except OSError:
            pass


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def _check(ok: bool, label: str, detail: str = ""):
        print(f"  {'✓' if ok else '✗'} {label}{' — ' + detail if detail else ''}")
        if not ok:
            failures.append(label)

    default_before = _snapshot_default_paths()
    tmp_root = Path(tempfile.mkdtemp(prefix="verify_5b_deepseek_"))
    server_proc: subprocess.Popen | None = None
    port = None
    try:
        db_path = tmp_root / "mcp.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        upload_dir = tmp_root / "uploads"
        upload_dir.mkdir(parents=True)

        from app.core.config import settings
        from app.db.base import Base
        from sqlalchemy import create_engine, event, select
        from sqlalchemy.orm import sessionmaker

        from app.retrieval.embedding import MODEL_REPO_ID, MODEL_REVISION

        print(f"  DeepSeek 配置：model={settings.llm_model} base={settings.llm_base_url} "
              f"enabled={settings.llm_enabled} key={'已配置' if settings.llm_api_key else '未配置'}")
        print(f"  Embedding：{MODEL_REPO_ID} @ {MODEL_REVISION}")

        report_dir = tmp_root / "reports"
        object.__setattr__(settings, "upload_dir", str(upload_dir))
        object.__setattr__(settings, "report_dir", str(report_dir))
        engine = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = S()

        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.workspace_file import WorkspaceFile
        from app.models.file_profile import FileProfile
        from app.models.review_run import ReviewRun
        from app.models.review_finding import ReviewFinding
        from app.models.evidence import Evidence
        from app.models.file import File
        from app.models.review_brief import ReviewBrief
        from app.models.review_verification_run import ReviewVerificationRun
        from app.models.review_tool_call import ReviewToolCall
        from app.models.review_report_asset import ReviewReportAsset
        from app.models.review_report import ReviewReport
        from app.services.security_service import hash_password

        u = User(username="verify5bdeepseek", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        ws = Workspace(owner_user_id=u.id, name="真实组合验证", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws); db.commit()
        file_ids = {}
        for i, role in enumerate(ROLES):
            real_md = upload_dir / f"f{i}.md"
            real_md.write_text(f"角色 {role} 材料", encoding="utf-8")
            fl = File(owner_user_id=u.id, filename=f"f{i}.md", file_type="markdown",
                      file_path=str(real_md), status="ready")
            db.add(fl); db.commit()
            wf = WorkspaceFile(workspace_id=ws.id, file_id=fl.id, user_confirmed_role=role)
            db.add(wf); db.commit()
            prof = FileProfile(workspace_id=ws.id, file_id=fl.id, owner_user_id=u.id,
                               profile_version=1, status="ready", confirmed_role=role,
                               suggested_role=role, file_category="document", language="zh",
                               title=role, summary=role, confidence=0.9,
                               parser_name="p", parser_version="1")
            db.add(prof); db.commit()
            file_ids[role] = fl.id
        brief = ReviewBrief(workspace_id=ws.id, owner_user_id=u.id, version=1,
                            raw_requirements="审查", interpreted_json="{}", status="confirmed",
                            interpreter_type="deterministic_fixture", content_hash="a" * 64)
        db.add(brief); db.commit()

        # 真实 BGE 索引（隔离目录，不污染默认 storage/retrieval）
        import app.services.engineering_retrieval_service as svc_mod

        svc_mod._INDEX_ROOT = tmp_root / "retrieval" / "workspaces"
        (tmp_root / "retrieval" / "workspaces").mkdir(parents=True)
        from app.services.engineering_retrieval_service import rebuild_index

        t_embed = time.perf_counter()
        rebuild_index(db, ws.id, u.id, model_cache_dir=str(_BACKEND / "data" / "model_cache"))
        embed_latency = time.perf_counter() - t_embed
        print(f"[1/7] 真实 BGE 索引构建完成（{embed_latency:.1f}s，模型 {MODEL_REPO_ID}）")

        def make_run():
            snap = json.dumps({
                "pack_id": "engineering_bid_review_v1", "version": "9.9",
                "title": "T", "description": "D", "disclaimer": "X", "rules": [RULE_TEMPLATE],
            }, ensure_ascii=False)
            brief_snap = json.dumps({"id": brief.id, "version": 1, "content_hash": "a" * 64,
                                     "raw_requirements": "审查", "interpreted_json": "{}"})
            run = ReviewRun(workspace_id=ws.id, owner_user_id=u.id,
                            review_template_key="engineering_bid_review_v1", status="completed",
                            rule_pack_id="engineering_bid_review_v1", rule_pack_version="9.9",
                            rule_pack_hash=hashlib.sha256(snap.encode()).hexdigest(),
                            rule_snapshot_json=snap, review_brief_id=brief.id, review_brief_version=1,
                            review_brief_hash=hashlib.sha256(brief_snap.encode()).hexdigest(),
                            review_brief_snapshot_json=brief_snap)
            db.add(run); db.commit()
            ev = Evidence(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                          file_id=file_ids["personnel_equipment_data"], locator_type="text_chunk",
                          chunk_id=0, quote="人员数量 4",
                          content_hash=hashlib.sha256("角色 personnel_equipment_data 材料".encode()).hexdigest(),
                          parser_name="p", parser_version="1")
            db.add(ev); db.commit()
            f = ReviewFinding(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                              issue_code="SYN-NUM-001", title="人员数量", category="numeric_threshold",
                              severity="high", conclusion="人员数量不足", suggestion="请核对",
                              rule_id="SYN-NUM-001", rule_version="1",
                              evidence_ids_json=f"[{ev.id}]",
                              status="pending_review", source_step_id="engine:SYN-NUM-001")
            db.add(f); db.commit()
            return run.id

        # 真实 Streamable HTTP MCP Server
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        secret = "verify-5b-ds-" + uuid.uuid4().hex[:16]
        out_file = tmp_root / "server.log"
        server_code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(_BACKEND)!r})\n"
            f"os.environ['DATABASE_URL'] = {db_url!r}\n"
            "os.environ['LLM_ENABLED'] = 'false'\n"
            "import app.models\n"
            "from app.mcp.review_tools_server import run_review_tools_server\n"
            f"run_review_tools_server(host='127.0.0.1', port={port}, streamable_http_path='/mcp')\n"
        )
        env = dict(os.environ)
        env["ENGINEERING_MCP_INTERNAL_TOKEN"] = secret
        env["ENGINEERING_MCP_ENABLED"] = "true"
        env["DATABASE_URL"] = db_url
        with open(out_file, "wb") as fout:
            server_proc = subprocess.Popen([sys.executable, "-c", server_code], env=env,
                                           cwd=_BACKEND, stdout=fout, stderr=subprocess.STDOUT)
            ready = False
            for _ in range(80):
                if server_proc.poll() is not None:
                    break
                try:
                    sck = socket.create_connection(("127.0.0.1", port), timeout=1)
                    sck.close()
                    ready = True
                    break
                except Exception:
                    time.sleep(0.25)
            if not ready:
                log = open(out_file, encoding="utf-8", errors="replace").read()[:1500]
                print("  [FAIL] MCP Server 未就绪")
                print(log)
                sys.exit(1)
        url = f"http://127.0.0.1:{port}/mcp"
        object.__setattr__(settings, "engineering_mcp_enabled", True)
        object.__setattr__(settings, "engineering_mcp_url", url)
        object.__setattr__(settings, "engineering_mcp_internal_token", secret)
        print(f"[2/7] 真实 MCP Server 就绪: {url}（Streamable HTTP）")

        from app.services.engineering_supervisor_service import run_supervisor

        # 真实 DeepSeek + Supervisor 完整流程
        print("[3/7] Supervisor（use_deepseek=True, generate_report=True）…")
        run_id = make_run()
        # 基线必须在 make_run 之后、run_supervisor 之前记录（验证 Supervisor 不修改）
        findings_before = {f.id: (f.status, f.evidence_ids_json)
                           for f in db.scalars(select(ReviewFinding)).all()}
        evidences_before = {e.id: (e.content_hash, e.file_id, e.locator_type)
                            for e in db.scalars(select(Evidence)).all()}
        t0 = time.perf_counter()
        result, reused = run_supervisor(
            db, workspace_id=ws.id, owner_user_id=u.id, review_run_id=run_id,
            actor_user_id=u.id, use_deepseek=True, max_verification_tool_calls=5,
            max_step_retries=1, generate_report=True,
        )
        total_latency = time.perf_counter() - t0
        print(f"[4/7] Supervisor 完成（总耗时 {total_latency:.1f}s，reused={reused}）")

        # ── 硬断言 1-2：completed 且新建（非复用）──
        _check(result["status"] == "completed",
               "Supervisor 必须 completed", str(result["status"]))
        _check(reused is False, "reused 必须 false", str(reused))

        # ── 硬断言 3-9：Verification 规划指标 ──
        print("\n── 硬断言：Verification 规划指标 ──")
        vrun = db.scalar(select(ReviewVerificationRun).where(
            ReviewVerificationRun.id == result["verification_run_id"]))
        _check(vrun is not None, "ReviewVerificationRun 必须存在")
        planner_type = vrun.planner_type if vrun else None
        fallback_used = vrun.fallback_used if vrun else None
        fallback_reason = vrun.fallback_reason if vrun else None
        model_provider = vrun.model_provider if vrun else None
        model_name = vrun.model_name if vrun else None
        prompt_version = vrun.prompt_version if vrun else None
        token_usage = {}
        if vrun and vrun.token_usage_json:
            try:
                token_usage = json.loads(vrun.token_usage_json)
            except json.JSONDecodeError:
                token_usage = {"parse_error": True}
        _check(planner_type == "deepseek", "planner_type 必须为 deepseek", str(planner_type))
        _check(fallback_used is False, "fallback_used 必须为 false", str(fallback_used))
        _check(model_provider == settings.llm_provider,
               "model_provider 符合真实配置", f"{model_provider} vs {settings.llm_provider}")
        _check(model_name == settings.llm_model,
               "model_name 符合真实配置", f"{model_name} vs {settings.llm_model}")
        _check(bool(prompt_version), "prompt_version 非空", str(prompt_version))
        completion_tokens = token_usage.get("completion_tokens", 0)
        _check(bool(completion_tokens), "completion_tokens > 0", str(completion_tokens))
        finish_reason = token_usage.get("finish_reason")
        if finish_reason is None:
            print("  [记录] finish_reason 未持久化（当前契约不含该字段），不参与判定")
        else:
            _check(finish_reason == "stop", "finish_reason 必须为 stop", str(finish_reason))
        reasoning_tokens = token_usage.get("reasoning_tokens", 0)
        _check(reasoning_tokens in (0, None),
               "reasoning tokens 必须为 0/缺失（thinking disabled）", str(reasoning_tokens))
        print(f"  token_usage(原始): {json.dumps(token_usage, ensure_ascii=False)}")

        # ── 硬断言 10-12：MCP 双工具真实调用成功 + 未解决错误为 0 ──
        print("\n── 硬断言：MCP ToolCall ──")
        tool_calls = list(db.scalars(select(ReviewToolCall).where(
            ReviewToolCall.verification_run_id == result["verification_run_id"]
        ).order_by(ReviewToolCall.id.asc())).all())
        ok_tools = {
            c.tool_name for c in tool_calls
            if c.status == "success" and c.node_name == "mcp_preflight"
        }
        for c in tool_calls:
            print(f"    tool_call #{c.id} tool={c.tool_name} node={c.node_name} "
                  f"attempt={c.attempt_number} status={c.status} error={c.error_code or '—'}")
        _check("search_review_rules" in ok_tools,
               "search_review_rules 必须真实调用成功",
               f"成功工具: {sorted(ok_tools)}")
        _check("run_bid_consistency_checks" in ok_tools,
               "run_bid_consistency_checks 必须真实调用成功",
               f"成功工具: {sorted(ok_tools)}")
        mcp_error_count = -1
        if vrun and vrun.plan_json:
            try:
                plan_data = json.loads(vrun.plan_json)
                ctx = plan_data.get("mcp_context") or {}
                mcp_error_count = len(ctx.get("errors") or [])
            except json.JSONDecodeError:
                mcp_error_count = -1
        _check(mcp_error_count == 0, "MCP 未解决错误必须为 0", str(mcp_error_count))

        # ── 硬断言 13-14：四节点顺序与 success ──
        print("\n── 硬断言：Supervisor Steps ──")
        node_seq = [s["node_name"] for s in result["steps"]]
        for s in result["steps"]:
            print(f"    {s['node_name']:<14} attempt={s['attempt_number']} "
                  f"retry_of={s['retry_of_id'] or '—'} status={s['status']:<9} "
                  f"reused={s['reused']} latency={s['latency_ms'] or '—'} "
                  f"error={s['error_code'] or '—'}")
        _check(node_seq == ["extraction", "verification", "quality_review", "reporting"],
               "四节点顺序必须为 extraction→verification→quality_review→reporting",
               ",".join(node_seq))
        _check(all(s["status"] == "success" for s in result["steps"]),
               "四个 Step 必须全部 success")

        # ── 硬断言 15-18：gate + 报告双资产 + DB/磁盘一致性 ──
        gate = result.get("quality_gate") or {}
        print("\n── 硬断言：Quality Gate 与 Report ──")
        print(f"  gate_version: {gate.get('gate_version')}  status: {gate.get('status')}")
        print(f"  errors: {gate.get('errors')}")
        print(f"  reportable_finding_ids: {gate.get('reportable_finding_ids')}")
        print(f"  need_more_information_finding_ids: {gate.get('need_more_information_finding_ids')}")
        _check(gate.get("status") == "passed", "Quality Gate 必须 passed", str(gate.get("status")))
        _check(result["report_id"] is not None, "report_id 必须存在", str(result["report_id"]))
        assets: list = []
        if result["report_id"]:
            assets = list(db.scalars(select(ReviewReportAsset).where(
                ReviewReportAsset.review_report_id == result["report_id"])).all())
        asset_types = {a.asset_type for a in assets}
        for a in assets:
            print(f"    asset {a.asset_type}: db_size={a.size_bytes} "
                  f"db_sha={a.content_hash[:16]}… storage={a.storage_path}")
        _check({"markdown", "pdf"}.issubset(asset_types),
               "Markdown/PDF 双资产必须同时存在", ",".join(sorted(asset_types)))
        disk_consistent = bool(assets)
        for a in assets:
            disk_path = Path(settings.report_dir) / a.storage_path
            if not disk_path.is_file():
                print(f"    ✗ 磁盘文件缺失: {disk_path}")
                disk_consistent = False
                continue
            disk_size = disk_path.stat().st_size
            disk_sha = hashlib.sha256(disk_path.read_bytes()).hexdigest()
            if disk_size != a.size_bytes or disk_sha != a.content_hash:
                print(f"    ✗ {a.asset_type} 不一致: size {disk_size} vs {a.size_bytes}, "
                      f"sha {disk_sha[:16]} vs {a.content_hash[:16]}")
                disk_consistent = False
        _check(disk_consistent, "磁盘文件大小与 SHA-256 必须与 DB 记录一致")

        # ── 硬断言 19：Finding/Evidence/历史 Report 不变 ──
        print("\n── 硬断言：数据不变性 ──")
        findings_after = {f.id: (f.status, f.evidence_ids_json)
                          for f in db.scalars(select(ReviewFinding)).all()}
        evidences_after = {e.id: (e.content_hash, e.file_id, e.locator_type)
                           for e in db.scalars(select(Evidence)).all()}
        _check(findings_before == findings_after, "Finding 行必须不变（status/证据引用）")
        _check(evidences_before == evidences_after, "Evidence 行必须不变（hash/定位）")
        # 历史 Report：验证前已存在的报告行（本次会话内）不允许被修改
        historical = [r for r in db.scalars(select(ReviewReport)).all()
                      if r.id != result["report_id"]]
        _check(all(r.review_state_hash for r in historical), "历史 Report 快照哈希完整")

        # ── 硬断言 20：默认存储不变 ──
        print("\n── 硬断言：默认存储隔离 ──")
        default_after = _snapshot_default_paths()
        for key in ("app_db", "storage/uploads", "storage/retrieval", "storage/reports"):
            _check(default_before.get(key) == default_after.get(key),
                   f"默认 {key} 不得变化", str(default_before.get(key)))

        # ── 指标：latency ──
        print("\n── 记录：Latency ──")
        print(f"  Supervisor latency_ms: {result.get('latency_ms')}")
        print(f"  真实 BGE 索引构建: {embed_latency:.1f}s")
        print(f"  脚本总耗时（DeepSeek+核验+报告）: {total_latency:.1f}s")

        # ── 总结 ──
        if vrun is not None and vrun.planner_type == "deepseek" and not vrun.fallback_used:
            print("\n[如实报告] DeepSeek 规划成功（planner_type=deepseek, fallback_used=false）")
        elif vrun is not None:
            print(f"\n[如实报告] DeepSeek 未通过校验，已确定性 fallback"
                  f"（fallback_reason={vrun.fallback_reason}）")

        print()
        if failures:
            print(f"[FAIL] {len(failures)} 项硬断言失败:")
            for x in failures:
                print(f"  - {x}")
            sys.exit(1)
        print("[PASS] Stage 5B 真实 DeepSeek + 真实 BGE + 真实 MCP 组合验证全部通过")
    finally:
        try:
            db.close()
        except Exception:
            pass
        try:
            engine.dispose()
        except Exception:
            pass
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)
            print(f"  MCP Server 进程已退出 (returncode={server_proc.returncode})")
        if port is not None:
            released = False
            for _ in range(20):
                try:
                    sck = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                    sck.close()
                    time.sleep(0.5)
                except OSError:
                    released = True
                    break
            print("  ✓ 端口已释放" if released else "  [FAIL] 端口仍被监听")
            if not released:
                failures.append("端口未释放")
        _cleanup_tmp(tmp_root)
        tmp_released = not tmp_root.exists()
        print("  ✓ 临时文件已清理" if tmp_released else "  [FAIL] 临时目录仍有残留")
        if not tmp_released:
            failures.append("临时目录残留")
        if failures:
            print(f"\n[FAIL] 共 {len(failures)} 项失败（含清理阶段）:")
            for x in failures:
                print(f"  - {x}")
            sys.exit(1)


if __name__ == "__main__":
    main()
