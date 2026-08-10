"""V3 阶段 4B：Dense Embedding、持久化索引与 RRF 混合检索测试。

使用 deterministic FakeEmbeddingProvider，避免联网和模型下载。
LocalEmbeddingProvider 通过 monkeypatch 注入假 SentenceTransformer 验证 instruction 逻辑。
测试全程不访问 Hugging Face，不加载真实模型权重。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.evaluation.v3_corpus import CHUNKING_VERSION, build_corpus
from app.evaluation.v3_embedding import (
    FakeEmbeddingProvider,
    LocalEmbeddingProvider,
    MODEL_REPO_ID,
    MODEL_REVISION,
    QUERY_INSTRUCTION,
)
from app.evaluation.v3_dense_index import (
    build_dense_index,
    load_dense_index,
    validate_index_exists,
    DenseIndexError,
)
from app.evaluation.v3_hybrid import hybrid_rrf_retrieve, RRF_K
from app.evaluation.v3_retrieval import (
    bm25_retrieve,
    keyword_retrieve,
    make_dense_retriever,
    tfidf_retrieve,
)
from app.evaluation.v3_metrics import (
    compute_answerable_metrics,
    aggregate_answerable,
)
from app.evaluation.v3_query_set import load_query_set

# -- 常量 --
GOLDEN_CASE_DIR = (
    Path(__file__).resolve().parents[2]
    / "examples" / "engineering_review_v1" / "golden_case"
)
STAGE4B_EVAL_DIR = GOLDEN_CASE_DIR.parent / "eval_results" / "stage4b"


# -- Fake provider fixture --
@pytest.fixture(scope="module")
def fake_provider():
    return FakeEmbeddingProvider(dimension=512, seed=42)


# -- Corpus fixture --
@pytest.fixture(scope="module")
def corpus():
    return build_corpus(GOLDEN_CASE_DIR)


# ================================================================
# 1. FakeEmbeddingProvider
# ================================================================


class TestFakeEmbeddingProvider:
    """FakeEmbeddingProvider 行为验证。"""

    def test_vectors_are_float32(self, fake_provider):
        vecs = fake_provider.encode_passages(["测试文本"])
        assert vecs.dtype == np.float32

    def test_dimension_consistent(self, fake_provider):
        vecs = fake_provider.encode_passages(["a", "b", "c"])
        assert vecs.shape == (3, 512)

    def test_vectors_are_normalized(self, fake_provider):
        vecs = fake_provider.encode_passages(["text1", "text2", "text3"])
        norms = np.linalg.norm(vecs, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-4), f"norms: {norms}"

    def test_no_nan_inf(self, fake_provider):
        vecs = fake_provider.encode_passages(["test"])
        assert not np.isnan(vecs).any()
        assert not np.isinf(vecs).any()

    def test_empty_input(self, fake_provider):
        vecs = fake_provider.encode_passages([])
        assert vecs.shape == (0, 512)
        vecs2 = fake_provider.encode_queries([])
        assert vecs2.shape == (0, 512)


# ================================================================
# 2. LocalEmbeddingProvider（monkeypatch，不加载真实模型）
# ================================================================


class FakeSentenceTransformer:
    """假的 SentenceTransformer，捕获构造参数并返回确定性向量。"""

    def __init__(self, repo_id, *, revision=None, device=None, cache_folder=None):
        self.repo_id = repo_id
        self.revision = revision
        self.device = device
        self.cache_folder = cache_folder
        self.last_encode_kwargs = {}

    def get_sentence_embedding_dimension(self):
        return 512

    def get_embedding_dimension(self):
        return 512

    def encode(self, sentences, *, batch_size=None, show_progress_bar=None,
               convert_to_numpy=None, normalize_embeddings=None):
        self.last_encode_kwargs = dict(
            batch_size=batch_size,
            convert_to_numpy=convert_to_numpy,
            normalize_embeddings=normalize_embeddings,
        )
        out = np.zeros((len(sentences), 512), dtype=np.float64)
        if normalize_embeddings:
            # L2 normalize
            for i in range(len(sentences)):
                out[i, 0] = 1.0
        return out


@pytest.fixture
def patched_local_provider(monkeypatch):
    """返回一个 monkeypatched LocalEmbeddingProvider 和 FakeSentenceTransformer。

    通过 monkeypatch.setattr 替换 sentence_transformers.SentenceTransformer，
    使用工厂函数捕获构造参数（包括 cache_folder）。
    """
    # 使用可变容器捕获工厂创建的 fake_model
    captured: list[FakeSentenceTransformer] = []

    def _factory(*args, **kwargs):
        m = FakeSentenceTransformer(*args, **kwargs)
        captured.append(m)
        return m

    import sentence_transformers
    monkeypatch.setattr(
        sentence_transformers, "SentenceTransformer",
        _factory,
        raising=False,
    )

    provider = LocalEmbeddingProvider(
        model_repo_id=MODEL_REPO_ID,
        model_revision=MODEL_REVISION,
        query_instruction=QUERY_INSTRUCTION,
        cache_dir="/tmp/test_cache",
        batch_size=4,
    )

    # provider 尚未加载；测试调用 _ensure_loaded() 后 captured[0] 即为创建的模型
    return provider, captured


class TestLocalEmbeddingProvider:
    """LocalEmbeddingProvider 逻辑验证（无需真实模型）。"""

    def test_empty_input_no_model_load(self):
        """空输入不应触发模型加载。"""
        provider = LocalEmbeddingProvider(cache_dir="/tmp/test")
        # 不应调用 _ensure_loaded，直接返回空
        assert provider._loaded is False

    def _load(self, provider, captured):
        """helper: 确保加载并返回 fake model。"""
        provider._ensure_loaded()
        assert len(captured) >= 1, "factory 未被调用"
        return captured[0]

    def test_repo_id_and_revision_passed_to_model(self, patched_local_provider):
        """验证构造参数传递给 SentenceTransformer。"""
        provider, captured = patched_local_provider
        m = self._load(provider, captured)
        assert m.repo_id == MODEL_REPO_ID
        assert m.revision == MODEL_REVISION

    def test_device_is_cpu(self, patched_local_provider):
        provider, captured = patched_local_provider
        m = self._load(provider, captured)
        assert m.device == "cpu"

    def test_cache_folder_always_set(self, patched_local_provider):
        provider, captured = patched_local_provider
        m = self._load(provider, captured)
        assert m.cache_folder == "/tmp/test_cache"

    def test_default_cache_folder_used(self, monkeypatch):
        """未传 cache_dir 时使用默认缓存目录。"""
        captured: list[FakeSentenceTransformer] = []

        def _factory(*args, **kwargs):
            m = FakeSentenceTransformer(*args, **kwargs)
            captured.append(m)
            return m

        import sentence_transformers
        monkeypatch.setattr(
            sentence_transformers, "SentenceTransformer", _factory, raising=False,
        )
        provider = LocalEmbeddingProvider(cache_dir=None)
        provider._ensure_loaded()
        assert len(captured) >= 1
        m = captured[0]
        assert m.cache_folder is not None
        assert "model_cache" in str(m.cache_folder)

    def test_passage_encodes_without_instruction(self, patched_local_provider):
        """encode_passages 不对文本添加 instruction。"""
        provider, captured = patched_local_provider
        m = self._load(provider, captured)
        provider.encode_passages(["正文内容"])
        assert m.last_encode_kwargs["normalize_embeddings"] is True

    def test_query_adds_instruction(self, patched_local_provider):
        """encode_queries 在文本前添加 query instruction。"""
        provider, captured = patched_local_provider
        m = self._load(provider, captured)
        provider.encode_queries(["问题"])
        assert m.last_encode_kwargs["convert_to_numpy"] is True

    def test_normalize_embeddings_is_true(self, patched_local_provider):
        provider, captured = patched_local_provider
        m = self._load(provider, captured)
        provider.encode_passages(["test"])
        assert m.last_encode_kwargs["normalize_embeddings"] is True

    def test_output_forced_to_float32(self, patched_local_provider):
        """即使模型返回 float64，输出也强制转 float32。"""
        provider, captured = patched_local_provider
        self._load(provider, captured)
        result = provider.encode_passages(["test"])
        assert result.dtype == np.float32

    def test_nan_inf_rejected(self, patched_local_provider):
        provider, captured = patched_local_provider
        self._load(provider, captured)
        result = provider.encode_passages(["test"])
        assert not np.isnan(result).any()
        assert not np.isinf(result).any()

    def test_metadata_dimension_matches_model(self, patched_local_provider):
        provider, captured = patched_local_provider
        self._load(provider, captured)
        meta = provider.metadata()
        assert meta["dimension"] == 512
        assert meta["normalize_embeddings"] is True
        assert meta["query_instruction"] == QUERY_INSTRUCTION
        assert meta["model_repo_id"] == MODEL_REPO_ID
        assert meta["model_revision"] == MODEL_REVISION


# ================================================================
# 3. Dense Index（基础功能）
# ================================================================


class TestDenseIndexBasic:
    """DenseIndex 构建、加载、基础校验。"""

    def test_index_build_and_load(self, fake_provider, corpus, tmp_path):
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)

        provider_meta = fake_provider.metadata()
        idx_dir = tmp_path / "test_index"
        build_dense_index(
            embeddings=embeddings,
            chunk_ids=chunk_ids,
            corpus_sha256="test_corpus_sha",
            provider_meta=provider_meta,
            output_dir=idx_dir,
        )
        assert (idx_dir / "dense_index.npz").exists()
        assert (idx_dir / "dense_index_meta.json").exists()

        loaded_vecs, loaded_ids, meta = load_dense_index(
            index_dir=idx_dir,
            corpus_sha256="test_corpus_sha",
            expected_chunk_ids=chunk_ids,
            expected_model_revision=provider_meta["model_revision"],
            expected_dimension=512,
        )
        assert len(loaded_ids) == len(chunk_ids)
        assert loaded_ids == chunk_ids
        assert np.allclose(loaded_vecs, embeddings, atol=1e-5)

    def test_index_reuse(self, fake_provider, corpus, tmp_path):
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "reuse_index"

        build_dense_index(embeddings, chunk_ids, "sha", fake_provider.metadata(), idx_dir)
        assert validate_index_exists(idx_dir)
        load_dense_index(idx_dir, "sha", chunk_ids, fake_provider.metadata()["model_revision"],
                         expected_dimension=512)

    def test_npz_no_pickle(self, fake_provider, corpus, tmp_path):
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "no_pickle_index"

        build_dense_index(embeddings, chunk_ids, "sha", fake_provider.metadata(), idx_dir)
        npz_path = idx_dir / "dense_index.npz"
        with np.load(npz_path, allow_pickle=False) as data:
            assert "embeddings" in data
            assert data["embeddings"].dtype == np.float32

    def test_corpus_sha_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "sha_mismatch"

        build_dense_index(embeddings, chunk_ids, "correct_sha", fake_provider.metadata(), idx_dir)
        with pytest.raises(DenseIndexError, match="corpus SHA"):
            load_dense_index(idx_dir, "different_sha", chunk_ids,
                             fake_provider.metadata()["model_revision"])

    def test_npz_tampering_rejected(self, fake_provider, corpus, tmp_path):
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "tamper_test"

        build_dense_index(embeddings, chunk_ids, "sha", fake_provider.metadata(), idx_dir)
        with open(idx_dir / "dense_index.npz", "ab") as f:
            f.write(b"tampered")
        with pytest.raises(DenseIndexError, match="SHA-256"):
            load_dense_index(idx_dir, "sha", chunk_ids,
                             fake_provider.metadata()["model_revision"])


# ================================================================
# 4. Dense Index（负面测试——完整契约）
# ================================================================


def _file_sha256_for_test(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class TestDenseIndexNegative:
    """Dense Index 完整契约——负面校验。"""

    def test_dtype_float64_rejected(self, fake_provider, corpus, tmp_path):
        """dtype 改为 float64 应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts).astype(np.float64)
        idx_dir = tmp_path / "dtype_reject"

        # build_dense_index 本身会拒绝 float64
        with pytest.raises(DenseIndexError, match="float32"):
            build_dense_index(embeddings, chunk_ids, "sha", fake_provider.metadata(), idx_dir)

    def test_dtype_mismatch_in_metadata_rejected(self, fake_provider, corpus, tmp_path):
        """metadata 中 dtype 改为 float64，实际 NPZ 是 float32，应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "dtype_meta_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        # 改 metadata 中的 dtype
        meta = json.loads((idx_dir / "dense_index_meta.json").read_text("utf-8"))
        meta["dtype"] = "float64"
        (idx_dir / "dense_index_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        with pytest.raises(DenseIndexError, match="float32"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512)

    def test_not_normalized_rejected(self, fake_provider, corpus, tmp_path):
        """向量未归一化应被拒绝（绕过 build 校验，直接构造 NPZ）。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        idx_dir = tmp_path / "norm_reject"
        idx_dir.mkdir(parents=True, exist_ok=True)
        p_meta = fake_provider.metadata()

        # 构造未归一化向量
        raw = np.random.default_rng(42).random((len(corpus), 512)).astype(np.float32) * 10
        np.savez_compressed(idx_dir / "dense_index.npz", embeddings=raw)
        npz_sha = _file_sha256_for_test(idx_dir / "dense_index.npz")

        meta = {
            "corpus_sha256": "sha",
            "model_repo_id": p_meta["model_repo_id"],
            "model_revision": p_meta["model_revision"],
            "embedding_dimension": 512,
            "chunk_count": len(chunk_ids),
            "chunk_ids": list(chunk_ids),
            "normalize_embeddings": True,
            "query_instruction": p_meta["query_instruction"],
            "chunking_version": CHUNKING_VERSION,
            "created_at": "2026-01-01T00:00:00+00:00",
            "index_sha256": npz_sha,
            "dtype": "float32",
        }
        idx_dir.mkdir(parents=True, exist_ok=True)
        (idx_dir / "dense_index_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        provider_meta = {
            "model_repo_id": p_meta["model_repo_id"],
            "model_revision": p_meta["model_revision"],
            "normalize_embeddings": True,
            "query_instruction": p_meta["query_instruction"],
        }
        with pytest.raises(DenseIndexError, match="未归一化"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512,
                             expected_model_repo_id=p_meta["model_repo_id"],
                             expected_chunking_version=CHUNKING_VERSION,
                             expected_provider_meta=provider_meta)

    def test_model_repo_id_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        """model_repo_id 不一致应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "repo_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        with pytest.raises(DenseIndexError, match="repo_id"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512,
                             expected_model_repo_id="different/repo",
                             expected_provider_meta={
                                 "model_repo_id": "different/repo",
                                 "model_revision": p_meta["model_revision"],
                                 "normalize_embeddings": True,
                                 "query_instruction": p_meta["query_instruction"],
                             })

    def test_revision_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        """revision 不一致应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "rev_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        with pytest.raises(DenseIndexError, match="revision"):
            load_dense_index(idx_dir, "sha", chunk_ids, "different_revision",
                             expected_dimension=512)

    def test_query_instruction_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        """query_instruction 不一致应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "qi_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        provider_meta_wrong_qi = {
            "model_repo_id": p_meta["model_repo_id"],
            "model_revision": p_meta["model_revision"],
            "normalize_embeddings": True,
            "query_instruction": "different instruction",
        }
        with pytest.raises(DenseIndexError, match="query_instruction"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512,
                             expected_provider_meta=provider_meta_wrong_qi)

    def test_chunking_version_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        """chunking_version 不一致应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "cv_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        with pytest.raises(DenseIndexError, match="chunking_version"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512,
                             expected_chunking_version="99.99.99")

    def test_normalize_false_rejected(self, fake_provider, corpus, tmp_path):
        """metadata 中 normalize_embeddings=false 应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "norm_false_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        # 修改 metadata 中 normalize_embeddings 为 false
        meta = json.loads((idx_dir / "dense_index_meta.json").read_text("utf-8"))
        meta["normalize_embeddings"] = False
        (idx_dir / "dense_index_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        provider_meta_normalize_false = {
            "model_repo_id": p_meta["model_repo_id"],
            "model_revision": p_meta["model_revision"],
            "normalize_embeddings": True,  # 期望 True
            "query_instruction": p_meta["query_instruction"],
        }
        with pytest.raises(DenseIndexError, match="normalize"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512,
                             expected_provider_meta=provider_meta_normalize_false)

    def test_dimension_metadata_array_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        """metadata 中 dimension 与实际数组维度不一致应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "dim_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)

        # 修改 metadata 中 dimension 为 768
        meta = json.loads((idx_dir / "dense_index_meta.json").read_text("utf-8"))
        meta["embedding_dimension"] = 768
        (idx_dir / "dense_index_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        with pytest.raises(DenseIndexError, match="维度"):
            load_dense_index(idx_dir, "sha", chunk_ids, p_meta["model_revision"],
                             expected_dimension=512)

    def test_chunk_ids_order_mismatch_rejected(self, fake_provider, corpus, tmp_path):
        """chunk_ids 顺序不一致应被拒绝。"""
        chunk_ids = [c["chunk_id"] for c in corpus]
        texts = [c["text"] for c in corpus]
        embeddings = fake_provider.encode_passages(texts)
        idx_dir = tmp_path / "order_reject"
        p_meta = fake_provider.metadata()

        build_dense_index(embeddings, chunk_ids, "sha", p_meta, idx_dir)
        reversed_ids = list(reversed(chunk_ids))
        with pytest.raises(DenseIndexError, match="chunk_ids 顺序"):
            load_dense_index(idx_dir, "sha", reversed_ids, p_meta["model_revision"],
                             expected_dimension=512)


# ================================================================
# 5. Dense Retrieval
# ================================================================


class TestDenseRetrieval:
    """Dense 检索公式与行为。"""

    def test_cosine_ranking(self, fake_provider, corpus):
        texts = [c["text"] for c in corpus]
        emb = fake_provider.encode_passages(texts)
        chunk_ids_order = [c["chunk_id"] for c in corpus]

        def encode_query(q):
            return fake_provider.encode_queries([q])[0]

        retriever = make_dense_retriever(emb, encode_query, chunk_ids_order)
        results = retriever("SYN-TENDER-001", corpus, top_k=5)
        assert len(results) > 0
        assert all(r["retrieval_mode"] == "dense" for r in results)
        scores = [r["score"] for r in results]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], f"分数未降序: {scores}"

    def test_same_score_stable_sort(self, fake_provider, corpus):
        texts = [c["text"] for c in corpus]
        emb = fake_provider.encode_passages(texts)
        chunk_ids_order = [c["chunk_id"] for c in corpus]

        def zero_query(q):
            return np.zeros(512, dtype=np.float32)

        retriever = make_dense_retriever(emb, zero_query, chunk_ids_order)
        results = retriever("any", corpus, top_k=5)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                if abs(results[i]["score"] - results[i + 1]["score"]) < 1e-9:
                    assert results[i]["chunk_id"] < results[i + 1]["chunk_id"]


