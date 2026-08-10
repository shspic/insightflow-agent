"""V3 中文检索分词器——兼容入口。

此模块现已迁移至共享检索库 app.retrieval.tokenizer。
保留此文件作为向后兼容的重新导出入口，避免破坏现有测试。
"""

from app.retrieval.tokenizer import (  # noqa: F401
    tokenize,
    tokenize_for_keyword,
    TOKENIZER_NAME,
    TOKENIZER_VERSION,
)
