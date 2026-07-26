import json
import re
from datetime import datetime
from app.core.timeutils import utcnow
from pathlib import Path
from typing import Any

import fitz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file import File
from app.models.file_chunk import FileChunk
from app.services.vector_service import VectorSearchError, search_chunks_by_tfidf

SUPPORTED_RAG_TYPES = {"pdf"}
SUPPORTED_RETRIEVAL_MODES = {"auto", "vector", "keyword"}


class RagServiceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def index_pdf_file(db: Session, file_record: File) -> dict[str, Any]:
    _ensure_pdf_file(file_record)

    existing_chunks = _get_chunks(db, file_record.id)
    if existing_chunks:
        schema = _load_schema(file_record.schema_json)
        indexed = _get_index_metadata(schema)
        return {
            "file_id": file_record.id,
            "filename": file_record.filename,
            "status": file_record.status,
            "page_count": int(indexed.get("page_count", 0)),
            "chunk_count": len(existing_chunks),
            "retrieval_mode": indexed.get("retrieval_mode", settings.rag_retrieval_mode),
            "chunk_size": int(indexed.get("chunk_size", settings.rag_chunk_size)),
            "chunk_overlap": int(indexed.get("chunk_overlap", settings.rag_chunk_overlap)),
            "message": "PDF 已索引，无需重复处理。",
        }

    pages = _extract_pdf_pages(Path(file_record.file_path))
    if not any(page["text"].strip() for page in pages):
        raise RagServiceError("该 PDF 可能是扫描件，当前阶段暂不支持 OCR")

    chunks: list[FileChunk] = []
    chunk_index = 0
    for page in pages:
        for chunk_text in _split_text(page["text"]):
            chunks.append(
                FileChunk(
                    file_id=file_record.id,
                    page_number=page["page_number"],
                    chunk_index=chunk_index,
                    chunk_text=chunk_text,
                )
            )
            chunk_index += 1

    db.add_all(chunks)
    schema = _load_schema(file_record.schema_json)
    indexed_metadata = {
        "indexed": True,
        "type": settings.rag_retrieval_mode,
        "retrieval_mode": settings.rag_retrieval_mode,
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "chunk_size": settings.rag_chunk_size,
        "chunk_overlap": settings.rag_chunk_overlap,
        "indexed_at": utcnow().isoformat(),
    }
    schema["indexed"] = indexed_metadata
    schema["rag_index"] = indexed_metadata
    file_record.status = "indexed"
    file_record.schema_json = json.dumps(schema, ensure_ascii=False)
    db.commit()
    db.refresh(file_record)

    return {
        "file_id": file_record.id,
        "filename": file_record.filename,
        "status": file_record.status,
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "retrieval_mode": settings.rag_retrieval_mode,
        "chunk_size": settings.rag_chunk_size,
        "chunk_overlap": settings.rag_chunk_overlap,
        "message": "PDF 索引完成。",
    }


def search_pdf_chunks(
    db: Session,
    file_record: File,
    query: str,
    top_k: int | None = None,
    retrieval_mode: str | None = None,
) -> dict[str, Any]:
    _ensure_pdf_file(file_record)

    normalized_query = query.strip()
    if not normalized_query:
        raise RagServiceError("检索问题不能为空")

    final_top_k = _normalize_top_k(top_k)
    final_mode = _normalize_retrieval_mode(retrieval_mode)
    chunks = _get_chunks(db, file_record.id)
    if not chunks:
        index_pdf_file(db, file_record)
        chunks = _get_chunks(db, file_record.id)

    if final_mode == "keyword":
        results = _search_keyword_chunks(chunks, file_record.filename, normalized_query, final_top_k)
        return _build_search_response(
            file_record=file_record,
            query=normalized_query,
            top_k=final_top_k,
            retrieval_mode="keyword",
            fallback_used=False,
            results=results,
        )

    if final_mode == "vector":
        try:
            results = search_chunks_by_tfidf(
                query=normalized_query,
                chunks=chunks,
                filename=file_record.filename,
                top_k=final_top_k,
            )
        except VectorSearchError as exc:
            raise RagServiceError(f"向量检索失败：{exc.message}") from exc
        except Exception as exc:
            raise RagServiceError(f"向量检索失败：{exc}") from exc

        return _build_search_response(
            file_record=file_record,
            query=normalized_query,
            top_k=final_top_k,
            retrieval_mode="vector",
            fallback_used=False,
            results=results,
        )

    try:
        results = search_chunks_by_tfidf(
            query=normalized_query,
            chunks=chunks,
            filename=file_record.filename,
            top_k=final_top_k,
        )
        return _build_search_response(
            file_record=file_record,
            query=normalized_query,
            top_k=final_top_k,
            retrieval_mode="vector",
            fallback_used=False,
            results=results,
        )
    except Exception as exc:
        results = _search_keyword_chunks(chunks, file_record.filename, normalized_query, final_top_k)
        response = _build_search_response(
            file_record=file_record,
            query=normalized_query,
            top_k=final_top_k,
            retrieval_mode="keyword",
            fallback_used=True,
            results=results,
        )
        response["message"] = f"向量检索失败，已回退关键词检索：{exc}"
        return response


