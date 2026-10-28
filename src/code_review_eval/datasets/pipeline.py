"""数据管线统一入口：真实 PR 抽取 + 合成数据生成 -> 质量校验 -> 落盘 JSONL。

命令行用法：
    python -m code_review_eval.datasets.pipeline \
        --output data/benchmark.jsonl \
        --synthetic 200 \
        [--repo owner/repo] [--pr-per-page 10] [--token-file .gh-token]

真实 PR 抽取是可选的（需要网络 + 可能触发 rate limit），
合成数据始终生成，保证离线也能产出可用的评测集。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .synthetic import generate_samples
from .validation import validate_samples


def build_dataset(
    output: str,
    synthetic_count: int = 200,
    repo: Optional[str] = None,
    token: Optional[str] = None,
    pr_per_page: int = 10,
    seed: int = 42,
) -> dict:
    """构建评测集：合成数据 +（可选）真实 PR 数据，校验后落盘。

    返回一个汇总 dict，记录来源构成与校验结果。
    """
    samples: List[dict] = []

    # 1) 合成数据（始终生成，确定性可复现）
    samples.extend(generate_samples(synthetic_count, seed=seed, repo="synthetic"))

    # 2) 真实 PR 数据（可选，需要网络）
    real_count = 0
    real_error = None
    if repo:
        try:
            from .github_source import GitHubPRSource

            src = GitHubPRSource(token=token)
            real_samples = src.to_samples(repo, per_page=pr_per_page)
            real_count = len(real_samples)
            samples.extend(real_samples)
        except Exception as e:  # 网络/限流失败不影响合成数据产出
            real_error = str(e)

    # 3) 质量校验 + 去重
    clean, report = validate_samples(samples)

    # 4) 落盘 JSONL
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for s in clean:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    return {
        "output": str(out),
        "synthetic_requested": synthetic_count,
        "real_collected": real_count,
        "real_error": real_error,
        "total": report.total,
        "passed": report.passed,
        "dropped_duplicate": report.dropped_duplicate,
        "dropped_invalid": report.dropped_invalid,
        "pass_rate": report.pass_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建代码评审评测集")
    parser.add_argument("--output", default="data/benchmark.jsonl")
    parser.add_argument("--synthetic", type=int, default=200)
    parser.add_argument("--repo", default=None, help="owner/repo，如 pandas-dev/pandas")
    parser.add_argument("--pr-per-page", type=int, default=10)
    parser.add_argument("--token-file", default=None, help="GitHub token 文件路径")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    token = None
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()

    result = build_dataset(
        output=args.output,
        synthetic_count=args.synthetic,
        repo=args.repo,
        token=token,
        pr_per_page=args.pr_per_page,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
