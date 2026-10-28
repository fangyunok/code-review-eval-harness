"""核心逻辑单元测试：对齐打分、JSON 解析、聚合、报告生成。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.aligner import ModelEvaluator
from code_review_eval.harness import Harness
from code_review_eval.report import ModelRunResult, Report
from code_review_eval.schema import Defect, ReviewIssue, Sample


def _make_sample(defects):
    return Sample(
        id="s1",
        title="t",
        diff="x",
        defects=[
            Defect(
                id=d["id"],
                type=d["type"],
                severity=d["severity"],
                message=d["message"],
                location=d["location"],
            )
            for d in defects
        ],
    )


def test_perfect_match():
    sample = _make_sample(
        [{"id": "d1", "type": "security", "severity": "critical",
          "message": "sql injection", "location": "a.py:1"}]
    )
    pred = [ReviewIssue(type="security", severity="critical",
                        message="sql injection", location="a.py:1")]
    res = ModelEvaluator().evaluate_sample(sample, pred)
    assert res.tp == 1 and res.fp == 0 and res.fn == 0


def test_miss_critical():
    sample = _make_sample(
        [{"id": "d1", "type": "security", "severity": "critical",
          "message": "sql injection", "location": "a.py:1"}]
    )
    res = ModelEvaluator().evaluate_sample(sample, [])
    assert res.fn == 1 and res.missed_critical[0].id == "d1"


def test_false_positive():
    sample = _make_sample([])
    pred = [ReviewIssue(type="style", severity="minor",
                        message="naming", location="a.py:9")]
    res = ModelEvaluator().evaluate_sample(sample, pred)
    assert res.fp == 1 and res.tp == 0


def test_location_substring_match():
    sample = _make_sample(
        [{"id": "d1", "type": "logic", "severity": "major",
          "message": "divide by zero", "location": "billing.py:18"}]
    )
    # 位置只写函数名，应能通过包含关系匹配
    pred = [ReviewIssue(type="logic", severity="major",
                        message="divide by zero", location="billing.py")]
    res = ModelEvaluator().evaluate_sample(sample, pred)
    assert res.tp == 1


def test_aggregate_metrics():
    sample = _make_sample(
        [{"id": "d1", "type": "security", "severity": "critical",
          "message": "sql injection", "location": "a.py:1"},
         {"id": "d2", "type": "logic", "severity": "major",
          "message": "null check", "location": "a.py:2"}]
    )
    pred = [ReviewIssue(type="security", severity="critical",
                        message="sql injection", location="a.py:1")]
    ev = ModelEvaluator()
    r1 = ev.evaluate_sample(sample, pred)
    agg = ev.aggregate([r1])
    assert agg["tp"] == 1 and agg["fn"] == 1 and agg["fp"] == 0
    assert agg["precision"] == 1.0 and agg["recall"] == 0.5


def test_harness_extract_json_with_fence():
    h = Harness(None)
    raw = '```json\n{"issues": []}\n```'
    assert h._extract_json(raw) == {"issues": []}


def test_harness_format_ok():
    h = Harness(None)
    out = h._parse('{"issues": [{"type": "security", "severity": "critical", '
                   '"message": "x", "location": "a.py:1"}]}')
    assert out["parse_ok"] and out["format_ok"] and len(out["issues"]) == 1


def test_report_markdown_contains_metrics():
    run = ModelRunResult(
        name="m",
        harness={"parse_rate": 1.0, "format_ok_rate": 1.0, "total": 1},
        model={"precision": 1.0, "recall": 1.0, "f1": 1.0,
               "missed_critical_count": 0, "false_positive_count": 0,
               "missed_by_type": {}, "missed_critical": []},
    )
    md = Report([run]).to_markdown()
    assert "Precision" in md and "归因分析" in md
