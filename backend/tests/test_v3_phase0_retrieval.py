"""V3 阶段 0 检索命名修正测试。

验证：
- tfidf 模式返回正确的 retrieval_mode 名称
- keyword 模式行为不变
- auto 模式行为与文档一致
- 旧 vector 参数作为弃用别名映射到 tfidf（同一算法）
- 非法检索模式被拒绝
"""
import pytest

from app.services.vector_service import VectorSearchError, search_chunks_by_tfidf
from app.services.rag_service import (
    RagServiceError,
    SUPPORTED_RETRIEVAL_MODES,
    _DEPRECATED_RETRIEVAL_ALIASES,
    _normalize_retrieval_mode,
    _search_keyword_chunks,
    _score_chunk,
    _build_search_response,
)
from app.models.file_chunk import FileChunk


# ---------------------------------------------------------------------------
# 辅助测试数据
# ---------------------------------------------------------------------------

def _make_chunks(texts: list[str]) -> list[FileChunk]:
    """用文本列表构建 FileChunk 列表，id/page/chunk_index 递增。"""
    return [
        FileChunk(
            id=idx + 1,
            file_id=1,
            page_number=idx + 1,
            chunk_index=idx,
            chunk_text=text,
        )
        for idx, text in enumerate(texts)
    ]


# ---------------------------------------------------------------------------
# vector_service 层：TF-IDF 返回 retrieval_mode
# ---------------------------------------------------------------------------

class TestTfidfReturnsCorrectName:
    """search_chunks_by_tfidf 不再返回 'vector'，统一返回 'tfidf'。"""

    def test_tfidf_result_has_correct_retrieval_mode(self):
        chunks = _make_chunks(
            [
                "本项目采用 TF-IDF 算法进行文档检索",
                "Python 数据分析使用 Pandas 库",
                "PDF 文档解析器基于 PyMuPDF",
            ]
        )
        results = search_chunks_by_tfidf(
            query="TF-IDF 检索",
            chunks=chunks,
            filename="test.pdf",
            top_k=3,
        )
        assert len(results) > 0, "TF-IDF 应返回至少一条结果"
        for item in results:
            assert item["retrieval_mode"] == "tfidf", (
                f"每条结果应为 'tfidf'，实际为 {item['retrieval_mode']!r}"
            )

    def test_tfidf_empty_query_raises(self):
        chunks = _make_chunks(["text"])
        with pytest.raises(VectorSearchError, match="不能为空"):
            search_chunks_by_tfidf(query="  ", chunks=chunks, filename="f.pdf", top_k=5)

    def test_tfidf_empty_chunks_returns_empty(self):
        results = search_chunks_by_tfidf(query="hello", chunks=[], filename="f.pdf", top_k=5)
        assert results == []

    def test_tfidf_no_valid_tokens_returns_empty(self):
        chunks = _make_chunks(["文本内容"])
        results = search_chunks_by_tfidf(query="...", chunks=chunks, filename="f.pdf", top_k=5)
        assert results == []


# ---------------------------------------------------------------------------
# rag_service 层：_normalize_retrieval_mode
# ---------------------------------------------------------------------------

class TestNormalizeRetrievalMode:
    """验证 _normalize_retrieval_mode 的合法/非法/弃用映射行为。"""

    def test_accepts_tfidf(self):
        assert _normalize_retrieval_mode("tfidf") == "tfidf"

    def test_accepts_keyword(self):
        assert _normalize_retrieval_mode("keyword") == "keyword"

    def test_accepts_auto(self):
        assert _normalize_retrieval_mode("auto") == "auto"

    def test_vector_maps_to_tfidf(self):
        """旧参数 'vector' 必须映射到 'tfidf'，不保留独立算法路径。"""
        assert _normalize_retrieval_mode("vector") == "tfidf"

    def test_unknown_mode_raises(self):
        with pytest.raises(RagServiceError, match="不支持"):
            _normalize_retrieval_mode("embedding")

    def test_none_defaults_to_auto(self):
        assert _normalize_retrieval_mode(None) == "auto"

    def test_empty_defaults_to_auto(self):
        assert _normalize_retrieval_mode("") == "auto"

    def test_whitespace_normalizes(self):
        assert _normalize_retrieval_mode("  AUTO  ") == "auto"


# ---------------------------------------------------------------------------
# rag_service 层：_search_keyword_chunks 行为不变
# ---------------------------------------------------------------------------

