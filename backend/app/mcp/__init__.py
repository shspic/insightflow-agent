"""阶段 5A-1：Review Tools MCP 基座。

- review_tools_server.py：MCP Server，只暴露两个工程审查工具
- review_tools_client.py：生产侧 MCP Client（发现 → 白名单 → 调用）
- schemas.py：工具输入/输出严格 Schema（extra=forbid）
- errors.py：稳定错误码与安全 message

MCP 协议层与业务 service 分离；不修改 BM25/Dense/RRF、规则包、Finding/Evidence。
"""

from app.mcp.errors import MCPError, MCPErrorCode
from app.mcp.review_tools_client import ReviewToolsMCPClient
from app.mcp.review_tools_server import (
    ALLOWED_MCP_TOOL_NAMES,
    InternalTokenVerifier,
    build_review_tools_mcp_server,
    run_review_tools_server,
)
from app.mcp.schemas import (
    RunBidConsistencyChecksInput,
    RunBidConsistencyChecksOutput,
    SearchReviewRulesInput,
    SearchReviewRulesOutput,
)

__all__ = [
    "ALLOWED_MCP_TOOL_NAMES",
    "MCPError",
    "MCPErrorCode",
    "ReviewToolsMCPClient",
    "RunBidConsistencyChecksInput",
    "RunBidConsistencyChecksOutput",
    "SearchReviewRulesInput",
    "SearchReviewRulesOutput",
    "build_review_tools_mcp_server",
    "run_review_tools_server",
]
