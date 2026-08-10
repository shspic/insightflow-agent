"""Review Tools MCP 健康检查（阶段 6D-1）。

- compose healthcheck 与 backend readiness 共用：真实工具发现
- 使用内部健康专用 subject（0，非真实用户 id）签发的短期 capability token；
  不使用任何真实用户 capability token，不把原始共享密钥当 bearer
- token 不进日志、不进响应；检查失败返回非零退出码
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request

from app.core.config import settings
from app.mcp.capability_tokens import issue_capability_token
from app.mcp.review_tools_client import ReviewToolsMCPClient
from app.mcp.review_tools_server import ALLOWED_MCP_TOOL_NAMES

# 健康检查专用 subject：0 不是任何真实用户（用户 id 自增从 1 起），
# 服务端仅将其用于认证中间件；该 token 不能访问任何 workspace/run。
HEALTH_SUBJECT = 0


def mcp_healthcheck_ok(
    url: str | None = None,
    timeout_seconds: float = 5.0,
    internal_token: str | None = None,
) -> bool:
    """真实工具发现：恰好发现两个白名单工具才算健康。

    internal_token 供测试注入；默认使用 settings 的
    ENGINEERING_MCP_INTERNAL_TOKEN（未配置时视为不健康）。
    """
    signing_key = (
        internal_token
        if internal_token is not None
        else settings.engineering_mcp_internal_token
    )
    if not signing_key:
        return False
    token = issue_capability_token(HEALTH_SUBJECT, secret=signing_key)
    client = ReviewToolsMCPClient(
        url=url or settings.engineering_mcp_url,
        internal_token=token,
        timeout_seconds=timeout_seconds,
        require_enabled=False,
    )
    try:
        tools = client.discover_tools_sync()
    except Exception:
        return False
    return set(tools) == set(ALLOWED_MCP_TOOL_NAMES)


def mcp_probe_ok(
    url: str | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """无凭据 401 探测：服务监听、Host 校验与认证中间件生效。

    不签发任何 token：initialize 请求不带 Authorization，
    服务正常时返回 401（Bearer 认证拒绝无凭据请求），
    连接失败或返回其他状态视为不健康。
    """
    probe_url = url or settings.engineering_mcp_url
    body = (
        b'{"jsonrpc":"2.0","id":1,"method":"initialize",'
        b'"params":{"protocolVersion":"2026-07-28","capabilities":{},'
        b'"clientInfo":{"name":"healthcheck","version":"1"}}}'
    )
    request = urllib.request.Request(
        probe_url,
        data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as exc:
        return exc.code == 401
    except Exception:
        return False
    return False  # 无认证请求成功返回 ≠ 认证在生效


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCP 服务健康检查（真实工具发现）")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/mcp",
        help="MCP Streamable HTTP 端点（默认 http://127.0.0.1:8765/mcp）",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)

    ok = mcp_healthcheck_ok(url=args.url, timeout_seconds=args.timeout)
    print("MCP 健康检查通过：两个白名单工具可发现" if ok else "MCP 健康检查失败", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
