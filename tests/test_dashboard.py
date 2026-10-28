"""看板模块单元测试：数据提取 + HTML 渲染。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.dashboard import (
    extract_from_report,
    render_dashboard,
    write_dashboard,
)
from code_review_eval.report import ModelRunResult, Report


def _make_report():
    run_a = ModelRunResult(
        name="model-a",
        harness={"parse_rate": 1.0, "format_ok_rate": 1.0, "total": 5},
        model={
            "precision": 1.0, "recall": 0.5, "f1": 0.6667,
            "missed_critical_count": 1, "false_positive_count": 0,
            "missed_by_type": {"performance": 1, "style": 1},
            "missed_critical": [],
        },
    )
    run_b = ModelRunResult(
        name="model-b",
        harness={"parse_rate": 1.0, "format_ok_rate": 1.0, "total": 5},
        model={
            "precision": 0.8571, "recall": 1.0, "f1": 0.9231,
            "missed_critical_count": 0, "false_positive_count": 1,
            "missed_by_type": {},
            "missed_critical": [],
        },
    )
    return Report([run_a, run_b])


def test_extract_metrics_and_attribution():
    data = extract_from_report(_make_report())
    assert data["models"] == ["model-a", "model-b"]
    assert len(data["metrics"]) == 2
    assert data["metrics"][0]["f1"] == 0.6667
    # 归因行：model-a 漏报 performance=1, style=1
    perf_rows = [r for r in data["attribution_rows"] if r["type"] == "performance"]
    assert perf_rows[0]["model"] == "model-a" and perf_rows[0]["count"] == 1


def test_render_dashboard_contains_charts():
    data = extract_from_report(_make_report())
    html = render_dashboard(data, trend=[])
    assert "echarts" in html
    assert "chart-metrics" in html
    assert "chart-attribution" in html
    assert "chart-trend" in html


def test_render_dashboard_embeds_data():
    data = extract_from_report(_make_report())
    html = render_dashboard(data, trend=[])
    # 数据应内嵌在 HTML 里
    assert "model-a" in html
    assert "0.6667" in html


def test_write_dashboard(tmp_path):
    data = extract_from_report(_make_report())
    path = str(tmp_path / "dash.html")
    out = write_dashboard(data, path, trend=[])
    assert out == path
    assert Path(path).exists()
    content = Path(path).read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")


def test_dashboard_embeds_echarts_no_cdn():
    """看板应内嵌 ECharts，不依赖外部 CDN（离线可用）。"""
    data = extract_from_report(_make_report())
    html = render_dashboard(data, trend=[])
    # 内嵌了 Apache 许可证的 echarts.min.js
    assert "Apache Software Foundation" in html
    # 无外部 CDN 引用
    assert "cdn.jsdelivr.net" not in html
    assert "unpkg.com" not in html