def answer_pdf_question(
    db: Session,
    file_record: File,
    question: str,
    top_k: int | None = None,
    retrieval_mode: str | None = None,
) -> dict[str, Any]:
    search_result = search_pdf_chunks(
        db=db,
        file_record=file_record,
        query=question,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
    )
    results = search_result["results"]

    if not results:
        return {
            **search_result,
            "answer": "未在该 PDF 中找到与问题相关的内容。",
            "sources": [],
        }

    summary_lines = [
        "根据检索到的 PDF 片段，相关内容主要包括：",
    ]
    sources = []
    for index, result in enumerate(results, start=1):
        snippet = _compact_text(result["chunk_text"])[:220]
        summary_lines.append(f"{index}. 第 {result['page_number']} 页：{snippet}")
        sources.append(
            {
                "filename": result["filename"],
                "page_number": result["page_number"],
                "chunk_id": result["chunk_id"],
                "chunk_index": result["chunk_index"],
                "chunk_text": snippet,
                "score": result["score"],
                "retrieval_mode": result["retrieval_mode"],
            }
        )

    return {
        **search_result,
        "answer": "\n".join(summary_lines),
        "sources": sources,
    }


def _search_keyword_chunks(
    chunks: list[FileChunk],
    filename: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    scored_results = []
    for chunk in chunks:
        score = _score_chunk(query, chunk.chunk_text)
        if score > 0:
            scored_results.append(
                {
                    "chunk_id": chunk.id,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.chunk_text,
                    "score": score,
                    "retrieval_mode": "keyword",
                    "filename": filename,
                }
            )

    scored_results.sort(key=lambda item: item["score"], reverse=True)
    return scored_results[:top_k]


def _ensure_pdf_file(file_record: File) -> None:
    file_type = (file_record.file_type or "").lower()
    if file_type not in SUPPORTED_RAG_TYPES:
        raise RagServiceError("当前文件类型不支持 PDF RAG，仅支持 PDF 文件")

    file_path = Path(file_record.file_path)
    if not file_path.exists():
        raise RagServiceError("文件不存在，无法执行 PDF RAG")


def _extract_pdf_pages(file_path: Path) -> list[dict[str, Any]]:
    pages = []
    with fitz.open(file_path) as document:
        for index, page in enumerate(document, start=1):
            pages.append(
                {
                    "page_number": index,
                    "text": page.get_text("text").strip(),
                }
            )
    return pages


def _split_text(text: str) -> list[str]:
    clean_text = _compact_text(text)
    if not clean_text:
        return []

    chunk_size = max(settings.rag_chunk_size, 100)
    chunk_overlap = max(min(settings.rag_chunk_overlap, chunk_size - 1), 0)
    chunks = []
    start = 0
    while start < len(clean_text):
        end = min(start + chunk_size, len(clean_text))
        chunks.append(clean_text[start:end])
        if end == len(clean_text):
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def _score_chunk(query: str, chunk_text: str) -> float:
    query_text = query.lower()
    chunk = chunk_text.lower()
    tokens = _build_query_tokens(query_text)
    if not tokens:
        return 0

    score = 0.0
    if query_text in chunk:
        score += 5.0

    for token in tokens:
        score += chunk.count(token)

    return score


def _build_query_tokens(query: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", query)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", query)
    chinese_terms = [query[index : index + 2] for index in range(len(query) - 1)]
    tokens = words + chinese_chars + chinese_terms
    return [token for token in tokens if token.strip()]


def _get_chunks(db: Session, file_id: int) -> list[FileChunk]:
    return (
        db.query(FileChunk)
        .filter(FileChunk.file_id == file_id)
        .order_by(FileChunk.page_number.asc(), FileChunk.chunk_index.asc())
        .all()
    )


def _load_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def _get_index_metadata(schema: dict[str, Any]) -> dict[str, Any]:
    rag_index = schema.get("rag_index")
    if isinstance(rag_index, dict):
        return rag_index

    indexed = schema.get("indexed")
    return indexed if isinstance(indexed, dict) else {}


def _normalize_top_k(top_k: int | None) -> int:
    value = top_k if top_k is not None else settings.rag_top_k
    return max(1, min(int(value), 20))


def _normalize_retrieval_mode(retrieval_mode: str | None) -> str:
    mode = (retrieval_mode or settings.rag_retrieval_mode or "auto").strip().lower()
    if mode not in SUPPORTED_RETRIEVAL_MODES:
        raise RagServiceError("检索模式不支持，请使用 auto、vector 或 keyword")
    return mode


def _build_search_response(
    file_record: File,
    query: str,
    top_k: int,
    retrieval_mode: str,
    fallback_used: bool,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "file_id": file_record.id,
        "query": query,
        "top_k": top_k,
        "retrieval_mode": retrieval_mode,
        "fallback_used": fallback_used,
        "result_count": len(results),
        "results": results,
        "message": None if results else "未找到相关内容。",
    }


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
