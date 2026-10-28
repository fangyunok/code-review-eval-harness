"""评测集加载与一键评测入口。

evaluate() 是框架的顶层 API：
1. 加载评测集（JSONL）；
2. 对每个后端，用 Harness 跑评审 + 记录 Harness 层指标；
3. 用 ModelEvaluator 做对齐打分 + 聚合；
4. 汇总成 Report，输出归因与报告。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .aligner import ModelEvaluator
from .harness import BaseBackend, Harness
from .report import ModelRunResult, Report
from .schema import Sample


def load_samples(path: str) -> List[Sample]:
    """从 JSONL 文件加载评测集，每行一个样本。"""
    samples: List[Sample] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(Sample.from_dict(json.loads(line)))
    return samples


def evaluate(
    samples: List[Sample],
    backends: Dict[str, BaseBackend],
    output_dir: Optional[str] = None,
) -> Report:
    """跑完整评测，返回 Report。若给 output_dir 则同时落盘报告。"""
    harnesses = {name: Harness(backend) for name, backend in backends.items()}
    evaluator = ModelEvaluator()

    runs: List[ModelRunResult] = []
    for name, harness in harnesses.items():
        parse_ok = 0
        format_ok = 0
        total = 0
        sample_results = []

        for sample in samples:
            total += 1
            out = harness.review(sample)
            if out["parse_ok"]:
                parse_ok += 1
            if out["format_ok"]:
                format_ok += 1
            res = evaluator.evaluate_sample(sample, out["issues"])
            sample_results.append(res)

        harness_metrics = {
            "parse_rate": parse_ok / total if total else 0.0,
            "format_ok_rate": format_ok / total if total else 0.0,
            "total": total,
        }
        model_metrics = evaluator.aggregate(sample_results)

        runs.append(
            ModelRunResult(
                name=name,
                harness=harness_metrics,
                model=model_metrics,
                per_sample=sample_results,
            )
        )

    report = Report(runs)
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        report.write(str(out / "report.json"), str(out / "report.md"))
    return report


def evaluate_async(
    samples: List[Sample],
    async_backends: Dict[str, Any],
    run_store: Optional[Any] = None,
    gate: Optional[Any] = None,
    max_concurrency: int = 8,
    max_retries: int = 3,
    timeout: float = 60.0,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """工业级异步评测入口：并发执行 + 结果落盘 run store + 质量门禁。

    返回一个 dict，包含：
    - report: Report 对象
    - metrics_by_backend: {后端名: {f1, recall, precision, ...}}，供门禁与趋势
    - gate_result: 门禁结果（若传入 gate）
    - run_id: 本次 run 的唯一 id（若传入 run_store）
    """
    import asyncio

    from .async_eval import AsyncEvaluator
    from .harness import Harness
    from .runstore import RunArtifact, new_run_id

    evaluator = ModelEvaluator()
    runs: List[ModelRunResult] = []
    metrics_by_backend: Dict[str, Dict[str, float]] = {}

    for name, backend in async_backends.items():
        harness = Harness(None)  # 只复用 prompt 构造与解析，不走同步 complete
        async_runner = AsyncEvaluator(
            harness=harness,
            backend=backend,
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            timeout=timeout,
        )

        outcomes = asyncio.run(async_runner.evaluate_all(samples))

        parse_ok = 0
        format_ok = 0
        failed = 0
        total = len(samples)
        sample_results = []

        for sample in samples:
            outcome = outcomes[sample.id]
            if outcome.failed:
                failed += 1
                # 失败样本按「无输出」处理：漏报全部标准缺陷
                sample_results.append(
                    evaluator.evaluate_sample(sample, [])
                )
                continue
            if outcome.parse_ok:
                parse_ok += 1
            if outcome.format_ok:
                format_ok += 1
            sample_results.append(
                evaluator.evaluate_sample(sample, outcome.issues)
            )

        harness_metrics = {
            "parse_rate": parse_ok / total if total else 0.0,
            "format_ok_rate": format_ok / total if total else 0.0,
            "failed": failed,
            "total": total,
        }
        model_metrics = evaluator.aggregate(sample_results)

        runs.append(
            ModelRunResult(
                name=name,
                harness=harness_metrics,
                model=model_metrics,
                per_sample=sample_results,
            )
        )
        metrics_by_backend[name] = {
            "f1": model_metrics["f1"],
            "precision": model_metrics["precision"],
            "recall": model_metrics["recall"],
            "missed_critical_count": model_metrics["missed_critical_count"],
            "false_positive_count": model_metrics["false_positive_count"],
        }

    report = Report(runs)

    result: Dict[str, Any] = {
        "report": report,
        "metrics_by_backend": metrics_by_backend,
        "gate_result": None,
        "run_id": None,
    }

    # 质量门禁
    if gate is not None:
        result["gate_result"] = gate.check(metrics_by_backend)

    # 落盘 run store
    if run_store is not None:
        run_id = new_run_id()
        artifact = RunArtifact(
            run_id=run_id,
            created_at=_now(),
            config=config or {},
            result=report.to_dict(),
            metrics=metrics_by_backend,
        )
        run_store.save(artifact, report_md=report.to_markdown())
        result["run_id"] = run_id

    return result


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
