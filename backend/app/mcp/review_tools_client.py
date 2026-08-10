"""Review Tools MCP Client（阶段 5A-1）。

流程：先发现工具 → 校验恰好两个白名单工具 → 客户端 Schema 校验 → 调用
     → 响应 Schema 校验 → 返回结构化结果。

- 服务端不可用 / 超时 / 协议错误 / Schema 错误严格区分（稳定错误码）
- 不提供本地同名函数 fallback：MCP 失败时返回明确错误，不伪装成功
- 错误信息固定安全文案，不含 API Key / 路径 / traceback / token
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.core.config import settings
from app.mcp.errors import (
    MCPError,
    MCPErrorCode,
    disabled,
    discovery_error,
    request_invalid,
    response_invalid,
    timeout,
    tool_error,
    tool_not_allowed,
    unavailable,
)
from app.mcp.schemas import (
    RunBidConsistencyChecksInput,
    RunBidConsistencyChecksOutput,
    SearchReviewRulesInput,
    SearchReviewRulesOutput,
)
from app.mcp.review_tools_server import ALLOWED_MCP_TOOL_NAMES

# 使用官方 Bearer 认证（mcp 2.0 BearerAuthBackend）
MCP_AUTH_HEADER = "Authorization"


class ReviewToolsMCPClient:
    """生产侧 MCP Client（Streamable HTTP）。"""

    def __init__(
        self,
        *,
        url: str | None = None,
        internal_token: str | None = None,
        timeout_seconds: float | None = None,
        require_enabled: bool = True,
    ):
        # 未显式指定 URL/token 且功能关闭时，调用返回明确 DISABLED 错误（不伪成功）
        if require_enabled and url is None and internal_token is None:
            if not settings.engineering_mcp_enabled:
                raise disabled()
        self.url = url or settings.engineering_mcp_url
        self.internal_token = internal_token or settings.engineering_mcp_internal_token
        self.timeout_seconds = timeout_seconds or settings.engineering_mcp_timeout_seconds

    @staticmethod
    def _classify_exception(exc: Exception) -> MCPError | None:
        """将 ExceptionGroup 内层异常归类为稳定 MCP 错误。"""
        candidates: list[BaseException] = []
        if isinstance(exc, BaseExceptionGroup):
            candidates.extend(exc.exceptions)
        else:
            candidates.append(exc)
        for sub in candidates:
            if isinstance(sub, (httpx2.TimeoutException, TimeoutError)):
                return timeout()
            if isinstance(sub, httpx2.ConnectError):
                return unavailable()
            if isinstance(sub, BaseExceptionGroup):
                nested = ReviewToolsMCPClient._classify_exception(sub)
                if nested is not None:
                    return nested
        return None

    def _preflight_connect(self) -> None:
        """TCP 预检：连接拒绝 → ENGINEERING_MCP_UNAVAILABLE。"""
        from urllib.parse import urlparse

        parsed = urlparse(self.url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        import socket as _socket

        try:
            sck = _socket.create_connection((host, port), timeout=min(3.0, self.timeout_seconds))
            sck.close()
        except OSError:
            raise unavailable()

    # ── 工具发现 ────────────────────────────────────────────────────

    async def discover_tools(self) -> list[str]:
        """发现工具，校验恰好存在允许的两个工具，返回白名单工具名列表。"""
        self._preflight_connect()
        headers = {
            "Accept": "application/json, text/event-stream",
            MCP_AUTH_HEADER: f"Bearer {self.internal_token}",
        }
        try:
            transport = streamable_http_client(
                self.url,
                http_client=httpx2.AsyncClient(
                    headers=headers,
                    timeout=httpx2.Timeout(self.timeout_seconds),
                ),
            )
            async with transport as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
        except MCPError:
            raise
        except Exception as exc:
            mapped = self._classify_exception(exc)
            if mapped is not None:
                raise mapped from exc
            raise discovery_error() from exc

        names = [t.name for t in (tools_result.tools or [])]
        if set(names) != set(ALLOWED_MCP_TOOL_NAMES):
            raise tool_not_allowed()
        return sorted(names)

    # ── 调用 ────────────────────────────────────────────────────────

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """执行白名单工具调用（内部完成 Schema 校验与错误映射）。"""
        if tool_name not in ALLOWED_MCP_TOOL_NAMES:
            raise tool_not_allowed()
        self._preflight_connect()

        # 客户端 Schema 校验（extra=forbid）
        try:
            if tool_name == "search_review_rules":
                SearchReviewRulesInput.model_validate(arguments)
            else:
                RunBidConsistencyChecksInput.model_validate(arguments)
        except Exception as exc:
            raise request_invalid() from exc

        headers = {
            "Accept": "application/json, text/event-stream",
            MCP_AUTH_HEADER: f"Bearer {self.internal_token}",
        }
        try:
            transport = streamable_http_client(
                self.url,
                http_client=httpx2.AsyncClient(
                    headers=headers,
                    timeout=httpx2.Timeout(self.timeout_seconds),
                ),
            )
            async with transport as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
        except MCPError:
            raise
        except Exception as exc:
            mapped = self._classify_exception(exc)
            if mapped is not None:
                raise mapped from exc
            raise unavailable() from exc

        content = result.content or []
        text_parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                text_parts.append(text)
        raw = "\n".join(text_parts)

        try:
            import json as json_mod

            data = json_mod.loads(raw) if raw else {}
        except Exception as exc:
            raise response_invalid() from exc

        if result.is_error or data.get("error_code"):
            code = data.get("error_code", MCPErrorCode.TOOL_ERROR)
            message = data.get("message", "MCP 工具执行失败")
            raise MCPError(code, message)

        # 响应 Schema 校验
        try:
            if tool_name == "search_review_rules":
                validated = SearchReviewRulesOutput.model_validate(data)
            else:
                validated = RunBidConsistencyChecksOutput.model_validate(data)
        except Exception as exc:
            raise response_invalid() from exc

        return validated.model_dump()

    # ── 同步便捷入口（供非 asyncio 环境/脚本使用）──────────────────

    def discover_tools_sync(self) -> list[str]:
        return asyncio.run(self.discover_tools())

    def call_tool_sync(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.call_tool(tool_name, arguments))

    @staticmethod
    def make_request_id() -> str:
        return uuid.uuid4().hex


def build_default_search_arguments(
    *,
    workspace_id: int,
    review_run_id: int,
    query: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """构造 search_review_rules 参数（request_id 自动生成）。"""
    return {
        "workspace_id": workspace_id,
        "review_run_id": review_run_id,
        "query": query,
        "top_k": top_k,
        "request_id": ReviewToolsMCPClient.make_request_id(),
    }
