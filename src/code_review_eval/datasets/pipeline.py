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
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .synthetic import generate_samples
from .validation import validate_samples


def _build_manifest(
    output: Path,
    clean: list[dict],
    sources: list[str],
    synthetic_count: int,
    seed: int,
) -> dict:
    """生成数据集版本快照（manifest），记录来源构成 + 内容哈希 + 时间戳。

    用途：让评测集可追溯——每次构建都留一个版本指纹，后续评测能
    精确对应到「哪一次构建、哪些来源、什么 seed」，保证可复现。
    """
    content_hash = hashlib.sha256()
    for s in clean:
        # 只哈希「内容」，不哈希顺序敏感的无关字段
        content_hash.update(
            json.dumps(s, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
    manifest = {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(clean),
        "synthetic_requested": synthetic_count,
        "seed": seed,
        "sources": sources,
        "content_sha256": content_hash.hexdigest(),
    }
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def build_dataset(
    output: str,
    synthetic_count: int = 200,
    repo: str | None = None,
    token: str | None = None,
    pr_per_page: int = 10,
    seed: int = 42,
    write_manifest: bool = True,
) -> dict:
    """构建评测集：合成数据 +（可选）真实 PR 数据，校验后落盘。

    repo 支持逗号分隔多个仓库（如 "psf/requests,pandas-dev/pandas"），
    一次批量抽取多个仓库合并成 benchmark。

    返回一个汇总 dict，记录来源构成与校验结果。
    """
    samples: list[dict] = []

    # 1) 合成数据（始终生成，确定性可复现）
    samples.extend(generate_samples(synthetic_count, seed=seed, repo="synthetic"))

    # 2) 真实 PR 数据（可选，需要网络）；支持多 repo 批量抽取
    repos = [r.strip() for r in (repo or "").split(",") if r.strip()]
    real_count = 0
    real_errors: dict = {}
    if repos:
        from .github_source import GitHubPRSource

        src = GitHubPRSource(token=token)
        for r in repos:
            try:
                real_samples = src.to_samples(r, per_page=pr_per_page)
                real_count += len(real_samples)
                samples.extend(real_samples)
            except Exception as e:  # 单个 repo 失败不影响其他 repo 与合成数据
                real_errors[r] = str(e)

    # 3) 质量校验 + 去重
    clean, report = validate_samples(samples)

    # 4) 落盘 JSONL
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for s in clean:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # 5) 版本快照（manifest）
    sources = ["synthetic"] + repos
    manifest = (
        _build_manifest(out, clean, sources, synthetic_count, seed)
        if write_manifest
        else None
    )

    return {
        "output": str(out),
        "synthetic_requested": synthetic_count,
        "real_collected": real_count,
        "real_errors": real_errors,
        "total": report.total,
        "passed": report.passed,
        "dropped_duplicate": report.dropped_duplicate,
        "dropped_invalid": report.dropped_invalid,
        "pass_rate": report.pass_rate,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建代码评审评测集")
    parser.add_argument("--output", default="data/benchmark.jsonl")
    parser.add_argument("--synthetic", type=int, default=200)
    parser.add_argument(
        "--repo", default=None, help="owner/repo，逗号分隔多个（如 psf/requests,pandas-dev/pandas）"
    )
    parser.add_argument("--pr-per-page", type=int, default=10)
    parser.add_argument("--token-file", default=None, help="GitHub token 文件路径")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-manifest", action="store_true", help="不生成版本快照 manifest")
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
        write_manifest=not args.no_manifest,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
