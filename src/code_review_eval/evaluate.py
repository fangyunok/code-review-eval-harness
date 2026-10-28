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
