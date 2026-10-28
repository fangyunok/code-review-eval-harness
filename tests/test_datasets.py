"""数据管线单元测试：合成生成、质量校验、去重。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.datasets.synthetic import generate_samples
from code_review_eval.datasets.validation import validate_samples


def test_generate_is_deterministic():
    a = generate_samples(30, seed=7)
    b = generate_samples(30, seed=7)
    assert a == b


def test_generate_count_and_unique_ids():
    samples = generate_samples(50, seed=1)
    assert len(samples) == 50
    ids = [s["id"] for s in samples]
    assert len(ids) == len(set(ids))


def test_generate_produces_diverse_diffs():
    samples = generate_samples(50, seed=2)
    diffs = [s["diff"] for s in samples]
    assert len(set(diffs)) == len(diffs)  # 每条 diff 都应不同


def test_validate_passes_clean_samples():
    samples = generate_samples(20, seed=3)
    clean, report = validate_samples(samples)
    assert report.passed == 20
    assert report.dropped_invalid == 0
    assert report.dropped_duplicate == 0


def test_validate_drops_invalid():
    bad = [
        {"id": "x", "diff": "", "defects": []},  # 空 diff
        {"id": "y", "diff": "d", "defects": [{"type": "logic", "severity": "critical", "message": "", "location": "a.py:1"}]},  # 空 message
    ]
    _, report = validate_samples(bad)
    assert report.passed == 0
    assert report.dropped_invalid == 2


def test_validate_drops_duplicate():
    dup = [
        {"id": "a", "repo": "r", "diff": "same", "defects": [{"id": "a-1", "type": "logic", "severity": "major", "message": "m", "location": "f.py:1"}]},
        {"id": "b", "repo": "r", "diff": "same", "defects": [{"id": "b-1", "type": "logic", "severity": "major", "message": "m", "location": "f.py:1"}]},
    ]
    clean, report = validate_samples(dup)
    assert len(clean) == 1
    assert report.dropped_duplicate == 1
