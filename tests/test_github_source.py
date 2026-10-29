"""真实 PR 抽取单元测试：非缺陷评论过滤、类型/严重度归类。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.datasets.github_source import (
    _classify_severity,
    _classify_type,
    _is_non_defect_comment,
)


def test_classify_type():
    assert _classify_type("this has SQL injection risk") == "security"
    assert _classify_type("this loop is O(n^2), too slow") == "performance"
    assert _classify_type("please fix the naming convention") == "style"
    assert _classify_type("this logic is wrong") == "logic"  # 兜底


def test_classify_severity():
    assert _classify_severity("critical security vulnerability") == "critical"
    assert _classify_severity("this is a bug, should be fixed") == "major"
    assert _classify_severity("minor cosmetic issue") == "minor"  # 兜底


def test_is_non_defect_comment_filters_praise():
    assert _is_non_defect_comment("+1") is True
    assert _is_non_defect_comment("LGTM!") is True
    assert _is_non_defect_comment("Thanks!") is True
    assert _is_non_defect_comment("Ah, brilliant! +1") is True


def test_is_non_defect_comment_keeps_real_defects():
    assert _is_non_defect_comment("This line will still cause pypi upload failure on Python3") is False
    assert _is_non_defect_comment("You should use os.path.join here to avoid path separator issues") is False


def test_is_non_defect_comment_filters_short():
    assert _is_non_defect_comment("👍") is True
    assert _is_non_defect_comment("nice") is True