class TestKeywordSearchUnchanged:
    """关键词检索不在阶段 0 修改范围，验证行为稳定。"""

    def test_keyword_returns_keyword_mode(self):
        chunks = _make_chunks(["项目负责人证书编号 CN-2024-001", "质量检测报告 QAR-2025"])
        results = _search_keyword_chunks(
            chunks=chunks,
            filename="bid.pdf",
            query="证书编号",
            top_k=5,
        )
        for item in results:
            assert item["retrieval_mode"] == "keyword"

    def test_keyword_scores_positive(self):
        chunks = _make_chunks(["hello world test", "nothing here"])
        results = _search_keyword_chunks(
            chunks=chunks,
            filename="f.pdf",
            query="hello",
            top_k=5,
        )
        assert len(results) >= 1
        assert results[0]["score"] > 0

    def test_keyword_empty_results(self):
        chunks = _make_chunks(["abc", "def"])
        results = _search_keyword_chunks(
            chunks=chunks,
            filename="f.pdf",
            query="xyz",
            top_k=5,
        )
        assert results == []


# ---------------------------------------------------------------------------
# rag_service 层：_score_chunk 基础逻辑
# ---------------------------------------------------------------------------

class TestScoreChunk:
    def test_exact_substring_bonus(self):
        score = _score_chunk("hello", "hello world")
        assert score >= 5.0, "精确子串匹配应获得 5 分基础加分"

    def test_no_match_returns_zero(self):
        assert _score_chunk("xyz", "abc def") == 0

    def test_case_insensitive(self):
        assert _score_chunk("Hello", "hello world") >= 5.0


# ---------------------------------------------------------------------------
# rag_service 层：SUPPORTED_RETRIEVAL_MODES 与弃用映射
# ---------------------------------------------------------------------------

class TestSupportedModes:
    def test_tfidf_is_supported(self):
        assert "tfidf" in SUPPORTED_RETRIEVAL_MODES

    def test_vector_is_deprecated_alias(self):
        assert "vector" in _DEPRECATED_RETRIEVAL_ALIASES
        assert _DEPRECATED_RETRIEVAL_ALIASES["vector"] == "tfidf"

    def test_vector_still_supported_as_input(self):
        """vector 仍可传入（兼容），但会被映射为 tfidf。"""
        assert "vector" in SUPPORTED_RETRIEVAL_MODES

    def test_no_two_different_algorithms(self):
        """vector 映射到 tfidf，它们走的是同一条代码路径。"""
        assert _normalize_retrieval_mode("vector") == _normalize_retrieval_mode("tfidf")


# ---------------------------------------------------------------------------
# rag_service 层：_build_search_response
# ---------------------------------------------------------------------------

class TestBuildSearchResponse:
    def test_response_structure(self):
        from unittest.mock import MagicMock

        mock_file = MagicMock()
        mock_file.id = 42
        resp = _build_search_response(
            file_record=mock_file,
            query="test",
            top_k=3,
            retrieval_mode="tfidf",
            fallback_used=False,
            results=[],
        )
        assert resp["retrieval_mode"] == "tfidf"
        assert resp["result_count"] == 0
        assert resp["message"] == "未找到相关内容。"
        assert resp["fallback_used"] is False
        assert resp["file_id"] == 42


# ---------------------------------------------------------------------------
# 完整性：非法检索模式仍被拒绝（Pydantic schema 层）
# ---------------------------------------------------------------------------

class TestSchemaRejectsIllegalMode:
    """验证 FileSearchRequest 的 Pydantic 校验拒绝非法模式。"""

    def test_illegal_mode_rejected_by_schema(self):
        from app.schemas.rag import FileSearchRequest
        from pydantic import ValidationError

        FileSearchRequest(query="test", retrieval_mode="tfidf")  # 合法
        FileSearchRequest(query="test", retrieval_mode="keyword")  # 合法
        FileSearchRequest(query="test", retrieval_mode="auto")  # 合法
        FileSearchRequest(query="test", retrieval_mode="vector")  # 旧兼容合法
        FileSearchRequest(query="test", retrieval_mode=None)  # 合法

        with pytest.raises(ValidationError):
            FileSearchRequest(query="test", retrieval_mode="embedding")
        with pytest.raises(ValidationError):
            FileSearchRequest(query="test", retrieval_mode="hybrid")
