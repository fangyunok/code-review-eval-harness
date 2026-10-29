"""Model 层：缺陷对齐打分（Precision / Recall / F1）。

在 Harness 层已稳定的前提下，这一层评测「模型评审能力」。

核心难点是「对齐」：模型输出的评审意见和人工标注的标准缺陷，
不会逐字相同，必须判定「这条预测对应哪条标准缺陷」。

对齐采用三层信号，取加权最高分（每层都是 0~1 的置信度）：
1. 位置重叠：把 location 解析成「文件+行号区间」，用 IoU 判定是否指向
   同一段代码，容忍行号偏移（比字符串相等鲁棒得多）；
2. 类型强约束：type 不同则基本不可能是同一条缺陷，这是天然的负样本过滤；
3. 语义相似：可选，用 embedding 计算「意见文本」与「缺陷描述」的语义距离，
   措辞完全不同也能识别同一件事（核心零依赖模式下用词法兜底）。

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
from typing import Any, Dict, List, Optional

from .location import parse_location
from .schema import Defect, ReviewIssue, Sample
from .semantic import NoopSemanticMatcher


def _tokenize(s: str) -> set:
    """把文本拆成单词集合，用于零依赖模式下的词法兜底。"""
    return set(re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", (s or "").lower()))


def _norm(s: str) -> str:
    """归一化：小写 + 去空白，用于位置字符串的退化比较。"""
    return re.sub(r"\s+", "", (s or "").lower())


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
    """把预测的评审意见对齐到标准缺陷，产出样本级与聚合级分数。

    参数：
    - location_weight: 位置重叠在总分中的权重（0~1），其余为类型+语义；
    - location_tolerance: 位置区间扩展的行数，容忍行号偏移；
    - semantic_matcher: 语义匹配器（默认 Noop，零依赖；可注入 embedding 实现）。
    - match_threshold: 判定「命中」的最低总分。
    """

    def __init__(
        self,
        location_weight: float = 0.5,
        location_tolerance: int = 3,
        semantic_matcher: Optional[Any] = None,
        match_threshold: float = 0.5,
    ):
        self.location_weight = location_weight
        self.location_tolerance = location_tolerance
        self.semantic_matcher = semantic_matcher or NoopSemanticMatcher()
        self.match_threshold = match_threshold

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
        if best_idx is not None and best_score >= self.match_threshold:
            return best_idx
        return None

    def _similarity(self, pred: ReviewIssue, gt: Defect) -> float:
        """三层信号加权：位置重叠 + 类型强约束 + 语义相似。

        类型是强约束（硬否决）：代码评审里「安全缺陷」和「风格缺陷」
        不可能是同一条，类型不同直接返回 0，避免位置巧合导致的乱配。
        """
        # 类型强约束：不同则直接不匹配
        if pred.type != gt.type:
            return 0.0

        # 1) 位置重叠（0~1）
        loc_score = self._location_score(pred.location, gt.location)

        # 2) 语义相似：措辞层面的相似度（零依赖用词法，可选 embedding）
        sem_score = self._semantic_score(pred.message, gt.message)

        # 3) 组合：位置为主，语义补充。位置对上时即使措辞不同也能命中；
        #    位置对不上但语义强相关（embedding 模式）也能命中。
        score = self.location_weight * loc_score + (1.0 - self.location_weight) * sem_score
        return score

    def _location_score(self, pred_loc: str, gt_loc: str) -> float:
        """位置重叠得分：优先区间 IoU，退化到字符串包含，最后是文件名匹配。"""
        p = parse_location(pred_loc)
        g = parse_location(gt_loc)
        if p is not None and g is not None:
            return p.overlaps(g, tolerance=self.location_tolerance)
        # 解析失败：退化到字符串比较
        if pred_loc and gt_loc:
            pn, gn = _norm(pred_loc), _norm(gt_loc)
            if pn == gn:
                return 1.0
            if pn in gn or gn in pn:
                return 0.7
        return 0.0

    def _semantic_score(self, pred_text: str, gt_text: str) -> float:
        """语义相似度：优先语义匹配器，零依赖模式退回词法重叠。"""
        if not pred_text or not gt_text:
            return 0.0
        # 若注入了真正的 embedding 匹配器（非 Noop），用它
        if not isinstance(self.semantic_matcher, NoopSemanticMatcher):
            return self.semantic_matcher.similarity(pred_text, gt_text)
        # 零依赖兜底：词法重叠（Jaccard）
        pt = _tokenize(pred_text)
        gt_ = _tokenize(gt_text)
        if not pt or not gt_:
            return 0.0
        inter = len(pt & gt_)
        union = len(pt | gt_)
        return inter / union if union else 0.0

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
