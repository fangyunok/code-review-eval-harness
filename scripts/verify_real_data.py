"""真实数据抽取验证：从真实 GitHub 仓库抽取 PR 评测集并产出质量报告。

用于验证「数据管线跑过真实数据」——这是评测集可信度的硬证据。

用法（需要 GitHub token，网络正常时运行）：
    python scripts/verify_real_data.py --repo psf/requests --token-file .gh-token

产出：
    data/benchmark_real.jsonl   真实 + 合成混合评测集
    打印抽取质量报告（真实样本数、缺陷类型/严重度分布、样例展示）
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.datasets.pipeline import build_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="真实数据抽取验证")
    parser.add_argument("--repo", default="psf/requests", help="owner/repo")
    parser.add_argument("--token-file", required=True, help="GitHub token 文件")
    parser.add_argument("--pr-per-page", type=int, default=20)
    parser.add_argument("--synthetic", type=int, default=100)
    parser.add_argument("--output", default="data/benchmark_real.jsonl")
    args = parser.parse_args()

    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    result = build_dataset(
        output=args.output,
        synthetic_count=args.synthetic,
        repo=args.repo,
        token=token,
        pr_per_page=args.pr_per_page,
    )

    print("=" * 60)
    print("真实数据抽取验证报告")
    print("=" * 60)
    print(f"目标仓库: {args.repo}")
    print(f"合成样本: {result['synthetic_requested']}")
    print(f"真实样本: {result['real_collected']}")
    print(f"总样本: {result['passed']}（去重 {result['dropped_duplicate']}，无效 {result['dropped_invalid']}）")
    print(f"通过率: {result['pass_rate']:.1%}")
    if result["real_error"]:
        print(f"真实抽取错误: {result['real_error']}")
    print()

    # 分析真实样本的缺陷分布
    type_counter = Counter()
    severity_counter = Counter()
    real_samples = []
    with open(result["output"], encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["repo"] == args.repo:
                real_samples.append(d)
                for defect in d["defects"]:
                    type_counter[defect["type"]] += 1
                    severity_counter[defect["severity"]] += 1

    if real_samples:
        print(f"真实样本缺陷类型分布: {dict(type_counter)}")
        print(f"真实样本严重度分布: {dict(severity_counter)}")
        print()
        print("样例（前 2 条真实样本的缺陷）：")
        for s in real_samples[:2]:
            print(f"  PR {s['id']}: {s['title'][:60]}")
            for defect in s["defects"][:3]:
                print(f"    - [{defect['type']}/{defect['severity']}] {defect['message'][:50]} @ {defect['location']}")
    else:
        print("（本次未抽取到真实样本，可能是目标仓库近期 PR 无 review comment，或网络受限）")


if __name__ == "__main__":
    main()
