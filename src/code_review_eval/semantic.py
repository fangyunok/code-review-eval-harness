"""语义嵌入对齐（可选）：用文本嵌入算「模型意见」与「标准缺陷」的语义相似度。

这是对齐的增强模式，默认不启用（保持核心零依赖、离线可复现）。
当措辞完全不同、关键词也对不上时，语义相似度是唯一能判「同一件事」的手段。

设计为「可插拔」：SemanticMatcher 是一个接口，默认实现是 NoopSemanticMatcher
（返回 0，即不参与打分）；需要语义对齐时，传入一个实现 embed() 的匹配器即可。
这样核心逻辑零依赖，语义能力由调用方注入，符合依赖倒置原则。
"""

from __future__ import annotations

import math
from typing import Protocol


class Embedder(Protocol):
    """嵌入接口：把一段文本映射为向量。由调用方注入具体实现。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个向量的余弦相似度（0~1）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class NoopSemanticMatcher:
    """默认匹配器：不参与打分，返回 0（核心零依赖模式）。"""

    def similarity(self, pred_text: str, gt_text: str) -> float:
        return 0.0


class EmbeddingSemanticMatcher:
    """用 embedding 计算语义相似度的匹配器。

    内部做批量嵌入 + 缓存，避免对同一段文本重复调用 embed()。
    """

    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self._cache: dict = {}

    def similarity(self, pred_text: str, gt_text: str) -> float:
        key = (pred_text, gt_text)
        if key in self._cache:
            return self._cache[key]
        try:
            vecs = self.embedder.embed([pred_text, gt_text])
            sim = cosine_similarity(vecs[0], vecs[1])
        except Exception:
            # 嵌入失败不应拖垮对齐，降级为 0（不参与）
            sim = 0.0
        self._cache[key] = sim
        return sim


class SentenceTransformerEmbedder:
    """本地 sentence-transformers 嵌入实现（离线、零 API 调用）。

    需安装 `sentence-transformers`：pip install -e ".[embeddings]"。
    首次加载会下载模型权重；之后缓存于内存，重复调用不再重复加载。
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "使用 SentenceTransformerEmbedder 需要安装 sentence-transformers："
                    "pip install -e \".[embeddings]\""
                ) from e
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vecs = model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]


class OpenAIEmbeddingEmbedder:
    """OpenAI 兼容的 embedding API 实现（云端向量）。

    任意实现 /v1/embeddings 协议的服务都能接（OpenAI / DeepSeek / 通义等）。
    需安装 openai：pip install -e ".[openai]"。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "使用 OpenAIEmbeddingEmbedder 需要安装 openai："
                    "pip install -e \".[openai]\""
                ) from e
            kwargs = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        resp = client.embeddings.create(model=self.model, input=texts)
        # 按输入顺序返回向量
        data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in data]
