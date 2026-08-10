"""工程检索共享 Schema：Corpus Chunk、检索结果、搜索请求/响应。
"""

from __future__ import annotations

import hashlib
from typing import Any


# 允许进入 Corpus 的工程角色
ENGINEERING_ROLES = {
    "tender_requirement",
    "bid_response",
    "personnel_equipment_data",
    "qualification_attachment",
    "clarification_document",
    "supplementary_attachment",
}

# Chunk ID 格式常量
CHUNK_ID_FORMAT = "W{workspace_id:04d}F{file_id:04d}C{index:03d}"


class CorpusChunk:
    """生产 Corpus Chunk（与评测 Corpus 字段兼容）。"""

    __slots__ = (
        "chunk_id", "workspace_id", "owner_user_id", "file_id", "file_name",
        "file_role", "locator_type", "page_number", "sheet_name", "cell_range",
        "text_chunk_index", "section_path", "text", "content_hash",
        "parser_name", "parser_version",
    )

    def __init__(
        self,
        chunk_id: str,
        workspace_id: int,
        owner_user_id: int,
        file_id: int,
        file_name: str,
        file_role: str,
        locator_type: str,
        text: str,
        content_hash: str,
        *,
        page_number: int | None = None,
        sheet_name: str | None = None,
        cell_range: str | None = None,
        text_chunk_index: int | None = None,
        section_path: str | None = None,
        parser_name: str = "unknown",
        parser_version: str = "1.0.0",
    ):
        self.chunk_id = chunk_id
        self.workspace_id = workspace_id
        self.owner_user_id = owner_user_id
        self.file_id = file_id
        self.file_name = file_name
        self.file_role = file_role
        self.locator_type = locator_type
        self.page_number = page_number
        self.sheet_name = sheet_name
        self.cell_range = cell_range
        self.text_chunk_index = text_chunk_index
        self.section_path = section_path
        self.text = text
        self.content_hash = content_hash
        self.parser_name = parser_name
        self.parser_version = parser_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "workspace_id": self.workspace_id,
            "owner_user_id": self.owner_user_id,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "file_role": self.file_role,
            "locator_type": self.locator_type,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "cell_range": self.cell_range,
            "text_chunk_index": self.text_chunk_index,
            "section_path": self.section_path,
            "text": self.text,
            "content_hash": self.content_hash,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
        }

    def to_retrieval_dict(self) -> dict[str, Any]:
        """转为与评测兼容的检索 dict。"""
        d = self.to_dict()
        d.setdefault("locator_type", self.locator_type)
        return d

    @staticmethod
    def make_chunk_id(workspace_id: int, file_id: int, index: int) -> str:
        return f"W{workspace_id:04d}F{file_id:04d}C{index:03d}"

    @staticmethod
    def compute_content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_corpus_sha256(chunks: list[CorpusChunk]) -> str:
        """对排序后的 chunk 规范化 JSON 序列化计算 SHA-256。"""
        serialized = json.dumps(
            [c.to_dict() for c in sorted(chunks, key=lambda c: c.chunk_id)],
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class RetrievalResult:
    """单条检索结果。"""
    __slots__ = (
        "rank", "chunk_id", "file_id", "file_name", "file_role",
        "locator_type", "page_number", "sheet_name", "cell_range",
        "quote", "score", "bm25_rank", "dense_rank", "rrf_score",
        "content_hash", "parser_name", "parser_version",
    )

    def __init__(self, *, rank: int, chunk_id: str, file_id: int,
                 file_name: str, file_role: str, locator_type: str,
                 quote: str, score: float, bm25_rank: int = 0,
                 dense_rank: int = 0, rrf_score: float = 0.0,
                 page_number: int | None = None, sheet_name: str | None = None,
                 cell_range: str | None = None,
                 content_hash: str = "", parser_name: str = "unknown",
                 parser_version: str = "1.0.0"):
        self.rank = rank
        self.chunk_id = chunk_id
        self.file_id = file_id
        self.file_name = file_name
        self.file_role = file_role
        self.locator_type = locator_type
        self.page_number = page_number
        self.sheet_name = sheet_name
        self.cell_range = cell_range
        self.quote = quote
        self.score = score
        self.bm25_rank = bm25_rank
        self.dense_rank = dense_rank
        self.rrf_score = rrf_score
        self.content_hash = content_hash
        self.parser_name = parser_name
        self.parser_version = parser_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "file_role": self.file_role,
            "locator_type": self.locator_type,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "cell_range": self.cell_range,
            "quote": self.quote,
            "score": self.score,
            "bm25_rank": self.bm25_rank,
            "dense_rank": self.dense_rank,
            "content_hash": self.content_hash,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
        }


class SearchRequest:
    def __init__(self, query: str, top_k: int = 5,
                 retrieval_mode: str = "hybrid_rrf"):
        self.query = query
        self.top_k = top_k
        self.retrieval_mode = retrieval_mode


class SearchResponse:
    def __init__(self, query: str, retrieval_mode: str, results: list[RetrievalResult],
                 *, index_sha256: str = "", corpus_sha256: str = "",
                 model_revision: str = "", rrf_k: int = 60,
                 latency_ms: dict[str, float] | None = None,
                 answerability: str = "unknown"):
        self.query = query
        self.retrieval_mode = retrieval_mode
        self.results = results
        self.index_sha256 = index_sha256
        self.corpus_sha256 = corpus_sha256
        self.model_revision = model_revision
        self.rrf_k = rrf_k
        self.latency_ms = latency_ms or {}
        self.answerability = answerability

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "retrieval_mode": self.retrieval_mode,
            "answerability": self.answerability,
            "index_sha256": self.index_sha256,
            "corpus_sha256": self.corpus_sha256,
            "model_revision": self.model_revision,
            "rrf_k": self.rrf_k,
            "latency_ms": self.latency_ms,
            "results": [r.to_dict() for r in self.results],
        }


class IndexInfo:
    def __init__(self, status: str, workspace_id: int, *,
                 corpus_sha256: str = "", chunk_count: int = 0,
                 file_count: int = 0, model_repo_id: str = "",
                 model_revision: str = "", index_sha256: str = "",
                 created_at: str = "", warnings: list[str] | None = None):
        self.status = status
        self.workspace_id = workspace_id
        self.corpus_sha256 = corpus_sha256
        self.chunk_count = chunk_count
        self.file_count = file_count
        self.model_repo_id = model_repo_id
        self.model_revision = model_revision
        self.index_sha256 = index_sha256
        self.created_at = created_at
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "workspace_id": self.workspace_id,
            "corpus_sha256": self.corpus_sha256,
            "chunk_count": self.chunk_count,
            "file_count": self.file_count,
            "model_repo_id": self.model_repo_id,
            "model_revision": self.model_revision,
            "index_sha256": self.index_sha256,
            "created_at": self.created_at,
            "warnings": self.warnings,
        }


# json import at module level (used in compute_corpus_sha256)
import json
