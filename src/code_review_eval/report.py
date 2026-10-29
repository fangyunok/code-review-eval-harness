"""归因分析 + 报告输出。

把 Model 层的聚合分数，进一步拆到「哪个模型 / 哪类缺陷 / 哪个产品线」漏报最多，
输出 Markdown 报告 + JSON 结果，作为「AI 能力量化与质量否决项的反馈信号」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ModelRunResult:
    """某个模型（或配置）跑完整个评测集的完整结果。"""

    name: str
    harness: Dict[str, Any] = field(default_factory=dict)  # Harness 层指标
    model: Dict[str, Any] = field(default_factory=dict)  # Model 层聚合分数
    per_sample: List[Any] = field(default_factory=list)


class Report:
    """汇总多个模型/配置的结果，产出归因结论与报告。"""

    def __init__(self, runs: List[ModelRunResult]):
        self.runs = runs

    def attribute(self) -> Dict[str, Any]:
        """归因：跨模型按缺陷类型聚合漏报，找出共性薄弱点。"""
        by_type: Dict[str, Dict[str, int]] = {}
        for run in self.runs:
            missed = run.model.get("missed_by_type", {})
            for t, c in missed.items():
                by_type.setdefault(t, {})[run.name] = c
        return by_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runs": [
                {
                    "name": r.name,
                    "harness": r.harness,
                    "model": {
                        k: v
                        for k, v in r.model.items()
                        if k not in ("missed_critical",)
                    },
                }
                for r in self.runs
            ],
            "attribution": self.attribute(),
        }

    def to_markdown(self) -> str:
        lines: List[str] = ["# 代码评审 Agent 评测报告", ""]

        lines.append("## 一、Model 层分数（Precision / Recall / F1）")
        lines.append("")
        lines.append("| 模型 | Precision | Recall | F1 | 漏报 critical | 误报数 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in self.runs:
            m = r.model
            lines.append(
                f"| {r.name} | {m['precision']} | {m['recall']} | {m['f1']} "
                f"| {m['missed_critical_count']} | {m['false_positive_count']} |"
            )
        lines.append("")

        lines.append("## 二、Harness 层指标（工程脚手架稳定性）")
        lines.append("")
        lines.append("| 模型 | 解析成功率 | 格式合规率 |")
        lines.append("| --- | --- | --- |")
        for r in self.runs:
            h = r.harness
            lines.append(
                f"| {r.name} | {h.get('parse_rate', 0):.2%} "
                f"| {h.get('format_ok_rate', 0):.2%} |"
            )
        lines.append("")

        lines.append("## 三、归因分析（按缺陷类型聚合漏报）")
        lines.append("")
        attr = self.attribute()
        if attr:
            types = sorted(attr.keys())
            header = "| 缺陷类型 | " + " | ".join(r.name for r in self.runs) + " |"
            lines.append(header)
            lines.append("| --- | " + " | ".join("---" for _ in self.runs) + " |")
            for t in types:
                row = [str(attr[t].get(r.name, 0)) for r in self.runs]
                lines.append(f"| {t} | " + " | ".join(row) + " |")
        else:
            lines.append("（无漏报）")
        lines.append("")

        lines.append("## 四、漏报的 critical 缺陷清单")
        lines.append("")
        shown = False
        for r in self.runs:
            for d in r.model.get("missed_critical", []):
                shown = True
                lines.append(
                    f"- `{r.name}` 漏报 `{d.id}`：{d.message}（{d.location}）"
                )
        if not shown:
            lines.append("（无 critical 漏报）")
        lines.append("")

        return "\n".join(lines)

    def write(self, json_path: str, md_path: str) -> None:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())
