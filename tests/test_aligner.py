"""对齐算法升级专项测试：位置区间 IoU、行号偏移容忍、语义嵌入、类型约束。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.aligner import ModelEvaluator
from code_review_eval.location import LocationSpan, parse_location
from code_review_eval.schema import Defect, ReviewIssue, Sample
from code_review_eval.semantic import (
    EmbeddingSemanticMatcher,
    cosine_similarity,
)


def _sample(defects):
    return Sample(
        id="s", title="t", diff="x",
        defects=[Defect(id=d["id"], type=d["type"], severity=d["severity"],
                        message=d["message"], location=d["location"])
                 for d in defects],
    )


# ---- 位置区间解析 ----

def test_parse_location_forms():
    assert parse_location("a.py:42").start == 42
    span = parse_location("a.py:42-45")
    assert span.start == 42 and span.end == 45
    only_file = parse_location("a.py")
    assert only_file.file == "a.py" and not only_file.has_line
    assert parse_location("no_line_here") is None  # 无文件、无行号 -> None


def test_span_iou_with_tolerance():
    a = LocationSpan("a.py", 42, 42)
    b = LocationSpan("a.py", 45, 45)  # 差 3 行
    assert a.overlaps(b, tolerance=3) > 0  # 容忍后应重叠


def test_span_different_file_no_overlap():
    a = LocationSpan("a.py", 1, 1)
    b = LocationSpan("b.py", 1, 1)
    assert a.overlaps(b) == 0.0


# ---- 对齐：行号偏移容忍 ----

def test_align_tolerates_line_offset():
    sample = _sample([{"id": "d1", "type": "logic", "severity": "major",
                       "message": "divide by zero", "location": "billing.py:18"}])
    # 模型报的位置差 2 行，措辞也略不同，但类型一致 -> 应命中
    pred = [ReviewIssue(type="logic", severity="major",
                        message="possible division by zero when count is 0",
                        location="billing.py:20")]
    res = ModelEvaluator().evaluate_sample(sample, pred)
    assert res.tp == 1 and res.fn == 0


# ---- 对齐：类型强约束 ----

def test_align_type_mismatch_not_matched():
    sample = _sample([{"id": "d1", "type": "security", "severity": "critical",
                       "message": "sql injection", "location": "a.py:1"}])
    # 位置相同但类型完全不同 -> 不应命中（避免乱配）
    pred = [ReviewIssue(type="style", severity="minor",
                        message="naming convention", location="a.py:1")]
    res = ModelEvaluator().evaluate_sample(sample, pred)
    assert res.tp == 0 and res.fn == 1


# ---- 语义嵌入对齐 ----

class _FakeEmbedder:
    """假嵌入：把文本映射成「含关键词的稀疏向量」，能区分语义。"""

    def embed(self, texts):
        vecs = []
        for t in texts:
            v = [0.0] * 4
            if "inject" in t or "注入" in t or "sql" in t.lower():
                v[0] = 1.0
            if "divide" in t or "除零" in t or "zero" in t:
                v[1] = 1.0
            if "naming" in t or "命名" in t or "style" in t.lower():
                v[2] = 1.0
            if "leak" in t or "泄露" in t or "close" in t:
                v[3] = 1.0
            vecs.append(v)
        return vecs


def test_align_with_semantic_embedding():
    # 措辞完全不同、位置也对不上，但语义相同 -> embedding 应能匹配
    sample = _sample([{"id": "d1", "type": "security", "severity": "critical",
                       "message": "sql injection risk", "location": "a.py:1"}])
    pred = [ReviewIssue(type="security", severity="critical",
                        message="this query is vulnerable to injection",
                        location="a.py:50")]  # 位置差很远
    matcher = EmbeddingSemanticMatcher(_FakeEmbedder())
    ev = ModelEvaluator(location_weight=0.3, semantic_matcher=matcher)
    res = ev.evaluate_sample(sample, pred)
    assert res.tp == 1


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    assert abs(cosine_similarity([1, 1], [1, 0]) - 0.7071) < 0.01