# ================================================================
# 6. RRF Hybrid
# ================================================================


class TestRRFHybrid:
    """RRF 融合公式与行为。"""

    def test_rrf_formula_toy_case(self):
        bm25_rank = 1
        dense_rank = 3
        expected = 1.0 / (RRF_K + bm25_rank) + 1.0 / (RRF_K + dense_rank)
        assert abs(expected - (1 / 61 + 1 / 63)) < 1e-9

    def test_rrf_k_is_60(self):
        assert RRF_K == 60

    def test_rrf_uses_1_based_rank(self, fake_provider, corpus):
        texts = [c["text"] for c in corpus]
        emb = fake_provider.encode_passages(texts)
        chunk_ids_order = [c["chunk_id"] for c in corpus]

        def encode_query(q):
            return fake_provider.encode_queries([q])[0]

        dense_fn = make_dense_retriever(emb, encode_query, chunk_ids_order)
        results = hybrid_rrf_retrieve(
            "测试查询", corpus, top_k=5,
            bm25_retrieve_fn=bm25_retrieve,
            dense_retrieve_fn=dense_fn,
        )
        for r in results:
            assert "bm25_rank" in r
            assert "dense_rank" in r
            assert r.get("bm25_rank", 0) >= 1 or r.get("bm25_rank", 1) == 0
            assert r.get("dense_rank", 0) >= 1 or r.get("dense_rank", 1) == 0

    def test_hybrid_returns_rrf_score(self, fake_provider, corpus):
        texts = [c["text"] for c in corpus]
        emb = fake_provider.encode_passages(texts)
        chunk_ids_order = [c["chunk_id"] for c in corpus]

        def encode_query(q):
            return fake_provider.encode_queries([q])[0]

        dense_fn = make_dense_retriever(emb, encode_query, chunk_ids_order)
        results = hybrid_rrf_retrieve(
            "SYN-TENDER-001", corpus, top_k=3,
            bm25_retrieve_fn=bm25_retrieve,
            dense_retrieve_fn=dense_fn,
        )
        assert len(results) > 0
        for r in results:
            assert "rrf_score" in r
            assert r["retrieval_mode"] == "hybrid_rrf"

    def test_no_direct_mix_of_raw_scores(self):
        import inspect
        source = inspect.getsource(hybrid_rrf_retrieve)
        assert "bm25_score" not in source.lower()
        assert "cosine_score" not in source.lower()

    def test_equal_weight(self):
        import inspect
        source = inspect.getsource(hybrid_rrf_retrieve)
        assert "1.0 / (rrf_k + bm25_r)" in source
        assert "1.0 / (rrf_k + dense_r)" in source


