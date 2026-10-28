"""离线演示：用 FakeBackend 模拟两个模型跑通完整评测链路。

不依赖任何真实模型或 API Key，直接 `python demo.py` 即可复现全流程：
加载评测集 -> Harness 评审 -> 对齐打分 -> 归因 -> 输出报告。

运行方式（在仓库根目录）：
    python demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from code_review_eval.evaluate import evaluate, load_samples
from code_review_eval.harness import FakeBackend

# 模拟「模型 A」：能找出 SQL 注入和除零，但漏掉性能问题和风格问题
MODEL_A_RESPONSES = [
    # sample-001 命中 SQL 注入（位置对得上）
    '{"issues": [{"type": "security", "severity": "critical", '
    '"message": "字符串拼接导致 SQL 注入", "location": "payment.py:42"}]}',
    # sample-002 命中除零
    '{"issues": [{"type": "logic", "severity": "critical", '
    '"message": "count 可能为 0 导致除零", "location": "billing.py:18"}]}',
    # sample-003 漏报（输出空）
    '{"issues": []}',
    # sample-004 漏报
    '{"issues": []}',
    # sample-005 只报一条，漏掉异常处理
    '{"issues": [{"type": "logic", "severity": "major", '
    '"message": "文件未关闭", "location": "loader.py:9"}]}',
]

# 模拟「模型 B」：更全面，但也有一处误报（位置错误）
MODEL_B_RESPONSES = [
    '{"issues": [{"type": "security", "severity": "critical", '
    '"message": "SQL 注入风险", "location": "payment.py:42"}]}',
    '{"issues": [{"type": "logic", "severity": "critical", '
    '"message": "除零未防护", "location": "billing.py:18"}]}',
    '{"issues": [{"type": "performance", "severity": "major", '
    '"message": "循环内拼接字符串应用 join", "location": "report.py:33"}]}',
    '{"issues": [{"type": "style", "severity": "minor", '
    '"message": "命名与缩进不规范", "location": "utils.py:5"}]}',
    '{"issues": [{"type": "logic", "severity": "major", '
    '"message": "文件未关闭", "location": "loader.py:9"}, '
    '{"type": "logic", "severity": "minor", '
    '"message": "未处理异常", "location": "loader.py:9"}, '
    '{"type": "security", "severity": "minor", '
    '"message": "疑似路径遍历", "location": "loader.py:100"}]}',
]


def main() -> None:
    samples = load_samples("data/samples.jsonl")
    backends = {
        "model-a": FakeBackend(list(MODEL_A_RESPONSES)),
        "model-b": FakeBackend(list(MODEL_B_RESPONSES)),
    }
    report = evaluate(samples, backends, output_dir="reports")
    print(report.to_markdown())


if __name__ == "__main__":
    main()
