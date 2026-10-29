"""归因可视化看板：生成自包含的交互式 HTML。

看板四个板块：
1. 跨模型指标对比（分组柱状图：Precision / Recall / F1）
2. 缺陷类型归因（堆叠柱状图：每个模型各类缺陷的漏报数）
3. critical 漏报明细（表格 + 按模型着色）
4. 历史趋势（折线图：多次 run 的 F1 走向）

数据内嵌在 HTML 里，用 ECharts（CDN）渲染，单文件可直接浏览器打开。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .report import Report


def extract_from_report(report: Report) -> Dict[str, Any]:
    """从单个 Report 提取看板数据（不含历史趋势）。

    返回：{models, metrics, attribution_rows, missed_critical}
    """
    data = report.to_dict()
    runs = data["runs"]
    attribution = data.get("attribution", {})

    models = [r["name"] for r in runs]

    # 1) 跨模型指标
    metrics = []
    for r in runs:
        m = r["model"]
        metrics.append(
            {
                "name": r["name"],
                "precision": m.get("precision", 0),
                "recall": m.get("recall", 0),
                "f1": m.get("f1", 0),
                "missed_critical": m.get("missed_critical_count", 0),
                "false_positive": m.get("false_positive_count", 0),
            }
        )

    # 2) 缺陷类型归因：转成 [类型, 模型, 漏报数] 三元组
    attribution_rows = []
    for dtype in sorted(attribution.keys()):
        for model in models:
            count = attribution[dtype].get(model, 0)
            attribution_rows.append({"type": dtype, "model": model, "count": count})

    # 3) critical 漏报明细（Report.to_dict 过滤了 missed_critical，需从 runs 取）
    missed_critical = []
    for r in report.runs:
        for d in r.model.get("missed_critical", []):
            missed_critical.append(
                {
                    "model": r.name,
                    "defect_id": d.id if hasattr(d, "id") else d.get("id", ""),
                    "message": d.message if hasattr(d, "message") else d.get("message", ""),
                    "location": d.location if hasattr(d, "location") else d.get("location", ""),
                    "type": d.type if hasattr(d, "type") else d.get("type", ""),
                }
            )

    return {
        "models": models,
        "metrics": metrics,
        "attribution_rows": attribution_rows,
        "missed_critical": missed_critical,
        "summary": _build_summary(metrics, attribution),
    }


def _build_summary(metrics: List[Dict[str, Any]], attribution: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    """构建「结论先行」摘要：谁最优、F1 差距、最薄弱缺陷类型。"""
    if not metrics:
        return {"best": None, "best_f1": 0, "runner_up_f1": 0, "gap": 0,
                "weakest_type": None, "weakest_count": 0, "total_missed_critical": 0}

    best = max(metrics, key=lambda m: m["f1"])
    best_f1 = best["f1"]
    runner_up = max((m["f1"] for m in metrics if m["name"] != best["name"]), default=0.0)
    gap = best_f1 - runner_up

    # 最薄弱缺陷类型：跨模型漏报总数最多的类型
    weakest_type, weakest_count = None, 0
    for dtype, by_model in attribution.items():
        total = sum(by_model.values())
        if total > weakest_count:
            weakest_type, weakest_count = dtype, total

    total_missed_critical = sum(m["missed_critical"] for m in metrics)
    return {
        "best": best["name"],
        "best_f1": round(best_f1, 4),
        "runner_up_f1": round(runner_up, 4),
        "gap": round(gap, 4),
        "weakest_type": weakest_type,
        "weakest_count": weakest_count,
        "total_missed_critical": total_missed_critical,
    }


def extract_trend(run_store: Any, metric: str = "f1") -> List[Dict[str, Any]]:
    """从 RunStore 提取历史趋势（每个后端一条折线）。"""
    if run_store is None:
        return []
    runs = run_store.list_runs()
    series: Dict[str, List[Dict[str, Any]]] = {}
    for run_id in runs:
        art = run_store.load(run_id)
        created_at = art.created_at
        for backend, m in art.metrics.items():
            if not isinstance(m, dict):
                continue
            if metric in m:
                series.setdefault(backend, []).append(
                    {"run_id": run_id, "created_at": created_at, "value": m[metric]}
                )
    for backend in series:
        series[backend].sort(key=lambda x: x["created_at"])
    return [
        {
            "backend": backend,
            "points": [p["value"] for p in points],
            "labels": [p["run_id"][:15] for p in points],
        }
        for backend, points in series.items()
    ]


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>代码评审 Agent 归因看板</title>
<script>__ECHARTS__</script>
<style>
  :root {
    --bg: #f7f7f5;
    --card: #ffffff;
    --border: #e5e4e0;
    --text: #2c2c2a;
    --muted: #888780;
    --red: #d85a30;
    --blue: #378add;
    --teal: #1d9e75;
    --amber: #ba7517;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: var(--bg); color: var(--text); padding: 24px; line-height: 1.6; }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
          padding: 20px; }
  .card h2 { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
  .chart { width: 100%; height: 300px; }
  .full { grid-column: 1 / -1; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
  .badge.security { background: #fcebeb; color: #a32d2d; }
  .badge.logic { background: #e6f1fb; color: #0c447c; }
  .badge.performance { background: #faeeda; color: #854f0b; }
  .badge.style { background: #e1f5ee; color: #0f6e56; }
  .empty { color: var(--muted); font-size: 13px; padding: 20px; text-align: center; }
  .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
  .summary .item { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
  .summary .label { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
  .summary .value { font-size: 22px; font-weight: 600; }
  .summary .value.best { color: var(--teal); }
  .summary .value.worst { color: var(--red); }
</style>
</head>
<body>
<h1>代码评审 Agent 归因看板</h1>
<div class="sub">跨模型对比 · 缺陷类型归因 · critical 漏报 · 历史趋势</div>

<div class="summary" id="summary"></div>

<div class="grid">
  <div class="card">
    <h2>跨模型指标对比</h2>
    <div id="chart-metrics" class="chart"></div>
  </div>
  <div class="card">
    <h2>缺陷类型归因（漏报数）</h2>
    <div id="chart-attribution" class="chart"></div>
  </div>
  <div class="card full">
    <h2>critical 漏报明细</h2>
    <div id="critical-list"></div>
  </div>
  <div class="card full">
    <h2>历史趋势（F1）</h2>
    <div id="chart-trend" class="chart"></div>
  </div>
</div>

<script>
const DATA = __DATA__;

const METRIC_COLORS = { precision: "#378add", recall: "#1d9e75", f1: "#d85a30" };

function renderSummary() {
  const s = DATA.summary;
  const el = document.getElementById("summary");
  if (!s || !s.best) { el.style.display = "none"; return; }
  el.innerHTML = `
    <div class="item"><div class="label">最优模型</div><div class="value best">${s.best}</div></div>
    <div class="item"><div class="label">F1 领先幅度</div><div class="value">+${s.gap}</div></div>
    <div class="item"><div class="label">最薄弱缺陷类型</div><div class="value worst">${s.weakest_type || "—"}<span style="font-size:13px;color:var(--muted)">（漏 ${s.weakest_count}）</span></div></div>
    <div class="item"><div class="label">critical 漏报</div><div class="value ${s.total_missed_critical ? 'worst' : ''}">${s.total_missed_critical}</div></div>
  `;
}

function renderMetrics() {
  const models = DATA.metrics.map(m => m.name);
  const chart = echarts.init(document.getElementById("chart-metrics"));
  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["Precision", "Recall", "F1"], bottom: 0 },
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
    xAxis: { type: "category", data: models },
    yAxis: { type: "value", min: 0, max: 1 },
    series: ["precision", "recall", "f1"].map(k => ({
      name: k === "f1" ? "F1" : k.charAt(0).toUpperCase() + k.slice(1),
      type: "bar",
      data: DATA.metrics.map(m => m[k]),
      itemStyle: { color: METRIC_COLORS[k] },
      barMaxWidth: 36
    }))
  });
}

function renderAttribution() {
  const types = [...new Set(DATA.attribution_rows.map(r => r.type))];
  const models = DATA.models;
  const chart = echarts.init(document.getElementById("chart-attribution"));
  const series = models.map(m => ({
    name: m,
    type: "bar",
    stack: "total",
    data: types.map(t => {
      const row = DATA.attribution_rows.find(r => r.type === t && r.model === m);
      return row ? row.count : 0;
    }),
    barMaxWidth: 40
  }));
  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { data: models, bottom: 0 },
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
    xAxis: { type: "category", data: types },
    yAxis: { type: "value", minInterval: 1 },
    series
  });
}

function renderCritical() {
  const el = document.getElementById("critical-list");
  const items = DATA.missed_critical;
  if (!items.length) {
    el.innerHTML = '<div class="empty">无 critical 漏报</div>';
    return;
  }
  let html = '<table><thead><tr><th>模型</th><th>类型</th><th>缺陷描述</th><th>位置</th></tr></thead><tbody>';
  for (const it of items) {
    html += `<tr>
      <td>${it.model}</td>
      <td><span class="badge ${it.type}">${it.type}</span></td>
      <td>${it.message}</td>
      <td style="color:var(--muted)">${it.location}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderTrend() {
  const trend = DATA.trend;
  const el = document.getElementById("chart-trend");
  if (!trend.length) {
    el.innerHTML = '<div class="empty">暂无历史 run 数据（至少跑两次评测）</div>';
    return;
  }
  const chart = echarts.init(el);
  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: trend.map(t => t.backend), bottom: 0 },
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
    xAxis: { type: "category", data: trend[0].labels },
    yAxis: { type: "value", min: 0, max: 1 },
    series: trend.map(t => ({
      name: t.backend, type: "line", data: t.points, smooth: true,
      connectNulls: true
    }))
  });
}

renderSummary();
renderMetrics();
renderAttribution();
renderCritical();
renderTrend();

window.addEventListener("resize", () => {
  ["chart-metrics", "chart-attribution", "chart-trend"].forEach(id => {
    const el = document.getElementById(id);
    if (el && echarts.getInstanceByDom(el)) echarts.getInstanceByDom(el).resize();
  });
});
</script>
</body>
</html>
"""


