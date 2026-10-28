"""code-review-eval-harness: 代码评审 Agent 双层评测框架。

对外暴露的核心入口：
- evaluate: 一键跑完整评测，输出报告
- Harness: 统一 LLM 调用脚手架（Harness 层）
- ModelEvaluator: 缺陷对齐打分（Model 层）
"""

from .schema import Defect, Sample, ReviewIssue
from .harness import Harness
from .aligner import ModelEvaluator
from .report import Report

__version__ = "0.1.0"

__all__ = [
    "Defect",
    "Sample",
    "ReviewIssue",
    "Harness",
    "ModelEvaluator",
    "Report",
]
