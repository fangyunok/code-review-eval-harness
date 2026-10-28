"""数据集子包：真实 PR 抽取、合成数据生成、质量校验、管线入口。"""

from .synthetic import generate_samples
from .validation import validate_samples, ValidationReport

__all__ = [
    "generate_samples",
    "validate_samples",
    "ValidationReport",
]
