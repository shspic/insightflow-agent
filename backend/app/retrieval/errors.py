"""工程检索错误类型——API 层只做映射，不根据字符串猜错误类型。"""

from __future__ import annotations


class EngineeringRetrievalError(Exception):
    """工程检索统一异常基类。

    API 层通过 code 识别错误类型，无需字符串匹配。
    """

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ── 具体错误类型 ────────────────────────────────────────────────────


def workspace_invalid(message: str = "仅工程类工作区支持检索") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_WORKSPACE_INVALID", message, status_code=400
    )


def material_not_ready(message: str = "工作区没有可用于检索的工程材料") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_MATERIAL_NOT_READY", message, status_code=400
    )


def index_missing(message: str = "索引未构建") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_INDEX_MISSING", message, status_code=400
    )


def index_stale(message: str = "语料已变更，索引需重建") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_INDEX_STALE", message, status_code=400
    )


def model_unavailable(message: str = "Embedding 模型不可用") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_MODEL_UNAVAILABLE", message, status_code=500
    )


def index_error(message: str = "索引操作失败") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_INDEX_ERROR", message, status_code=500
    )


def query_invalid(message: str = "查询参数无效") -> EngineeringRetrievalError:
    return EngineeringRetrievalError(
        "ENGINEERING_RETRIEVAL_QUERY_INVALID", message, status_code=400
    )
