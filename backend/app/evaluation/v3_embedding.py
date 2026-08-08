"""V3 阶段 4B：Dense Embedding Provider——兼容入口。

此模块现已迁移至共享检索库 app.retrieval.embedding。
保留此文件作为向后兼容的重新导出入口，避免破坏现有测试。
"""

from app.retrieval.embedding import (  # noqa: F401
    MODEL_REPO_ID,
    MODEL_REVISION,
    QUERY_INSTRUCTION,
    FakeEmbeddingProvider,
    LocalEmbeddingProvider,
    EmbeddingError,
    load_provider,
)