_ECHARTS_CACHE: Optional[str] = None


def _load_echarts() -> str:
    """加载内嵌的 ECharts 脚本（带缓存）。

    从包内读取 echarts.min.js，内嵌进 HTML，使看板完全离线可用、
    不依赖任何 CDN。若本地文件缺失则降级为 CDN 引用。
    """
    global _ECHARTS_CACHE
    if _ECHARTS_CACHE is not None:
        return _ECHARTS_CACHE
    from pathlib import Path

    local = Path(__file__).with_name("echarts.min.js")
    if local.exists():
        _ECHARTS_CACHE = local.read_text(encoding="utf-8")
    else:
        # 降级：CDN 引用（多源，任一可用即可）
        _ECHARTS_CACHE = (
            '<script src="https://unpkg.com/echarts@5.5.0/dist/echarts.min.js"></script>'
            '<script>if(typeof echarts==="undefined"){'
            'document.write(\'<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"><\\/script>\')}'
            "</script>"
        )
    return _ECHARTS_CACHE


def render_dashboard(
    data: Dict[str, Any], trend: Optional[List[Dict[str, Any]]] = None
) -> str:
    """渲染看板 HTML。data 来自 extract_from_report，trend 来自 extract_trend。

    ECharts 内嵌进 HTML，单文件完全离线可用。
    """
    payload = dict(data)
    payload["trend"] = trend or []
    html = _HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    return html.replace("__ECHARTS__", _load_echarts())


def write_dashboard(
    data: Dict[str, Any],
    path: str,
    trend: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """把看板写盘，返回路径。"""
    html = render_dashboard(data, trend)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
