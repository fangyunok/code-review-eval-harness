"""数据质量校验：去重、字段完整性、标注一致性。

评测集质量直接决定评测分数可信度。本模块在数据入库前做三道校验：
1. 字段完整性：必填字段是否存在、枚举是否合法、diff 是否非空；
2. 去重：按 diff 内容哈希去重，防止重复样本稀释指标；
3. 标注一致性：同一缺陷 id 不应重复、缺陷必须能落到具体位置。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List

from ..schema import DEFECT_TYPES, SEVERITIES


@dataclass
class ValidationReport:
    total: int = 0
    passed: int = 0
    dropped_duplicate: int = 0
    dropped_invalid: int = 0
    issues: List[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0


def _valid_sample(s: Dict) -> bool:
    """单条样本是否通过字段完整性校验。"""
    if not s.get("id") or not s.get("diff", "").strip():
        return False
    defects = s.get("defects")
    if not isinstance(defects, list) or not defects:
        return False
    seen_ids = set()
    for d in defects:
        if d.get("type") not in DEFECT_TYPES:
            return False
        if d.get("severity") not in SEVERITIES:
            return False
        if not d.get("message", "").strip():
            return False
        # 缺陷必须能落到具体位置，否则无法对齐打分
        if not d.get("location", "").strip():
            return False
        if d["id"] in seen_ids:
            return False  # 同一缺陷 id 重复 = 标注不一致
        seen_ids.add(d["id"])
    return True


def _diff_hash(s: Dict) -> str:
    """按 diff 内容 + repo 做去重哈希。"""
    raw = (s.get("repo", "") + "\n" + s.get("diff", "")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_samples(samples: List[Dict]) -> tuple[List[Dict], ValidationReport]:
    """校验并清洗样本列表，返回 (通过样本, 校验报告)。"""
    report = ValidationReport(total=len(samples))
    seen_hashes: set = set()
    clean: List[Dict] = []

    for s in samples:
        if not _valid_sample(s):
            report.dropped_invalid += 1
            report.issues.append(f"invalid: {s.get('id', '?')}")
            continue
        h = _diff_hash(s)
        if h in seen_hashes:
            report.dropped_duplicate += 1
            report.issues.append(f"duplicate: {s.get('id', '?')}")
            continue
        seen_hashes.add(h)
        clean.append(s)

    report.passed = len(clean)
    return clean, report
