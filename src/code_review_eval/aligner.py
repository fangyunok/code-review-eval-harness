"""Model 层：缺陷对齐打分（Precision / Recall / F1）。

在 Harness 层已稳定的前提下，这一层评测「模型评审能力」。

核心难点是「对齐」：模型输出的评审意见和人工标注的标准缺陷，
不会逐字相同，必须判定「这条预测对应哪条标准缺陷」。

对齐规则（按优先级）：
1. 位置匹配：预测的 location 与某条标准缺陷的 location 一致（或互相包含）；
2. 类型匹配：预测 type == 标准 type；
3. 语义兜底：位置没对上但类型对上时，用关键词重叠判断是否指向同一缺陷。

对齐结果分三类：
- TP（命中）：预测找到了标准缺陷；
- FP（误报）：预测了不存在的缺陷；
- FN（漏报）：标准缺陷模型没找到。

指标：
- Precision = TP / (TP + FP) —— 报得准不准（误报越低越好）
- Recall = TP / (TP + FN) —— 找得全不全（漏报越少越好）
- F1 = 调和平均
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .schema import Defect, ReviewIssue, Sample


def _norm(s: str) -> str:
    """归一化：小写 + 去空白，用于位置/关键词的宽松比较。"""
    return re.sub(r"\s+", "", (s or "").lower())


def _tokenize(s: str) -> set:
    """把文本拆成单词集合，用于语义兜底的关键词重叠。"""
    return set(re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", (s or "").lower()))


@dataclass
class SampleResult:
    """单个样本的对齐结果。"""

    sample_id: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    missed_critical: List[Defect] = field(default_factory=list)
    missed_by_type: Dict[str, int] = field(default_factory=dict)
    false_positives: List[ReviewIssue] = field(default_factory=list)


class ModelEvaluator:
    """把预测的评审意见对齐到标准缺陷，产出样本级与聚合级分数。"""

    def __init__(self, location_weight: float = 0.6, keyword_overlap: float = 0.5):
        self.location_weight = location_weight
        self.keyword_overlap = keyword_overlap

    def evaluate_sample(
        self, sample: Sample, predicted: List[ReviewIssue]
    ) -> SampleResult:
        res = SampleResult(sample_id=sample.id)

        gt = list(sample.defects)
        matched = [False] * len(gt)  # 每条标准缺陷是否已被某条预测命中

        for pred in predicted:
            best_idx = self._match(pred, gt, matched)
            if best_idx is None:
                # 没有可匹配的标准缺陷 -> 误报
                res.fp += 1
                res.false_positives.append(pred)
            else:
                res.tp += 1
                matched[best_idx] = True

        # 未命中的标准缺陷 -> 漏报
        for i, d in enumerate(gt):
            if not matched[i]:
                res.fn += 1
                if d.severity == "critical":
                    res.missed_critical.append(d)
                res.missed_by_type[d.type] = res.missed_by_type.get(d.type, 0) + 1

        return res

    def _match(
        self, pred: ReviewIssue, gt: List[Defect], matched: List[bool]
    ) -> int | None:
        """在未命中的标准缺陷里，找与 pred 最像的一条；找不到返回 None。"""
        best_idx = None
        best_score = 0.0
        for i, d in enumerate(gt):
            if matched[i]:
                continue
            score = self._similarity(pred, d)
            if score > best_score:
                best_score = score
                best_idx = i
        # 只有相似度过阈值才算命中，避免乱配
        if best_idx is not None and best_score >= 0.5:
            return best_idx
        return None

    def _similarity(self, pred: ReviewIssue, gt: Defect) -> float:
        score = 0.0
        # 1) 位置匹配（权重最高）
        if pred.location and _norm(pred.location) == _norm(gt.location):
            score += self.location_weight
        elif pred.location and gt.location:
            p, g = _norm(pred.location), _norm(gt.location)
            if p in g or g in p:
                score += self.location_weight * 0.8
        # 2) 类型匹配
        if pred.type == gt.type:
            score += 1.0 - self.location_weight
        # 3) 语义兜底：位置没对上但类型对上时，用关键词重叠判断
        elif pred.type == gt.type:
            overlap = _tokenize(pred.message) & _tokenize(gt.message)
            if overlap and len(overlap) / max(len(_tokenize(gt.message)), 1) >= self.keyword_overlap:
                score += (1.0 - self.location_weight) * 0.8
        return score

    @staticmethod
    def aggregate(results: List[SampleResult]) -> Dict[str, Any]:
        """把多个样本结果聚合为整体 Precision / Recall / F1，以及归因分布。"""
        tp = sum(r.tp for r in results)
        fp = sum(r.fp for r in results)
        fn = sum(r.fn for r in results)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        missed_critical = [d for r in results for d in r.missed_critical]
        missed_by_type: Dict[str, int] = {}
        for r in results:
            for t, c in r.missed_by_type.items():
                missed_by_type[t] = missed_by_type.get(t, 0) + c

        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "missed_critical_count": len(missed_critical),
            "missed_critical": missed_critical,
            "missed_by_type": missed_by_type,
            "false_positive_count": fp,
        }