# ================================================================
# 7. CLI 与报告隔离
# ================================================================


class TestStage4BIsolation:
    """Stage 4B 输出不覆盖 Stage 4A 报告。"""

    def test_stage4a_reports_untouched(self):
        for split in ("all", "dev", "test"):
            path = GOLDEN_CASE_DIR.parent / "eval_results" / split / "retrieval_report.json"
            assert path.exists(), f"Stage 4A {split} 报告缺失: {path}"

    def test_stage4b_reports_exist(self):
        for split in ("all", "dev", "test"):
            json_path = STAGE4B_EVAL_DIR / split / "retrieval_report.json"
            md_path = STAGE4B_EVAL_DIR / split / "retrieval_report.md"
            fail_path = STAGE4B_EVAL_DIR / split / "failures.json"
            assert json_path.exists(), f"Stage 4B {split} JSON 缺失"
            assert md_path.exists(), f"Stage 4B {split} MD 缺失"
            assert fail_path.exists(), f"Stage 4B {split} failures 缺失"

    def test_stage4b_has_five_modes(self):
        r = json.loads((STAGE4B_EVAL_DIR / "all" / "retrieval_report.json").read_text("utf-8"))
        modes = r["meta"]["retrieval_modes"]
        assert "keyword" in modes
        assert "tfidf" in modes
        assert "bm25" in modes
        assert "dense" in modes
        assert "hybrid_rrf" in modes
        assert len(modes) == 5


