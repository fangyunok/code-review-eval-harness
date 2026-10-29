"""code-review-eval-harness: 代码评审 Agent 双层评测框架。

对外暴露的核心入口：
- evaluate: 同步评测（兼容保留）
- evaluate_async: 工业级异步评测（并发 + run store + 门禁）
- Harness / ModelEvaluator / Report: 双层评测核心
- build_dataset: 数据管线（真实 PR + 合成 + 质量校验）
- QualityGate / RunStore: 门禁与可复现 run 管理
"""

from .aligner import ModelEvaluator
from .backends import (
    AnthropicAsyncBackend,
    OllamaAsyncBackend,
    OpenAIAsyncBackend,
    OpenAICompatibleBackend,
)
from .dashboard import extract_from_report, extract_trend, render_dashboard, write_dashboard
from .evaluate import evaluate, evaluate_async, load_samples
from .gate import GateResult, QualityGate
from .harness import Harness
from .location import LocationSpan, parse_location
from .report import Report
from .runstore import RunArtifact, RunConfig, RunStore
from .schema import Defect, ReviewIssue, Sample
from .semantic import (
    EmbeddingSemanticMatcher,
    NoopSemanticMatcher,
    OpenAIEmbeddingEmbedder,
    SentenceTransformerEmbedder,
    cosine_similarity,
)

__version__ = "0.2.0"

__all__ = [
    "Defect",
    "Sample",
    "ReviewIssue",
    "Harness",
    "ModelEvaluator",
    "Report",
    "QualityGate",
    "GateResult",
    "RunStore",
    "RunArtifact",
    "RunConfig",
    "evaluate",
    "evaluate_async",
    "load_samples",
    "extract_from_report",
    "extract_trend",
    "render_dashboard",
    "write_dashboard",
    "OpenAIAsyncBackend",
    "OpenAICompatibleBackend",
    "AnthropicAsyncBackend",
    "OllamaAsyncBackend",
    "EmbeddingSemanticMatcher",
    "NoopSemanticMatcher",
    "OpenAIEmbeddingEmbedder",
    "SentenceTransformerEmbedder",
    "cosine_similarity",
    "LocationSpan",
    "parse_location",
]
