"""code-review-eval-harness: 代码评审 Agent 双层评测框架。

对外暴露的核心入口：
- evaluate: 同步评测（兼容保留）
- evaluate_async: 工业级异步评测（并发 + run store + 门禁）
- Harness / ModelEvaluator / Report: 双层评测核心
- build_dataset: 数据管线（真实 PR + 合成 + 质量校验）
- QualityGate / RunStore: 门禁与可复现 run 管理
"""

from .schema import Defect, Sample, ReviewIssue
from .harness import Harness
from .aligner import ModelEvaluator
from .location import LocationSpan, parse_location
from .semantic import EmbeddingSemanticMatcher, NoopSemanticMatcher, cosine_similarity
from .report import Report
from .gate import QualityGate, GateResult
from .runstore import RunStore, RunArtifact, RunConfig
from .evaluate import evaluate, evaluate_async, load_samples
from .dashboard import extract_from_report, extract_trend, render_dashboard, write_dashboard
from .backends import OpenAIAsyncBackend, OpenAICompatibleBackend

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
]