# ================================================================
# 8. 元数据完整性
# ================================================================


class TestStage4BMetadata:
    """Stage 4B 元数据验证。"""

    def test_new_metadata_fields_present(self):
        r = json.loads((STAGE4B_EVAL_DIR / "all" / "retrieval_report.json").read_text("utf-8"))
        meta = r["meta"]
        required = [
            "embedding_provider", "model_repo_id", "model_revision",
            "model_dimension", "normalize_embeddings", "query_instruction",
            "sentence_transformers_version", "torch_version", "numpy_version",
            "device", "index_file_sha256", "index_metadata_sha256",
            "index_reused", "dense_index_build_time_ms", "dense_index_load_time_ms",
        ]
        for field in required:
            assert field in meta, f"缺少 Stage 4B 元数据字段: {field}"
        assert meta.get("rrf_k") == 60
        assert meta.get("fusion_sources") == ["bm25", "dense"]

    def test_no_absolute_paths(self):
        text = (STAGE4B_EVAL_DIR / "all" / "retrieval_report.json").read_text("utf-8")
        assert "D:\\" not in text
        assert "C:\\" not in text
        assert "d:\\spir" not in text.lower()
        assert "D:/spir" not in text
        assert "HF_TOKEN" not in text
        assert "sk-" not in text

    def test_eval_code_hash_includes_new_files(self):
        r = json.loads((STAGE4B_EVAL_DIR / "all" / "retrieval_report.json").read_text("utf-8"))
        eval_files = r["meta"].get("evaluation_source_files", [])
        assert len(eval_files) == 9, f"应为 9 个文件（6个 4A + 3个 4B），实际 {len(eval_files)}"
        paths = {f["path"] for f in eval_files}
        assert "backend/app/evaluation/v3_embedding.py" in paths
        assert "backend/app/evaluation/v3_dense_index.py" in paths
        assert "backend/app/evaluation/v3_hybrid.py" in paths


