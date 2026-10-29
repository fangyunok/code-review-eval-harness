"""语义嵌入（semantic.py）的单元测试。

验证 embedder 实现和语义匹配器：不依赖真实模型，用 monkeypatch
伪造 embedder，测 cosine、缓存、降级、以及 OpenAI embedding 客户端调用逻辑。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.semantic import (
    EmbeddingSemanticMatcher,
    OpenAIEmbeddingEmbedder,
    cosine_similarity,
)


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    assert cosine_similarity([], [1]) == 0.0
    assert abs(cosine_similarity([1, 1], [1, 1]) - 1.0) < 1e-9


class _FakeEmbedder:
    def __init__(self, vecs):
        self.vecs = vecs
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return self.vecs


def test_embedding_matcher_computes_similarity_and_caches():
    matcher = EmbeddingSemanticMatcher(_FakeEmbedder([[1.0, 0.0], [1.0, 0.0]]))
    s1 = matcher.similarity("a", "b")
    s2 = matcher.similarity("a", "b")
    assert s1 == 1.0
    assert s2 == 1.0
    # 第二次命中缓存，embed 只调用一次
    assert matcher.embedder.calls == 1


def test_embedding_matcher_degrades_on_failure():
    class _Boom:
        def embed(self, texts):
            raise RuntimeError("embed failed")

    matcher = EmbeddingSemanticMatcher(_Boom())
    assert matcher.similarity("a", "b") == 0.0


def test_openai_embedding_embedder(monkeypatch):
    emb = OpenAIEmbeddingEmbedder(api_key="sk-test", model="emb-test")

    class _D:
        def __init__(self, idx, vec):
            self.index = idx
            self.embedding = vec

    class _Resp:
        data = [_D(1, [0.0, 1.0]), _D(0, [1.0, 0.0])]

    class _Embeddings:
        def create(self, **kwargs):
            return _Resp()

    fake = type("C", (), {"embeddings": _Embeddings()})()
    emb._client = fake
    vecs = emb.embed(["a", "b"])
    # 按 index 排序，顺序恢复为输入顺序
    assert vecs == [[1.0, 0.0], [0.0, 1.0]]
