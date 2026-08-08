"""V3 阶段 4B：RRF Hybrid Retrieval——兼容入口。

此模块现已迁移至共享检索库 app.retrieval.hybrid。
保留此文件作为向后兼容的重新导出入口，避免破坏现有测试。
"""

from app.retrieval.hybrid import (  # noqa: F401
    hybrid_rrf_retrieve,
    RRF_K,
)
