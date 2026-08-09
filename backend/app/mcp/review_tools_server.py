"""Review Tools MCP Server（阶段 5A-1）。

只暴露两个工具：
- search_review_rules：在工程审查规则包中检索与问题相关的规则
- run_bid_consistency_checks：对已持久化审查数据执行受控一致性检查

安全边界：
- 服务端重新验证 workspace / ReviewRun / owner 归属（不信任客户端传入 owner）
- 仅 engineering workspace 可用
- Host/Origin 校验 + 内部 token 校验（中间件）
- 输出不泄露磁盘路径、traceback、token
- 检查结果 candidate_only=true，不修改 Finding/Evidence/Report
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.context import Context
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.mcp.capability_tokens import verify_capability_token
from app.mcp.errors import MCPError, MCPErrorCode, business_invalid, tool_error
from app.mcp.schemas import (
    ConsistencyCheck,
    RunBidConsistencyChecksInput,
    RunBidConsistencyChecksOutput,
    SearchReviewRulesInput,
    SearchReviewRulesOutput,
    SearchReviewRulesResultItem,
)
from app.models.evidence import Evidence as EvidenceModel
from app.models.review_finding import ReviewFinding
from app.models.review_run import ReviewRun
from app.models.workspace import Workspace
from app.services.review_rule_service import RuleLoadError, load_rule_pack_from_snapshot

ALLOWED_MCP_TOOL_NAMES = frozenset(
    {"search_review_rules", "run_bid_consistency_checks"}
)

# 阶段 6D-1：绑定与 Host 校验的明确允许列表（禁止 * 全通配）
# - 默认只允许 localhost 系绑定与 Host 头
# - 只有显式启用"容器内部绑定"（ENGINEERING_MCP_ALLOW_CONTAINER_BIND=true）
#   才额外允许 Docker 内部网络主机名 mcp（docker-compose.prod.yml 服务名）
LOCALHOST_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MCP_CONTAINER_INTERNAL_HOST = "mcp"
_MCP_ALLOWED_HOSTS_LOCALHOST = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_MCP_ALLOWED_ORIGINS_LOCALHOST = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def build_transport_security(allow_container_bind: bool = False) -> TransportSecuritySettings:
    """构建传输安全设置：Host/Origin 只使用明确允许列表，不用 * 全通配。"""
    allowed_hosts = list(_MCP_ALLOWED_HOSTS_LOCALHOST)
    if allow_container_bind:
        allowed_hosts.append(f"{MCP_CONTAINER_INTERNAL_HOST}:*")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=list(_MCP_ALLOWED_ORIGINS_LOCALHOST),
    )


class FaultInjector:
    """受控瞬时故障注入（仅真实评测脚本显式启用，默认完全关闭）。

    阶段 6A 局部重试真实评测：对指定工具的前 N 次调用返回
    ENGINEERING_MCP_UNAVAILABLE（可重试错误码），随后恢复正常。
    环境变量：ENGINEERING_MCP_FAULT_TOOL（工具名）、
    ENGINEERING_MCP_FAULT_FIRST_N（前 N 次调用失败，默认 1）。
    未设置环境变量时行为与不注入完全一致，不影响正常部署。
    """

    def __init__(self) -> None:
        self._tool = os.environ.get("ENGINEERING_MCP_FAULT_TOOL", "")
        self._remaining = 0
        if self._tool:
            raw = os.environ.get("ENGINEERING_MCP_FAULT_FIRST_N", "1")
            try:
                self._remaining = max(1, int(raw))
            except ValueError:
                self._remaining = 1

    @property
    def enabled(self) -> bool:
        return bool(self._tool)

    def should_fail(self, tool_name: str) -> bool:
        if not self._tool or tool_name != self._tool:
            return False
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True


_FAULT_INJECTOR = FaultInjector()

TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_review_rules": "在当前工程审查规则包中检索与问题相关的规则",
    "run_bid_consistency_checks": "对已持久化的工程审查数据执行受控一致性检查",
}

# 检查代码白名单（防止任意表达式/文件路径/URL）
BID_CHECK_CODES = frozenset({
    "finding_evidence_binding",
    "finding_rule_exists",
    "evidence_locator_valid",
    "finding_severity_matches_rule",
    "cross_finding_evidence_duplication",
})


# ── 业务辅助 ────────────────────────────────────────────────────────


def _resolve_owned_run(
    db: Session, workspace_id: int, review_run_id: int, actor_user_id: int
) -> tuple[Workspace, ReviewRun]:
    """服务端解析并验证 workspace 与 ReviewRun 归属（调用者身份隔离）。

    actor_user_id 来自认证后的 AccessToken.subject（官方 AuthContext），
    绝不信任工具参数中明文传入的 owner_user_id。
    必须满足 Workspace.owner_user_id == actor_user_id 且
    ReviewRun.owner_user_id == workspace.owner_user_id，否则统一安全错误。
    """
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.status == "active",
        )
    )
    if workspace is None:
        raise business_invalid("工作区不存在或无权访问")
    if workspace.workspace_type != "engineering":
        raise business_invalid("仅 engineering 工作区支持 MCP 审查工具")
    if workspace.owner_user_id != actor_user_id:
        raise business_invalid("工作区不存在或无权访问")

    run = db.scalar(
        select(ReviewRun).where(
            ReviewRun.id == review_run_id,
            ReviewRun.workspace_id == workspace_id,
            ReviewRun.owner_user_id == workspace.owner_user_id,
        )
    )
    if run is None:
        raise business_invalid("审查任务不存在或无权访问")
    return workspace, run


def _actor_user_id_or_error() -> int:
    """从官方 AuthContext 读取认证后的 subject（真实 user_id）。"""
    access = get_access_token()
    if access is None or not access.subject or not access.subject.isdigit():
        raise business_invalid("调用者身份无效")
    return int(access.subject)


def _safe_rule_summary(rule: Any) -> SearchReviewRulesResultItem:
    return SearchReviewRulesResultItem(
        rank=1,
        rule_id=rule.rule_id,
        title=rule.title,
        description=rule.description[:2000],
        severity=rule.severity,
        evidence_required=rule.type == "evidence_required",
        source_hash=hashlib.sha256(
            f"{rule.rule_id}:{rule.version}".encode("utf-8")
        ).hexdigest()[:16],
    )


def _run_search_review_rules(
    db: Session, payload: SearchReviewRulesInput, actor_user_id: int
) -> SearchReviewRulesOutput:
    start = time.perf_counter()
    workspace, run = _resolve_owned_run(db, payload.workspace_id, payload.review_run_id, actor_user_id)

    # 事实来源 = ReviewRun 固化的不可变规则快照（不读磁盘最新规则文件）
    try:
        pack = load_rule_pack_from_snapshot(run.rule_snapshot_json, run.rule_pack_hash)
    except RuleLoadError as exc:
        raise business_invalid("审查任务规则快照不可用") from exc

    query = payload.query.lower()
    scored: list[tuple[int, Any]] = []
    for rule in pack.rules:
        score = 0
        if query in rule.rule_id.lower():
            score += 3
        if query in rule.title.lower():
            score += 2
        if query in rule.description.lower():
            score += 1
        if query in (rule.source_locator or "").lower():
            score += 1
        if score > 0:
            scored.append((score, rule))
    scored.sort(key=lambda x: (-x[0], x[1].rule_id))

    results = []
    for rank, (_score, rule) in enumerate(scored[: payload.top_k], start=1):
        item = _safe_rule_summary(rule)
        item.rank = rank
        results.append(item)

    latency_ms = int((time.perf_counter() - start) * 1000)
    return SearchReviewRulesOutput(
        request_id=payload.request_id,
        latency_ms=latency_ms,
        rule_pack_id=run.rule_pack_id,
        rule_pack_version=run.rule_pack_version,
        results=results,
        warnings=[],
    )


def _run_bid_consistency_checks(
    db: Session, payload: RunBidConsistencyChecksInput, actor_user_id: int
) -> RunBidConsistencyChecksOutput:
    start = time.perf_counter()
    workspace, run = _resolve_owned_run(db, payload.workspace_id, payload.review_run_id, actor_user_id)

    findings = list(
        db.scalars(
            select(ReviewFinding)
            .where(ReviewFinding.review_run_id == run.id)
            .order_by(ReviewFinding.id.asc())
        ).all()
    )
    evidence_records = list(
        db.scalars(
            select(EvidenceModel).where(EvidenceModel.review_run_id == run.id)
        ).all()
    )
    evidence_by_id = {e.id: e for e in evidence_records}

    checks: list[ConsistencyCheck] = []
    warnings: list[str] = []

    # 1. finding_evidence_binding：Finding 引用的 evidence id 必须存在
    missing_binding: list[int] = []
    for finding in findings:
        try:
            ids = [int(x) for x in json.loads(finding.evidence_ids_json or "[]")]
        except Exception:
            ids = []
        for eid in ids:
            if eid not in evidence_by_id:
                missing_binding.append(finding.id)
                break
    checks.append(
        ConsistencyCheck(
            check_code="finding_evidence_binding",
            status="pass" if not missing_binding else "warn",
            message=(
                "所有 Finding 引用的证据均存在"
                if not missing_binding
                else f"{len(missing_binding)} 个 Finding 引用了不存在的证据"
            ),
            finding_ids=missing_binding,
            evidence_ids=[],
            rule_ids=[],
        )
    )

    # 2. finding_rule_exists：Finding 的 rule_id 必须存在于 Run 固化规则快照
    try:
        pack = load_rule_pack_from_snapshot(run.rule_snapshot_json, run.rule_pack_hash)
        rule_ids = {r.rule_id for r in pack.rules}
    except RuleLoadError:
        rule_ids = set()
        warnings.append("规则快照不可用，finding_rule_exists 检查跳过")
    missing_rule = [f.id for f in findings if f.rule_id not in rule_ids]
    checks.append(
        ConsistencyCheck(
            check_code="finding_rule_exists",
            status="pass" if not missing_rule else "warn",
            message=(
                "所有 Finding 的规则均存在于规则包"
                if not missing_rule
                else f"{len(missing_rule)} 个 Finding 引用了不存在的规则"
            ),
            finding_ids=missing_rule,
            evidence_ids=[],
            rule_ids=sorted(rule_ids)[:50],
        )
    )

    # 3. evidence_locator_valid：Evidence locator 字段合法
    invalid_locator: list[int] = []
    for e in evidence_records:
        if e.locator_type not in ("pdf_page", "spreadsheet_cell", "text_chunk"):
            invalid_locator.append(e.id)
            continue
        if e.locator_type == "pdf_page" and (not e.page_number or e.page_number < 1):
            invalid_locator.append(e.id)
        if e.locator_type == "spreadsheet_cell" and (
            not e.sheet_name or not e.cell_range
        ):
            invalid_locator.append(e.id)
    checks.append(
        ConsistencyCheck(
            check_code="evidence_locator_valid",
            status="pass" if not invalid_locator else "warn",
            message=(
                "所有证据定位信息合法"
                if not invalid_locator
                else f"{len(invalid_locator)} 条证据定位信息不完整"
            ),
            finding_ids=[],
            evidence_ids=invalid_locator,
            rule_ids=[],
        )
    )

    # 4. finding_severity_matches_rule：Finding severity 与规则定义一致
    severity_mismatch: list[int] = []
    rule_by_id = {r.rule_id: r for r in pack.rules} if rule_ids else {}
    for finding in findings:
        rule_def = rule_by_id.get(finding.rule_id)
        if rule_def is not None and rule_def.severity != finding.severity:
            severity_mismatch.append(finding.id)
    checks.append(
        ConsistencyCheck(
            check_code="finding_severity_matches_rule",
            status="pass" if not severity_mismatch else "warn",
            message=(
                "Finding 风险等级与规则定义一致"
                if not severity_mismatch
                else f"{len(severity_mismatch)} 个 Finding 风险等级与规则定义不一致"
            ),
            finding_ids=severity_mismatch,
            evidence_ids=[],
            rule_ids=[],
        )
    )

    # 5. cross_finding_evidence_duplication：同一条证据被多个 Finding 引用（提示性）
    usage: dict[int, list[int]] = {}
    for finding in findings:
        try:
            ids = [int(x) for x in json.loads(finding.evidence_ids_json or "[]")]
        except Exception:
            ids = []
        for eid in ids:
            usage.setdefault(eid, []).append(finding.id)
    duplicated = {eid: fids for eid, fids in usage.items() if len(fids) > 1}
    checks.append(
        ConsistencyCheck(
            check_code="cross_finding_evidence_duplication",
            status="warn" if duplicated else "pass",
            message=(
                "未发现跨 Finding 共享证据"
                if not duplicated
                else f"{len(duplicated)} 条证据被多个 Finding 引用"
            ),
            finding_ids=sorted({f for fids in duplicated.values() for f in fids}),
            evidence_ids=sorted(duplicated.keys()),
            rule_ids=[],
        )
    )

    latency_ms = int((time.perf_counter() - start) * 1000)
    return RunBidConsistencyChecksOutput(
        request_id=payload.request_id,
        latency_ms=latency_ms,
        review_run_id=run.id,
        checks=checks,
        warnings=warnings,
    )


class InternalTokenVerifier:
    """官方 TokenVerifier：校验短期签名 capability token。

    使用官方 Bearer 认证中间件（mcp.server.auth.middleware.bearer_auth）。
    以 ENGINEERING_MCP_INTERNAL_TOKEN 为 HMAC 签名密钥校验；
    校验成功后把真实 user_id 写入 AccessToken.subject。
    原始共享密钥本身不能作为 bearer（格式校验不通过 → 401）。
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        payload = verify_capability_token(token)
        if payload is None:
            return None
        subject = payload.get("sub")
        exp = payload.get("exp")
        return AccessToken(
            token=token,
            client_id="internal",
            scopes=[],
            expires_at=exp,
            subject=subject,
        )


