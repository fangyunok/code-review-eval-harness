"""数据管线单元测试：合成生成、质量校验、去重、版本快照。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.datasets.pipeline import build_dataset
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


def test_build_dataset_writes_manifest(tmp_path):
    out = str(tmp_path / "benchmark.jsonl")
    result = build_dataset(output=out, synthetic_count=10, seed=5)
    assert result["passed"] == 10
    # manifest 文件生成
    manifest_path = Path(out).with_suffix(".manifest.json")
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sample_count"] == 10
    assert manifest["seed"] == 5
    assert manifest["sources"] == ["synthetic"]
    assert len(manifest["content_sha256"]) == 64


def test_build_dataset_no_manifest(tmp_path):
    out = str(tmp_path / "benchmark.jsonl")
    build_dataset(output=out, synthetic_count=5, write_manifest=False)
    assert not Path(out).with_suffix(".manifest.json").exists()


def test_build_dataset_multi_repo_parse():
    # 验证逗号分隔的 repo 被正确拆分（不实际请求网络，靠 monkeypatch）
    import code_review_eval.datasets.github_source as gs

    class _FakeSource:
        def __init__(self, token=None):
            self.token = token

        def to_samples(self, repo, per_page=10):
            return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gs, "GitHubPRSource", _FakeSource)
    try:
        result = build_dataset(
            output="unused.jsonl",
            synthetic_count=3,
            repo="psf/requests,pandas-dev/pandas",
            write_manifest=False,
        )
        # 两个 repo 都尝试抽取（FakeSource 返回空，所以 real_collected=0）
        assert result["real_errors"] == {}
        assert result["real_collected"] == 0
    finally:
        monkeypatch.undo()