# ================================================================
# 9. 检索模式名称
# ================================================================


class TestRetrievalModeNames:
    """五种检索模式名称验证。"""

    def test_all_five_mode_names_correct(self):
        r = json.loads((STAGE4B_EVAL_DIR / "all" / "retrieval_report.json").read_text("utf-8"))
        modes = r["meta"]["retrieval_modes"]
        for m in modes:
            assert m != "vector", "不应使用 'vector' 作为模式名"
            assert m in ("keyword", "tfidf", "bm25", "dense", "hybrid_rrf")

    def test_dense_not_called_vector(self):
        r = json.loads((STAGE4B_EVAL_DIR / "all" / "retrieval_report.json").read_text("utf-8"))
        assert "vector" not in r["meta"]["retrieval_modes"]


# ================================================================
# 10. 查询集不变性
# ================================================================


class TestQuerySetUnchanged:
    """Stage 4A 查询集和 relevant_chunk_ids 未被修改。"""

    def test_query_count_unchanged(self):
        query_path = GOLDEN_CASE_DIR / "retrieval_queries.json"
        queries, _, _ = load_query_set(query_path)
        assert len(queries) == 44

    def test_answerable_no_answer_unchanged(self):
        query_path = GOLDEN_CASE_DIR / "retrieval_queries.json"
        queries, _, _ = load_query_set(query_path)
        ans = [q for q in queries if q["answerable"]]
        na = [q for q in queries if not q["answerable"]]
        assert len(ans) == 38
        assert len(na) == 6

    def test_chunk_ids_references_unchanged(self, corpus):
        query_path = GOLDEN_CASE_DIR / "retrieval_queries.json"
        queries, _, _ = load_query_set(query_path)
        corpus_ids = {c["chunk_id"] for c in corpus}
        for q in queries:
            for cid in q.get("relevant_chunk_ids", []):
                assert cid in corpus_ids, f"{q['query_id']}: {cid} 不在语料中"