def build_review_tools_mcp_server() -> MCPServer:
    """构建只暴露两个审查工具的 MCPServer（Bearer token 认证）。"""
    # 官方 Bearer 认证要求同时提供 AuthSettings（仅作为 RS 元数据，不实现 OAuth 授权端点）
    auth_settings = AuthSettings(
        issuer_url="http://127.0.0.1/mcp",
        resource_server_url="http://127.0.0.1/mcp",
        required_scopes=[],
    )
    server = MCPServer(
        name="review-tools",
        version="1.0.0",
        token_verifier=InternalTokenVerifier(),
        auth=auth_settings,
    )

    @server.tool(
        name="search_review_rules",
        description=TOOL_DESCRIPTIONS["search_review_rules"],
    )
    async def search_review_rules(
        workspace_id: int,
        review_run_id: int,
        query: str,
        top_k: int = 5,
        request_id: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        del ctx
        if _FAULT_INJECTOR.should_fail("search_review_rules"):
            return {"schema_version": "1.0", "tool_name": "search_review_rules",
                    "status": "error", "error_code": MCPErrorCode.UNAVAILABLE,
                    "message": "MCP 服务不可用，请稍后重试",
                    "request_id": request_id, "latency_ms": 0,
                    "rule_pack_id": "", "rule_pack_version": "",
                    "results": [], "warnings": []}
        payload = SearchReviewRulesInput(
            workspace_id=workspace_id,
            review_run_id=review_run_id,
            query=query,
            top_k=top_k,
            request_id=request_id,
        )
        db = SessionLocal()
        try:
            actor_user_id = _actor_user_id_or_error()
            return _run_search_review_rules(db, payload, actor_user_id).model_dump()
        except MCPError as exc:
            return {"schema_version": "1.0", "tool_name": "search_review_rules",
                    "status": "error", "error_code": exc.code, "message": exc.message,
                    "request_id": request_id, "latency_ms": 0,
                    "rule_pack_id": "", "rule_pack_version": "",
                    "results": [], "warnings": []}
        except Exception:
            exc = tool_error()
            return {"schema_version": "1.0", "tool_name": "search_review_rules",
                    "status": "error", "error_code": exc.code, "message": exc.message,
                    "request_id": request_id, "latency_ms": 0,
                    "rule_pack_id": "", "rule_pack_version": "",
                    "results": [], "warnings": []}
        finally:
            db.close()

    @server.tool(
        name="run_bid_consistency_checks",
        description=TOOL_DESCRIPTIONS["run_bid_consistency_checks"],
    )
    async def run_bid_consistency_checks(
        workspace_id: int,
        review_run_id: int,
        request_id: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        del ctx
        if _FAULT_INJECTOR.should_fail("run_bid_consistency_checks"):
            return {"schema_version": "1.0", "tool_name": "run_bid_consistency_checks",
                    "status": "error", "error_code": MCPErrorCode.UNAVAILABLE,
                    "message": "MCP 服务不可用，请稍后重试",
                    "request_id": request_id, "latency_ms": 0,
                    "review_run_id": review_run_id, "checks": [], "warnings": []}
        payload = RunBidConsistencyChecksInput(
            workspace_id=workspace_id,
            review_run_id=review_run_id,
            request_id=request_id,
        )
        db = SessionLocal()
        try:
            actor_user_id = _actor_user_id_or_error()
            return _run_bid_consistency_checks(db, payload, actor_user_id).model_dump()
        except MCPError as exc:
            return {"schema_version": "1.0", "tool_name": "run_bid_consistency_checks",
                    "status": "error", "error_code": exc.code, "message": exc.message,
                    "request_id": request_id, "latency_ms": 0,
                    "review_run_id": review_run_id, "checks": [], "warnings": []}
        except Exception:
            exc = tool_error()
            return {"schema_version": "1.0", "tool_name": "run_bid_consistency_checks",
                    "status": "error", "error_code": exc.code, "message": exc.message,
                    "request_id": request_id, "latency_ms": 0,
                    "review_run_id": review_run_id, "checks": [], "warnings": []}
        finally:
            db.close()

    return server


def run_review_tools_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    streamable_http_path: str = "/mcp",
    allow_container_bind: bool = False,
) -> None:
    """使用官方 Streamable HTTP 传输运行 MCP Server（阻塞）。

    - 默认只绑定 localhost（127.0.0.1/localhost/::1），禁止危险绑定
    - 仅显式启用 allow_container_bind 时允许 0.0.0.0（Docker 内部网络监听）
    - 官方 DNS rebinding 防护（Host/Origin 明确允许列表，无 * 全通配）
    - 官方 Bearer token 认证（InternalTokenVerifier）
    - json_response=True：请求以单一 JSON 响应返回（便于测试与审计）
    """
    if allow_container_bind:
        if host != "0.0.0.0" and host not in LOCALHOST_BIND_HOSTS:
            raise ValueError(
                "容器内部绑定模式仅允许 0.0.0.0 或 localhost 系绑定地址"
            )
    elif host not in LOCALHOST_BIND_HOSTS:
        raise ValueError(
            "MCP Server 仅允许绑定 localhost（127.0.0.1/localhost/::1）；"
            "容器内部绑定需显式启用 ENGINEERING_MCP_ALLOW_CONTAINER_BIND"
        )

    security = build_transport_security(allow_container_bind=allow_container_bind)
    server = build_review_tools_mcp_server()
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
        json_response=True,
        transport_security=security,
    )
