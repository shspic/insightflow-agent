"""生产 MCP Server 启动入口（阶段 6D-1）。

- 由 docker-compose.prod.yml 的 mcp 服务调用（复用 backend 镜像）
- 仅当显式配置 ENGINEERING_MCP_ALLOW_CONTAINER_BIND=true 时监听
  容器内部网络（0.0.0.0），否则保持 127.0.0.1 安全默认
- 内部 token 未配置时拒绝启动（避免无认证静默上线）
"""

from app.core.config import settings
from app.mcp.review_tools_server import run_review_tools_server


def main() -> None:
    if not settings.engineering_mcp_internal_token:
        raise RuntimeError(
            "ENGINEERING_MCP_INTERNAL_TOKEN 未配置，MCP Server 拒绝启动"
        )
    run_review_tools_server(
        host="0.0.0.0" if settings.engineering_mcp_allow_container_bind else "127.0.0.1",
        port=8765,
        streamable_http_path="/mcp",
        allow_container_bind=settings.engineering_mcp_allow_container_bind,
    )


if __name__ == "__main__":
    main()
