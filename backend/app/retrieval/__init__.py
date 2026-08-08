"""共享检索库——供评测（app.evaluation）和生产（app.services）共同使用。

本包提供纯算法和契约接口，不包含：
- 报告生成
- CLI 参数解析
- golden_case 数据
- 评测指标计算
"""

# 从各子模块导出核心类型和函数

from app.retrieval.tokenizer import tokenize, TOKENIZER_NAME, TOKENIZER_VERSION
from app.retrieval.bm25 import bm25_scorer, BM25Scorer
from app.retrieval.embedding import (
    MODEL_REPO_ID,
    MODEL_REVISION,
    QUERY_INSTRUCTION,
    FakeEmbeddingProvider,
    LocalEmbeddingProvider,
    EmbeddingError,
    load_provider,
)
from app.retrieval.dense_index import (
    build_dense_index,
    load_dense_index,
    validate_index_exists,
    DenseIndexError,
)
from app.retrieval.hybrid import hybrid_rrf_retrieve, RRF_K
from app.retrieval.schemas import (
    CorpusChunk,
    RetrievalResult,
    SearchRequest,
    SearchResponse,
    IndexInfo,
    ENGINEERING_ROLES,
    CHUNK_ID_FORMAT,
)
from app.retrieval.errors import (
    EngineeringRetrievalError,
    workspace_invalid,
    material_not_ready,
    index_missing,
    index_stale,
    model_unavailable,
    index_error,
    query_invalid,
)
