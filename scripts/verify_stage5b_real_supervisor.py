#!/usr/bin/env python3
"""Stage 5B 真实验证：Engineering Supervisor 编排（真实 Streamable HTTP MCP）。

流程：
    1. 临时 SQLite + uploads/retrieval/reports；不污染 app.db
    2. 真实 Streamable HTTP MCP + 真实 Supervisor service（FakeEmbedding 检索）
    3. 验证 gate 阻断路径与 gate 通过路径
    4. 验证 MCP 暂时故障只重试 verification；MCP 永久故障 → needs_human
    5. 验证失败时不生成报告、通过时生成/复用报告
    6. 验证 Finding/Evidence 未被 Supervisor 自动修改；历史 Report/资产 SHA 不变
    7. TestClient 验证 Supervisor 完整 service/API（201/200 幂等、列表、steps、404、403）
    8. 进程退出、端口释放、临时目录安全清理

说明：planner 为 deterministic；未调用 DeepSeek；检索用 FakeEmbedding
（真实 BGE 组合验证由单独 DeepSeek 脚本阶段执行）。
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
    if root.name.startswith("verify_5b_") and root.exists():
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

    tmp_root = Path(tempfile.mkdtemp(prefix="verify_5b_"))
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
        from app.models.review_report import ReviewReport
        from app.models.evidence import Evidence
        from app.models.file import File
        from app.models.review_brief import ReviewBrief
        from app.services.security_service import hash_password

        u = User(username="verify5b", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        ws = Workspace(owner_user_id=u.id, name="验证工程", workspace_type="engineering",
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

        # FakeEmbedding 检索隔离
        import app.services.engineering_retrieval_service as svc_mod
        from app.retrieval.embedding import FakeEmbeddingProvider

        svc_mod._INDEX_ROOT = tmp_root / "retrieval" / "workspaces"
        (tmp_root / "retrieval" / "workspaces").mkdir(parents=True)
        svc_mod.LocalEmbeddingProvider = lambda *a, **kw: FakeEmbeddingProvider(dimension=512, seed=42)
        from app.services.engineering_retrieval_service import rebuild_index

        def make_run(evidence_json="[1]", source_step_id="engine:SYN-NUM-001"):
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
            if evidence_json == "[1]":
                evidence_json = f"[{ev.id}]"
            f = ReviewFinding(review_run_id=run.id, workspace_id=ws.id, owner_user_id=u.id,
                              issue_code="SYN-NUM-001", title="人员数量", category="numeric_threshold",
                              severity="high", conclusion="人员数量不足", suggestion="请核对",
                              rule_id="SYN-NUM-001", rule_version="1", evidence_ids_json=evidence_json,
                              status="pending_review", source_step_id=source_step_id)
            db.add(f); db.commit()
            return run.id

        rebuild_index(db, ws.id, u.id)
        print("[1/10] 隔离数据库/上传/检索就绪（FakeEmbedding）")

        # ── 真实 MCP Server ──
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        secret = "verify-5b-" + uuid.uuid4().hex[:16]
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
        print(f"[2/10] 真实 MCP Server 就绪: {url}（Streamable HTTP）")

        from app.services.engineering_supervisor_service import run_supervisor

        # ── gate 阻断路径 ──
        print("[3/10] gate 阻断路径（无证据）…")
        bad_run = make_run(evidence_json="[]")
        result, _ = run_supervisor(db, workspace_id=ws.id, owner_user_id=u.id,
                                   review_run_id=bad_run, actor_user_id=u.id,
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=True)
        _check(result["status"] == "needs_human", "gate 失败 → needs_human", result["status"])
        _check("EVIDENCE_MISSING" in result["quality_gate"]["errors"], "EVIDENCE_MISSING")
        _check(result["report_id"] is None, "失败不生成报告")

        # ── gate 通过路径 ──
        print("[4/10] gate 通过路径（generate_report=true）…")
        good_run = make_run()
        result2, _ = run_supervisor(db, workspace_id=ws.id, owner_user_id=u.id,
                                    review_run_id=good_run, actor_user_id=u.id,
                                    use_deepseek=False, max_verification_tool_calls=5,
                                    max_step_retries=1, generate_report=True)
        _check(result2["status"] == "completed", "completed", result2["status"])
        _check(result2["quality_gate"]["status"] == "passed", "gate passed")
        _check(result2["report_id"] is not None, "报告已生成")
        from app.models.review_finding import ReviewFinding as _Finding

        good_finding_id = db.scalar(select(_Finding.id).where(_Finding.review_run_id == good_run))
        reportable_ids = result2["quality_gate"].get("reportable_finding_ids") or []
        _check(
            bool(reportable_ids) and good_finding_id in reportable_ids,
            "reportable 含该 finding",
            f"finding #{good_finding_id}",
        )

        # ── MCP 暂时故障只重试 verification ──
        print("[5/10] MCP 暂时故障只重试 verification …")
        from app.mcp.review_tools_client import ReviewToolsMCPClient as _RC
        from app.mcp.errors import unavailable as _unavail

        real = _RC.call_tool_sync
        state = {"n": 0}

        def flaky(self, tool_name, arguments):
            if tool_name == "search_review_rules" and state["n"] == 0:
                state["n"] += 1
                raise _unavail()
            return real(self, tool_name, arguments)

        _RC.call_tool_sync = flaky
        try:
            retry_run = make_run()
            r3, _ = run_supervisor(db, workspace_id=ws.id, owner_user_id=u.id,
                                   review_run_id=retry_run, actor_user_id=u.id,
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=False)
            _check(r3["status"] == "ready_to_report", "重试后 ready_to_report", r3["status"])
            from app.models.review_tool_call import ReviewToolCall

            mcp_calls = list(db.scalars(select(ReviewToolCall).where(
                ReviewToolCall.verification_run_id == r3["verification_run_id"],
                ReviewToolCall.node_name == "mcp_preflight").order_by(ReviewToolCall.id.asc())).all())
            attempt2 = [c for c in mcp_calls if c.attempt_number == 2]
            _check(bool(attempt2), "Verification 内部 MCP 重试（attempt2）")
            extraction = [s for s in r3["steps"] if s["node_name"] == "extraction"]
            _check(len(extraction) == 1, "extraction 未重跑")
        finally:
            _RC.call_tool_sync = real

        # ── MCP 永久故障 → needs_human ──
        print("[6/10] MCP 永久故障 → needs_human …")
        try:
            _RC.call_tool_sync = lambda self, tool_name, arguments: (
                (_ for _ in ()).throw(_unavail()))
            perm_run = make_run()
            rp, _ = run_supervisor(db, workspace_id=ws.id, owner_user_id=u.id,
                                   review_run_id=perm_run, actor_user_id=u.id,
                                   use_deepseek=False, max_verification_tool_calls=5,
                                   max_step_retries=1, generate_report=False)
            _check(rp["status"] == "needs_human", "MCP 永久故障 → needs_human", rp["status"])
            _check(rp["current_step"] == "verification", "停在 verification 节点", rp["current_step"])
            _check(rp["report_id"] is None, "失败不生成报告")
            _check(rp["error_code"] in ("VERIFICATION_FAILED", "VERIFICATION_MCP_FAILED"),
                   "错误码明确", rp["error_code"])
        finally:
            _RC.call_tool_sync = real

        # ── Finding/Evidence 未被自动修改；历史 Report 不变 ──
        print("[7/10] Finding/Evidence 不变；历史 Report/资产不变 …")
        findings = list(db.scalars(select(ReviewFinding)).all())
        _check(all(f.status == "pending_review" for f in findings), "Finding status 不变")
        _check(db.query(Evidence).count() >= 1, "Evidence 未被删除")
        from app.models.review_report_asset import ReviewReportAsset

        reports_before = {
            (r.id, r.version, r.review_state_hash)
            for r in db.scalars(select(ReviewReport)).all()
        }
        assets_before = {
            (a.id, a.content_hash, a.size_bytes)
            for a in db.scalars(select(ReviewReportAsset)).all()
        }
        immut_run = make_run()
        immut_result, _ = run_supervisor(db, workspace_id=ws.id, owner_user_id=u.id,
                                         review_run_id=immut_run, actor_user_id=u.id,
                                         use_deepseek=False, max_verification_tool_calls=5,
                                         max_step_retries=1, generate_report=True)
        _check(immut_result["report_id"] is not None, "再次通过后生成报告")
        reports_after = {
            (r.id, r.version, r.review_state_hash)
            for r in db.scalars(select(ReviewReport)).all()
        }
        assets_after = {
            (a.id, a.content_hash, a.size_bytes)
            for a in db.scalars(select(ReviewReportAsset)).all()
        }
        _check(reports_before.issubset(reports_after), "历史 Report 行不变（只新增）")
        _check(assets_before.issubset(assets_after), "历史报告资产 SHA 不变（只新增）")

        # ── 幂等 ──
        print("[8/10] 幂等复用 …")
        r4, reused4 = run_supervisor(db, workspace_id=ws.id, owner_user_id=u.id,
                                     review_run_id=good_run, actor_user_id=u.id,
                                     use_deepseek=False, max_verification_tool_calls=5,
                                     max_step_retries=1, generate_report=True)
        _check(reused4 is True, "同输入 reused=true")
        _check(r4["supervisor_run_id"] == result2["supervisor_run_id"], "复用同一 SupervisorRun")

        # ── Supervisor 完整 service/API（TestClient）──
        print("[9/10] Supervisor API（登录/201/200/列表/steps/404/403）…")
        from fastapi.testclient import TestClient

        from app.db.session import get_db
        from app.main import app

        engine_api = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine_api, "connect")
        def _fka(conn, _r):  # noqa: ARG001
            conn.execute("PRAGMA foreign_keys=ON")

        S_api = sessionmaker(bind=engine_api, autoflush=False, autocommit=False)

        def override_get_db():
            api_db = S_api()
            try:
                yield api_db
            finally:
                api_db.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as client:
                csrf_resp = client.get("/api/v2/auth/csrf")
                token = client.cookies.get(settings.csrf_cookie_name)
                login_resp = client.post(
                    "/api/v2/auth/login",
                    headers={settings.csrf_header_name: token},
                    json={"username": "verify5b", "password": "SafePassword!2026"},
                )
                _check(login_resp.status_code == 200, "API 登录成功", login_resp.text[:120])
                api_headers = {settings.csrf_header_name: client.cookies.get(settings.csrf_cookie_name)}

                api_run = make_run()
                api_base = f"/api/v2/workspaces/{ws.id}/review-runs/{api_run}/supervisor-runs"
                api_payload = {
                    "use_deepseek": False, "generate_report": True,
                    "max_verification_tool_calls": 5, "max_step_retries": 1,
                }
                created = client.post(api_base, headers=api_headers, json=api_payload)
                _check(created.status_code == 201, "API 创建 201", str(created.status_code))
                created_body = created.json()
                _check(created_body["reused"] is False, "API 201 reused=false")
                _check(created_body["status"] == "completed" and created_body["report_id"] is not None,
                       "API 运行完成并生成报告")
                repeated = client.post(api_base, headers=api_headers, json=api_payload)
                _check(repeated.status_code == 200 and repeated.json()["reused"] is True,
                       "API 幂等 200 reused=true")
                listing = client.get(api_base, headers=api_headers)
                _check(listing.status_code == 200 and len(listing.json()) == 1, "API 列表")
                steps = client.get(f"{api_base}/{created_body['supervisor_run_id']}/steps",
                                   headers=api_headers)
                nodes = [s["node_name"] for s in steps.json()]
                _check(steps.status_code == 200
                       and nodes == ["extraction", "verification", "quality_review", "reporting"],
                       "API steps 四节点完整", ",".join(nodes))
                wrong = client.get(f"/api/v2/workspaces/{ws.id}/review-runs/999999/supervisor-runs",
                                   headers=api_headers)
                _check(wrong.status_code == 404, "API wrong nesting 404")
                general_ws = Workspace(owner_user_id=u.id, name="通用",
                                       workspace_type="general", status="active")
                api_db = S_api()
                api_db.add(general_ws)
                api_db.commit()
                general_id = general_ws.id
                api_db.close()
                general = client.get(
                    f"/api/v2/workspaces/{general_id}/review-runs/1/supervisor-runs",
                    headers=api_headers)
                _check(general.status_code == 403, "API general 工作区 403")
        finally:
            app.dependency_overrides.clear()
            engine_api.dispose()

        print()
        if failures:
            print(f"[FAIL] {len(failures)} 项验证失败:")
            for x in failures:
                print(f"  - {x}")
            sys.exit(1)
        print("[PASS] Stage 5B 真实 Supervisor 验证全部通过！")
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=5)
            print(f"  MCP Server 进程已退出 (returncode={server_proc.returncode}，Windows terminate 语义)")
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
        _cleanup_tmp(tmp_root)
        print("  ✓ 临时文件已清理")


if __name__ == "__main__":
    main()
