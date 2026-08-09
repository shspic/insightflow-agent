"""Review Tools MCP 错误码与安全 message（阶段 5A-1）。

错误 message 使用固定、安全、可向用户展示的文案；
不包含 API Key、.env、数据库 URL、用户路径、磁盘绝对路径、traceback 或原始异常。
"""

from __future__ import annotations


class MCPErrorCode:
    """稳定错误码。"""

    UNAVAILABLE = "ENGINEERING_MCP_UNAVAILABLE"
    TIMEOUT = "ENGINEERING_MCP_TIMEOUT"
    DISCOVERY_ERROR = "ENGINEERING_MCP_DISCOVERY_ERROR"
    TOOL_NOT_ALLOWED = "ENGINEERING_MCP_TOOL_NOT_ALLOWED"
    REQUEST_INVALID = "ENGINEERING_MCP_REQUEST_INVALID"
    RESPONSE_INVALID = "ENGINEERING_MCP_RESPONSE_INVALID"
    TOOL_ERROR = "ENGINEERING_MCP_TOOL_ERROR"
    AUTH_FAILED = "ENGINEERING_MCP_AUTH_FAILED"
    DISABLED = "ENGINEERING_MCP_DISABLED"


class MCPError(Exception):
    """MCP 调用统一异常（带稳定错误码，message 固定安全）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


# ── 固定安全文案 ────────────────────────────────────────────────────


def unavailable() -> MCPError:
    return MCPError(MCPErrorCode.UNAVAILABLE, "MCP 服务不可用，请稍后重试")


def timeout() -> MCPError:
    return MCPError(MCPErrorCode.TIMEOUT, "MCP 服务响应超时，请稍后重试")


def discovery_error() -> MCPError:
    return MCPError(MCPErrorCode.DISCOVERY_ERROR, "MCP 工具发现失败，无法获取工具清单")


def tool_not_allowed() -> MCPError:
    return MCPError(MCPErrorCode.TOOL_NOT_ALLOWED, "不允许调用该 MCP 工具")


def request_invalid() -> MCPError:
    return MCPError(MCPErrorCode.REQUEST_INVALID, "MCP 请求参数不合法")


def response_invalid() -> MCPError:
    return MCPError(MCPErrorCode.RESPONSE_INVALID, "MCP 响应格式不合法")


def tool_error() -> MCPError:
    return MCPError(MCPErrorCode.TOOL_ERROR, "MCP 工具执行失败，请稍后重试")


def auth_failed() -> MCPError:
    return MCPError(MCPErrorCode.AUTH_FAILED, "MCP 服务认证失败")


def disabled() -> MCPError:
    return MCPError(MCPErrorCode.DISABLED, "MCP 功能未启用，请先开启 ENGINEERING_MCP_ENABLED")


# 业务侧错误（服务端校验失败，也使用固定文案，不泄露细节）
def business_invalid(message: str = "业务校验失败") -> MCPError:
    return MCPError(MCPErrorCode.REQUEST_INVALID, message)
