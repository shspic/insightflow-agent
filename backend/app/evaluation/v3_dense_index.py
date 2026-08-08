"""V3 阶段 4B：持久化 Dense Index——兼容入口。

此模块现已迁移至共享检索库 app.retrieval.dense_index。
保留此文件作为向后兼容的重新导出入口，避免破坏现有测试。
"""

from app.retrieval.dense_index import (  # noqa: F401
    build_dense_index,
    load_dense_index,
    validate_index_exists,
    DenseIndexError,
)