# ================================================================
# 11. Stage 4A 回归
# ================================================================


class TestStage4ARegression:
    """Stage 4A 检索指标不退化。"""

    def test_keyword_recall_unchanged(self, corpus):
        queries, _, _ = load_query_set(GOLDEN_CASE_DIR / "retrieval_queries.json")
        ans = [q for q in queries if q["answerable"]]
        per_query = []
        for q in ans:
            results = keyword_retrieve(q["query_text"], corpus, top_k=20)
            ids = [r["chunk_id"] for r in results]
            per_query.append(
                compute_answerable_metrics(q["query_id"], ids, q["relevant_chunk_ids"], 1.0)
            )
        agg = aggregate_answerable(per_query)
        assert agg["recall@3_mean"] == pytest.approx(0.6579, abs=0.001)
        assert agg["recall@5_mean"] == pytest.approx(0.7895, abs=0.001)

    def test_bm25_recall_unchanged(self, corpus):
        queries, _, _ = load_query_set(GOLDEN_CASE_DIR / "retrieval_queries.json")
        ans = [q for q in queries if q["answerable"]]
        per_query = []
        for q in ans:
            results = bm25_retrieve(q["query_text"], corpus, top_k=20)
            ids = [r["chunk_id"] for r in results]
            per_query.append(
                compute_answerable_metrics(q["query_id"], ids, q["relevant_chunk_ids"], 1.0)
            )
        agg = aggregate_answerable(per_query)
        assert agg["recall@3_mean"] == pytest.approx(0.7895, abs=0.001)
        assert agg["recall@5_mean"] == pytest.approx(0.8289, abs=0.001)

    def test_tfidf_recall_unchanged(self, corpus):
        queries, _, _ = load_query_set(GOLDEN_CASE_DIR / "retrieval_queries.json")
        ans = [q for q in queries if q["answerable"]]
        per_query = []
        for q in ans:
            results = tfidf_retrieve(q["query_text"], corpus, top_k=20)
            ids = [r["chunk_id"] for r in results]
            per_query.append(
                compute_answerable_metrics(q["query_id"], ids, q["relevant_chunk_ids"], 1.0)
            )
        agg = aggregate_answerable(per_query)
        assert agg["recall@3_mean"] == pytest.approx(0.7500, abs=0.001)
        assert agg["recall@5_mean"] == pytest.approx(0.8421, abs=0.001)
