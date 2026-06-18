import math
import re
from collections import Counter
from typing import Any

from app.models.file_chunk import FileChunk


class VectorSearchError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def search_chunks_by_tfidf(
    query: str,
    chunks: list[FileChunk],
    filename: str,
    top_k: int,
) -> list[dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        raise VectorSearchError("检索问题不能为空")

    if not chunks:
        return []

    query_tokens = _tokenize(normalized_query)
    if not query_tokens:
        return []

    chunk_tokens = [_tokenize(chunk.chunk_text or "") for chunk in chunks]
    document_frequency = _build_document_frequency(chunk_tokens)
    document_count = len(chunk_tokens)
    query_vector = _build_tfidf_vector(query_tokens, document_frequency, document_count)

    results = []
    for chunk, tokens in zip(chunks, chunk_tokens, strict=False):
        chunk_vector = _build_tfidf_vector(tokens, document_frequency, document_count)
        score = _cosine_similarity(query_vector, chunk_vector)
        if score <= 0:
            continue
        results.append(
            {
                "chunk_id": chunk.id,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "chunk_text": chunk.chunk_text,
                "score": round(score, 6),
                "retrieval_mode": "vector",
                "filename": filename,
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z0-9_]+", lowered)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
    chinese_terms = [lowered[index : index + 2] for index in range(len(lowered) - 1)]
    tokens = words + chinese_chars + chinese_terms
    return [token for token in tokens if token.strip()]


def _build_document_frequency(documents: list[list[str]]) -> Counter[str]:
    frequency: Counter[str] = Counter()
    for tokens in documents:
        frequency.update(set(tokens))
    return frequency


def _build_tfidf_vector(
    tokens: list[str],
    document_frequency: Counter[str],
    document_count: int,
) -> dict[str, float]:
    term_frequency = Counter(tokens)
    vector = {}
    for token, count in term_frequency.items():
        df = document_frequency.get(token, 0)
        idf = math.log((document_count + 1) / (df + 1)) + 1
        vector[token] = count * idf
    return vector


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0

    shared_tokens = set(left).intersection(right)
    dot_product = sum(left[token] * right[token] for token in shared_tokens)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)
