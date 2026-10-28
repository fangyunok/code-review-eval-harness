"""可复现 run 管理：run_id、配置快照、结构化产物、历史趋势。

工业级评测的核心要求是「结果可重现、可追溯」。本模块保证：
1. 每次评测生成唯一 run_id（时间戳 + 短哈希），产物落到独立目录；
2. 配置快照（后端、评测集、参数、依赖版本）随结果一起落盘，事后能还原「当时怎么跑的」；
3. 结果以固定 JSON schema 存储，供程序化消费；
4. 提供历史 run 的趋势对比，识别指标退化。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    """生成唯一 run_id：UTC 时间戳（含微秒）+ 随机成分哈希前 8 位。

    用微秒 + 随机盐保证同一秒内多次 run 也不会冲突。
    """
    import secrets

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    salt = secrets.token_hex(8)
    digest = hashlib.sha256((ts + salt).encode()).hexdigest()[:8]
    return f"{ts[:15]}-{digest}"


@dataclass
class RunConfig:
    """一次评测的完整配置快照。"""

    benchmark: str  # 评测集文件路径或标识
    backends: Dict[str, Any]  # 后端名 -> 后端配置（不含密钥）
    seed: int = 42
    python_version: str = field(default_factory=lambda: sys.version.split()[0])
    package_version: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "backends": self.backends,
            "seed": self.seed,
            "python_version": self.python_version,
            "package_version": self.package_version,
            "extra": self.extra,
        }


@dataclass
class RunArtifact:
    """一次评测落盘的结构化产物。"""

    run_id: str
    created_at: str
    config: Dict[str, Any]
    result: Dict[str, Any]  # Report.to_dict() 的内容
    metrics: Dict[str, Any]  # 提取的关键指标，供趋势对比

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "config": self.config,
            "result": self.result,
            "metrics": self.metrics,
        }


class RunStore:
    """run 产物存储：写入、读取、历史趋势对比。

    目录结构（相对 base_dir）：
        runs/<run_id>/run.json      完整产物
        runs/<run_id>/report.md     人类可读报告
    """

    def __init__(self, base_dir: str = "runs"):
        self.base_dir = Path(base_dir)

    def save(self, artifact: RunArtifact, report_md: str = "") -> Path:
        run_dir = self.base_dir / artifact.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "run.json", "w", encoding="utf-8") as f:
            json.dump(artifact.to_dict(), f, ensure_ascii=False, indent=2)
        if report_md:
            with open(run_dir / "report.md", "w", encoding="utf-8") as f:
                f.write(report_md)
        return run_dir

    def list_runs(self) -> List[str]:
        if not self.base_dir.exists():
            return []
        return sorted(p.name for p in self.base_dir.iterdir() if p.is_dir())

    def load(self, run_id: str) -> RunArtifact:
        path = self.base_dir / run_id / "run.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return RunArtifact(
            run_id=data["run_id"],
            created_at=data["created_at"],
            config=data["config"],
            result=data["result"],
            metrics=data["metrics"],
        )

    def trend(self, metric: str = "f1", backend: Optional[str] = None) -> List[Dict]:
        """提取历史 run 中某个指标的趋势，按时间排序。

        用于「防止指标退化」：对比最近一次与历史，识别是否变差。
        """
        rows = []
        for run_id in self.list_runs():
            art = self.load(run_id)
            if backend:
                value = (
                    art.metrics.get(backend, {}).get(metric)
                    if isinstance(art.metrics.get(backend), dict)
                    else None
                )
            else:
                # 取第一个后端的指标作为整体代表
                value = None
                for name, m in art.metrics.items():
                    if isinstance(m, dict):
                        value = m.get(metric)
                        break
            if value is not None:
                rows.append(
                    {"run_id": run_id, "created_at": art.created_at, "metric": metric, "value": value}
                )
        rows.sort(key=lambda r: r["created_at"])
        return rows
