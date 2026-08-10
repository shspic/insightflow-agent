#!/usr/bin/env python3
"""Stage 6A 真实端到端评测：真实 DeepSeek + 真实 BGE + 真实 MCP + Supervisor。

流程：
1. 冻结 engineering-review-v1（数据集版本/SHA/划分/映射）→ dataset_freeze.json
2. 真实 BGE（backend/data/model_cache 离线加载）构建临时索引
3. 真实 Streamable HTTP MCP Server
4. 真实 Supervisor（use_deepseek=True, generate_report=True）完整黄金案例
5. 检索评测：44 条查询 × 真实 BGE 混合检索（answerable/no-answer 隔离）
6. Supervisor 评测：抽取/问题识别/引用定位/content_hash/gate/报告
7. offline BGE 复用验证（离线加载 + 编码不联网）
8. 输出 eval_results/stage6a/{development,validation,test,overall}/ 与 split 映射

硬条件（任一失败 → [FAIL] + 非零退出）：
planner=deepseek、fallback=false、四节点 success、gate passed、
双资产、DB/磁盘 SHA 一致、Finding/Evidence 不变、默认存储不变。

阶段 6A 补修契约：
- pipeline 自动持久化 input_snapshot_json/hash（本脚本不得手工写入 DB）；
- 冻结层 evaluation_split_version 拆 development=20 / validation=8 / test=16；
- 同一输入重复生成映射必须逐字节一致。
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
CASE_DIR = _REPO_ROOT / "examples/engineering_review_v1/golden_case"
QUERY_PATH = CASE_DIR / "retrieval_queries.json"
EVAL_OUT = _REPO_ROOT / "examples/engineering_review_v1/eval_results/stage6a"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dir_signature(rel: str) -> dict | None:
    root = _BACKEND / rel
    if not root.exists():
        return None
    entries = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            entries.append((str(p.relative_to(root)), _sha256(p)))
    names = "\n".join(n for n, _ in entries)
    content = "\n".join(f"{n}\t{d}" for n, d in entries)
    return {"count": len(entries),
            "names_sha": hashlib.sha256(names.encode()).hexdigest(),
            "content_sha": hashlib.sha256(content.encode()).hexdigest()}


def _default_snapshot() -> dict:
    return {"reports": _dir_signature("storage/reports"),
            "retrieval": _dir_signature("storage/retrieval"),
            "uploads": _dir_signature("storage/uploads")}


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
    if root.name.startswith("verify_6a_") and root.exists():
        _clear_dir_entries(root)
        try:
            root.rmdir()
        except OSError:
            pass


def main() -> int:
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

    default_before = _default_snapshot()
    tmp_root = Path(tempfile.mkdtemp(prefix="verify_6a_"))
    server_proc: subprocess.Popen | None = None
    port = None
    try:
        from app.core.config import settings
        from app.db.base import Base
        from sqlalchemy import create_engine, event, select
        from sqlalchemy.orm import sessionmaker

        from app.evaluation.v4_end_to_end_runner import (
            collect_retrieval_eval,
            collect_supervisor_eval,
            extract_fields_from_files,
            freeze_engineering_review_v1,
            write_eval_outputs,
        )
        from app.evaluation.v4_metrics import aggregate_retrieval
        from app.retrieval.embedding import (
            LocalEmbeddingProvider, MODEL_REPO_ID, MODEL_REVISION,
        )
        from app.services.engineering_supervisor_service import run_supervisor

        print(f"  DeepSeek: {settings.llm_model} @ {settings.llm_base_url} "
              f"(key={'有' if settings.llm_api_key else '无'})")
        print(f"  Embedding: {MODEL_REPO_ID} @ {MODEL_REVISION}")

        db_path = tmp_root / "eval.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        upload_dir = tmp_root / "uploads"
        report_dir = tmp_root / "reports"
        upload_dir.mkdir(parents=True)
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
        from app.models.review_report import ReviewReport
        from app.models.review_report_asset import ReviewReportAsset
        from app.services.security_service import hash_password

        # ── 1. 数据集冻结 ──
        print("[1/8] 冻结 engineering-review-v1 …")
        freeze = freeze_engineering_review_v1(CASE_DIR, _REPO_ROOT)
        freeze_dir = EVAL_OUT / "dataset"
        freeze_dir.mkdir(parents=True, exist_ok=True)
        (freeze_dir / "dataset_freeze.json").write_text(
            json.dumps(freeze, ensure_ascii=False, indent=1), encoding="utf-8")
        # split 映射文件（确定性，重复生成必须逐字节一致）
        from app.evaluation.v4_end_to_end_runner import (
            SPLIT_MAPPING_FILE_NAME,
            compute_evaluation_split_mapping,
            split_mapping_document,
        )

        queries_raw = json.loads(QUERY_PATH.read_text(encoding="utf-8"))["queries"]
        mapping = compute_evaluation_split_mapping(queries_raw)
        mapping_doc = split_mapping_document(mapping)
        mapping_sha = hashlib.sha256(mapping_doc.encode("utf-8")).hexdigest()
        regen_doc = split_mapping_document(
            compute_evaluation_split_mapping(queries_raw))
        _check(mapping_doc == regen_doc, "split 映射重复生成逐字节一致")
        _check(mapping_sha == freeze["split_mapping"]["sha256"],
               "映射 SHA 与冻结一致", mapping_sha[:12])
        (freeze_dir / SPLIT_MAPPING_FILE_NAME).write_text(
            mapping_doc, encoding="utf-8")
        sm = freeze["split_mapping"]
        _check(freeze["splits"]["development"] == 20, "development=20")
        _check(freeze["splits"]["validation"] == 8, "validation=8")
        _check(freeze["splits"]["test"] == 16, "test=16")
        _check(len(sm["development_query_ids"]) == 20, "development query_id 清单=20")
        _check(len(sm["validation_query_ids"]) == 8, "validation query_id 清单=8")
        _check(len(sm["test_query_ids"]) == 16, "test query_id 清单=16")
        print(f"  dataset_version={freeze['dataset_version']} "
              f"split_version={freeze['evaluation_split_version']} "
              f"commit={freeze['git_commit'][:10]} dirty={freeze['git_dirty']}")

        # ── 2. 真实 BGE ──
        print("[2/8] 真实 BGE 索引 …")
        import app.services.engineering_retrieval_service as svc_mod

        svc_mod._INDEX_ROOT = tmp_root / "retrieval" / "workspaces"
        (tmp_root / "retrieval" / "workspaces").mkdir(parents=True)
        provider = LocalEmbeddingProvider(cache_dir=str(_BACKEND / "data" / "model_cache"))
        provider._ensure_loaded()
        from app.services.engineering_retrieval_service import rebuild_index

        t_embed = time.perf_counter()
        u = User(username="stage6a", password_hash=hash_password("SafePassword!2026"),
                 role="user", status="active", must_change_password=False)
        db.add(u); db.commit()
        ws = Workspace(owner_user_id=u.id, name="6A 评测", workspace_type="engineering",
                       review_template_key="engineering_bid_review_v1", status="active")
        db.add(ws); db.commit()
        file_ids = {}
        for i, role in enumerate(ROLES):
            src = CASE_DIR / ("01_合成招标要求.pdf" if role == "tender_requirement" else
                              "02_合成投标响应.pdf" if role == "bid_response" else
                              "03_人员设备清单.xlsx" if role == "personnel_equipment_data" else
                              "04_合成资质附件.pdf" if role == "qualification_attachment" else
                              "05_项目澄清.md")
            dst = upload_dir / f"f{i}{src.suffix}"
            dst.write_bytes(src.read_bytes())
            fl = File(owner_user_id=u.id, filename=src.name, file_type={
                "pdf": "pdf", "xlsx": "xlsx", "md": "markdown"}[src.suffix.lstrip(".")],
                file_path=str(dst), status="ready")
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
        rebuild_index(db, ws.id, u.id, model_cache_dir=str(_BACKEND / "data" / "model_cache"))
        embed_latency = time.perf_counter() - t_embed
        print(f"  真实 BGE 索引完成（{embed_latency:.1f}s）")

        # ── 3. 真实 MCP Server ──
        print("[3/8] 真实 Streamable HTTP MCP …")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        secret = "verify-6a-" + uuid.uuid4().hex[:16]
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
                print("  [FAIL] MCP Server 未就绪")
                print(open(out_file, encoding="utf-8", errors="replace").read()[:1500])
                sys.exit(1)
        url = f"http://127.0.0.1:{port}/mcp"
        object.__setattr__(settings, "engineering_mcp_enabled", True)
        object.__setattr__(settings, "engineering_mcp_url", url)
        object.__setattr__(settings, "engineering_mcp_internal_token", secret)
        print(f"  MCP 就绪: {url}")

        # ── 4. 创建 ReviewRun + 真实 Supervisor ──
        print("[4/8] 真实 Supervisor（DeepSeek + MCP + 四节点）…")
        # 规则快照：从磁盘 YAML 由规则服务加载并规范化
        from app.services.review_rule_service import compute_rule_pack_hash, compute_rule_snapshot, load_rule_pack

        rule_pack = load_rule_pack("engineering_bid_review_v1")
        snap = compute_rule_snapshot(rule_pack)
        brief_snap = json.dumps({"id": brief.id, "version": 1, "content_hash": "a" * 64,
                                 "raw_requirements": "审查", "interpreted_json": "{}"})
        run = ReviewRun(workspace_id=ws.id, owner_user_id=u.id,
                        review_template_key="engineering_bid_review_v1", status="pending",
                        rule_pack_id="engineering_bid_review_v1", rule_pack_version="1.1.0",
                        rule_pack_hash=compute_rule_pack_hash(snap), rule_snapshot_json=snap,
                        review_brief_id=brief.id, review_brief_version=1,
                        review_brief_hash=hashlib.sha256(brief_snap.encode()).hexdigest(),
                        review_brief_snapshot_json=brief_snap)
        db.add(run); db.commit()
        # 先执行一次确定性管道生成 Finding/Evidence（黄金案例真实材料）
        from app.services.engineering_review_pipeline_service import run_engineering_review

        run_engineering_review(db, run=run, workspace=ws, owner_user_id=u.id)
        # input snapshot 契约（阶段 6A）：pipeline 在真实字段抽取完成后自动
        # 持久化规范 JSON + SHA-256。本脚本禁止手工写 input_snapshot_json/hash；
        # 这里只做验证：快照存在、JSON 与哈希一致、必需输入字段在场。
        db.refresh(run)
        _check(run.input_snapshot_json and run.input_snapshot_hash,
               "pipeline 自动持久化 input snapshot（json + hash）")
        _check(
            hashlib.sha256(run.input_snapshot_json.encode("utf-8")).hexdigest()
            == run.input_snapshot_hash,
            "input snapshot JSON 与 hash 一致",
        )
        snap_fields = (json.loads(run.input_snapshot_json) or {}).get("fields") or {}
        _check("bid_response.project_name" in snap_fields
               and "personnel_equipment_data.total_personnel" in snap_fields,
               "快照包含规则所需结构化输入")
        findings_before = {f.id: (f.status, f.evidence_ids_json)
                           for f in db.scalars(select(ReviewFinding)).all()}
        evidences_before = {e.id: (e.content_hash, e.file_id)
                            for e in db.scalars(select(Evidence)).all()}
        t0 = time.perf_counter()
        result, reused = run_supervisor(
            db, workspace_id=ws.id, owner_user_id=u.id, review_run_id=run.id,
            actor_user_id=u.id, use_deepseek=True, max_verification_tool_calls=5,
            max_step_retries=1, generate_report=True,
        )
        supervisor_latency = time.perf_counter() - t0
        print(f"  Supervisor 完成（{supervisor_latency:.1f}s，status={result['status']}，reused={reused}）")

        # ── 硬条件断言 ──
        _check(result["status"] == "completed", "Supervisor completed", str(result["status"]))
        _check(reused is False, "reused=false")
        vrun = db.scalar(select(ReviewVerificationRun).where(
            ReviewVerificationRun.id == result["verification_run_id"]))
        _check(vrun is not None, "VerificationRun 存在")
        if vrun:
            _check(vrun.planner_type == "deepseek", "planner=deepseek", str(vrun.planner_type))
            _check(vrun.fallback_used is False, "fallback=false", str(vrun.fallback_used))
            print(f"  model={vrun.model_provider}/{vrun.model_name} prompt={vrun.prompt_version} "
                  f"tokens={vrun.token_usage_json}")
        steps = result.get("steps", [])
        node_seq = [s["node_name"] for s in steps]
        # reporting 仅在 gate 通过后执行；失败路径预期停在 quality_review
        expected_prefix = ["extraction", "verification", "quality_review"]
        _check(node_seq[:3] == expected_prefix, "前序节点顺序", ",".join(node_seq))
        if "reporting" in node_seq:
            _check(node_seq == ["extraction", "verification", "quality_review", "reporting"],
                   "四节点完整顺序")
        _check(all(s["status"] == "success" for s in steps), "已有节点全部 success",
               f"{len(node_seq)} 个节点")
        gate = result.get("quality_gate") or {}
        if gate.get("status") != "passed":
            print(f"  [调试] gate errors: {gate.get('errors')}")
            for c in (gate.get("checks") or [])[:8]:
                print(f"    check {c.get('check_code')} finding={c.get('finding_id')} "
                      f"evidence={c.get('evidence_id')} retryable={c.get('retryable')} "
                      f"msg={c.get('safe_message')}")
        _check(gate.get("status") == "passed", "gate passed", str(gate.get("status")))
        _check(result["report_id"] is not None, "report_id 存在")
        assets = list(db.scalars(select(ReviewReportAsset).where(
            ReviewReportAsset.review_report_id == result["report_id"])).all())
        _check({a.asset_type for a in assets} == {"markdown", "pdf"}, "双资产")
        disk_ok = True
        for a in assets:
            p = Path(settings.report_dir) / a.storage_path
            if not p.is_file() or p.stat().st_size != a.size_bytes or _sha256(p) != a.content_hash:
                disk_ok = False
        _check(disk_ok, "DB/磁盘 SHA 一致")
        findings_after = {f.id: (f.status, f.evidence_ids_json)
                          for f in db.scalars(select(ReviewFinding)).all()}
        evidences_after = {e.id: (e.content_hash, e.file_id)
                           for e in db.scalars(select(Evidence)).all()}
        _check(findings_before == findings_after, "Finding 不变")
        _check(evidences_before == evidences_after, "Evidence 不变")

        # ── 5. 检索评测（真实 BGE，44 条查询）──
        print("[5/8] 检索评测（真实 BGE 混合检索）…")
        ret = collect_retrieval_eval(
            CASE_DIR, QUERY_PATH,
            encode_query=lambda texts: provider.encode_passages(texts),
            top_k=5,
        )
        ret_metrics = aggregate_retrieval(ret.per_query_answerable, ret.per_query_no_answer)
        print(f"  answerable={ret_metrics['answerable']['answerable_count']} "
              f"recall@3={ret_metrics['answerable']['recall@3_mean']} "
              f"recall@5={ret_metrics['answerable']['recall@5_mean']} "
              f"mrr={ret_metrics['answerable']['mrr_mean']} "
              f"no-answer FP率={ret_metrics['no_answer']['false_positive_rate']}")

        # ── 6. Supervisor 评测指标 ──
        print("[6/8] Supervisor 业务指标 …")
        expected = json.loads((CASE_DIR / "ground_truth.json").read_text(encoding="utf-8"))
        extracted = extract_fields_from_files(db, ws.id, u.id)
        findings = list(db.scalars(select(ReviewFinding).where(
            ReviewFinding.review_run_id == run.id)).all())
        evidences = list(db.scalars(select(Evidence).where(
            Evidence.review_run_id == run.id)).all())
        reports = list(db.scalars(select(ReviewReport)).all())
        sup_metrics = collect_supervisor_eval(
            db, workspace_id=ws.id, owner_user_id=u.id,
            supervisor_result=result, extracted_fields=extracted, expected=expected,
            findings=findings, evidences=evidences, reports=reports,
            report_assets=list(db.scalars(select(ReviewReportAsset)).all()),
        )
        print(f"  字段抽取 F1={sup_metrics['field_extraction']['f1']} "
              f"问题识别 F1={sup_metrics['issue_identification']['f1']} "
              f"引用定位={sup_metrics['citation_locator']['accuracy']} "
              f"content_hash={sup_metrics['content_hash']['accuracy']} "
              f"无证据结论率={sup_metrics['no_evidence_rate']}")

        # ── 7. offline BGE 复用验证 ──
        print("[7/8] offline BGE 复用验证 …")
        offline_ok = False
        try:
            p2 = LocalEmbeddingProvider(cache_dir=str(_BACKEND / "data" / "model_cache"))
            p2._ensure_loaded()
            vecs = p2.encode_passages(["offline 复用验证"])
            offline_ok = vecs.shape == (1, p2.metadata()["dimension"])
        except Exception as exc:
            print(f"  offline 加载失败: {exc}")
        _check(offline_ok, "offline BGE 复用（缓存加载 + 编码成功）")

        # ── 8. 输出全部报告 ──
        print("[8/8] 输出 stage6a 报告 …")
        meta = {
            "dataset_name": "engineering-review-v1", "dataset_version": freeze["dataset_version"],
            "case_id": "SYN-ENG-2026-001",
            **{k: freeze[k] for k in ("files", "manifest.json", "ground_truth.json",
                                      "retrieval_queries.json", "review_brief.json",
                                      "rule_pack", "evaluation_code_sha256", "splits",
                                      "evaluation_split_version", "split_mapping",
                                      "git_commit", "git_branch", "git_dirty",
                                      "python_version", "platform")},
            "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "embedding": {"model_repo_id": MODEL_REPO_ID, "model_revision": MODEL_REVISION},
            "llm": {"model": settings.llm_model, "provider": settings.llm_provider},
            "supervisor_latency_ms": supervisor_latency * 1000,
        }
        failures_out: list[dict] = []
        for q in ret.per_query_answerable:
            if q["recall@5"] < 1.0:
                failures_out.append({
                    "failure_type": "RETRIEVAL_MISS", "manual_failure_category": "RECALL",
                    "item_id": q["query_id"], "detail": f"recall@5={q['recall@5']}"})
        for q in ret.per_query_no_answer:
            if q["false_positive"]:
                failures_out.append({
                    "failure_type": "NO_ANSWER_FALSE_POSITIVE",
                    "manual_failure_category": "NO_ANSWER",
                    "item_id": q["query_id"], "detail": "no-answer 查询返回了结果"})
        for f in findings:
            if not f.evidence_ids_json or f.evidence_ids_json == "[]":
                failures_out.append({
                    "failure_type": "NO_EVIDENCE_FINDING",
                    "manual_failure_category": "EVIDENCE",
                    "item_id": f.issue_code, "detail": "正式问题缺少证据"})

        # 按冻结层 evaluation split 映射划分（development=20 / validation=8 / test=16）
        def _split_aggregate(split_name: str) -> dict:
            per_a = [q for q in ret.per_query_answerable
                     if mapping.get(q["query_id"]) == split_name]
            per_n = [q for q in ret.per_query_no_answer
                     if mapping.get(q["query_id"]) == split_name]
            return aggregate_retrieval(per_a, per_n)

        splits_metrics = {
            "development": _split_aggregate("development"),
            "validation": _split_aggregate("validation"),
            "test": _split_aggregate("test"),
        }
        overall = aggregate_retrieval(ret.per_query_answerable, ret.per_query_no_answer)
        splits_metrics["overall"] = overall
        splits_metrics["supervisor"] = sup_metrics
        val_agg = splits_metrics["validation"]
        _check(val_agg["answerable"]["answerable_count"] == 7
               and val_agg["no_answer"]["no_answer_count"] == 1,
               "validation 指标非空（7 answerable + 1 no-answer）")
        _check(val_agg["answerable"]["recall@3_mean"] is not None,
               "validation recall@3 非空")
        dev_agg = splits_metrics["development"]
        _check(dev_agg["answerable"]["answerable_count"] == 18
               and dev_agg["no_answer"]["no_answer_count"] == 2,
               "development 指标非空（18 answerable + 2 no-answer）")
        print(f"  validation recall@3={val_agg['answerable']['recall@3_mean']} "
              f"recall@5={val_agg['answerable']['recall@5_mean']} "
              f"mrr={val_agg['answerable']['mrr_mean']}")

        for split_name, metrics in splits_metrics.items():
            out_dir = EVAL_OUT / split_name
            write_eval_outputs(out_dir, meta=meta, metrics=metrics, failures=failures_out)
        print(f"  输出目录: {EVAL_OUT}")

        # ── 默认资产不变 ──
        default_after = _default_snapshot()
        for key in ("reports", "retrieval", "uploads"):
            _check(default_before.get(key) == default_after.get(key),
                   f"默认 {key} 不变")

        print()
        if failures:
            print(f"[FAIL] {len(failures)} 项硬条件失败:")
            for x in failures:
                print(f"  - {x}")
            return 1
        print("[PASS] Stage 6A 真实端到端评测全部通过")
        return 0
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
            print(f"  MCP Server 已退出 (returncode={server_proc.returncode})")
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
        print("  ✓ 临时文件已清理" if not tmp_root.exists() else "  [FAIL] 临时目录残留")


if __name__ == "__main__":
    sys.exit(main())
