"""工业级评测 CLI：一键构建评测集 + 异步评测 + 质量门禁。

用法：
    python -m code_review_eval.cli eval \
        --benchmark data/benchmark.jsonl \
        --thresholds '{"f1": 0.5}' \
        [--synthetic 200] [--repo owner/repo]

退出码：通过=0，未通过=1，可直接接 CI 当质量否决项。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .async_eval import FakeAsyncBackend
from .evaluate import evaluate_async, load_samples
from .gate import QualityGate
from .runstore import RunStore
from .schema import Sample


def _build_backends_from_responses(responses: Dict[str, List[str]]):
    """从预置响应构建异步后端（离线演示用）。"""
    return {name: FakeAsyncBackend(list(resps)) for name, resps in responses.items()}


def cmd_eval(args) -> int:
    # 1) 构建评测集（可选）
    if args.synthetic or args.repo:
        from .datasets.pipeline import build_dataset

        token = None
        if args.token_file:
            token = Path(args.token_file).read_text(encoding="utf-8").strip()
        build_dataset(
            output=args.benchmark,
            synthetic_count=args.synthetic or 0,
            repo=args.repo,
            token=token,
            pr_per_page=args.pr_per_page,
            seed=args.seed,
        )

    # 2) 加载评测集
    samples = load_samples(args.benchmark)
    if not samples:
        print(f"评测集为空：{args.benchmark}", file=sys.stderr)
        return 1

    # 3) 构造后端：默认离线 FakeAsyncBackend（全命中），真实后端需另行配置
    backends: Dict[str, object] = {
        "offline-demo": FakeAsyncBackend()
    }

    # 4) 门禁
    thresholds = json.loads(args.thresholds) if args.thresholds else {"f1": 0.5}
    gate = QualityGate(thresholds)

    # 5) 异步评测 + 落盘
    store = RunStore(base_dir=args.runs_dir)
    result = evaluate_async(
        samples=samples,
        async_backends=backends,
        run_store=store,
        gate=gate,
        max_concurrency=args.concurrency,
        max_retries=args.retries,
        timeout=args.timeout,
        config={"benchmark": args.benchmark, "thresholds": thresholds, "seed": args.seed},
    )

    # 5.5) 生成归因看板
    if args.dashboard:
        from .dashboard import extract_from_report, extract_trend, write_dashboard

        dash_data = extract_from_report(result["report"])
        trend = extract_trend(store, metric="f1")
        dash_path = args.dashboard
        write_dashboard(dash_data, dash_path, trend=trend)
        print(f"\n归因看板已生成：{dash_path}")

    # 6) 输出
    report = result["report"]
    print(report.to_markdown())
    gate_result = result["gate_result"]
    if gate_result:
        print("\n## 质量门禁")
        print(f"通过：{'是' if gate_result.passed else '否'}（退出码 {gate_result.exit_code}）")
        for c in gate_result.checks:
            flag = "OK" if c["ok"] else "FAIL"
            print(f"  [{flag}] {c['backend']} {c['metric']}={c['value']} >= {c['threshold']}")

    return gate_result.exit_code if gate_result else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="creh", description="代码评审 Agent 工业级评测")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("eval", help="构建评测集并评测")
    p.add_argument("--benchmark", default="data/benchmark.jsonl")
    p.add_argument("--synthetic", type=int, default=200)
    p.add_argument("--repo", default=None)
    p.add_argument("--pr-per-page", type=int, default=10)
    p.add_argument("--token-file", default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--thresholds", default='{"f1": 0.5}')
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--dashboard", default=None, help="归因看板输出路径（如 dashboard.html）")

    args = parser.parse_args()
    if args.cmd == "eval":
        sys.exit(cmd_eval(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
