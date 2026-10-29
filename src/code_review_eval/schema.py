"""数据模型：评测集样本、标准缺陷、模型评审输出。

这些 dataclass 是整个框架的数据契约，Harness 层和 Model 层都依赖它。
关键设计：每条缺陷带「类型 + 严重度 + 位置」，这是能做字段级对齐打分（而非整段模糊打分）的前提。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 缺陷类型枚举：对应代码评审里最常见的四类缺陷
DEFECT_TYPES = ("logic", "security", "performance", "style")

# 严重度枚举：critical 是最不能漏的，也是归因分析重点关注的
SEVERITIES = ("critical", "major", "minor")


@dataclass
class Defect:
    """人工标注的一条标准缺陷（ground truth）。

    location 用于对齐：一个缺陷必须能落到具体位置（文件 + 行号或符号名），
    否则模型输出和标准答案之间无法做「同一条缺陷」的判定。
    """

    id: str
    type: str  # logic / security / performance / style
    severity: str  # critical / major / minor
    message: str  # 这条缺陷是什么，标准表述
    location: str  # 位置标识，如 "src/util.py:42" 或函数名
    category: str | None = None  # 更细的子类，如 security 下的 SQL 注入


@dataclass
class Sample:
    """一条评测样本：给模型一段代码/diff + 上下文，期望它找出标准缺陷列表。

    diff 是模型评审的对象，context 提供必要的背景（比如这是哪个模块、依赖什么）。
    """

    id: str
    title: str
    diff: str
    context: str = ""
    defects: list[Defect] = field(default_factory=list)
    repo: str = ""  # 来源仓库/产品线，便于归因时按产品线聚合

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sample:
        defects = [
            Defect(
                id=d["id"],
                type=d["type"],
                severity=d["severity"],
                message=d["message"],
                location=d["location"],
                category=d.get("category"),
            )
            for d in data.get("defects", [])
        ]
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            diff=data["diff"],
            context=data.get("context", ""),
            defects=defects,
            repo=data.get("repo", ""),
        )


@dataclass
class ReviewIssue:
    """模型输出的一条评审意见（预测）。

    与 Defect 结构对齐，便于做对齐打分。
    """

    type: str
    severity: str
    message: str
    location: str = ""
    category: str | None = None
