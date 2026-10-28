"""质量门禁：阈值否决 + 语义化退出码 + 历史趋势对比防退化。

工业级评测的落点是「结果能被程序化消费，作为质量否决项」：
1. 阈值否决：某指标低于阈值，判定不通过；
2. 退出码语义化：通过=0，未通过=1，便于接 CI；
3. 防退化：对比历史 run 的同一指标，识别是否比上次更差。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 退出码语义
EXIT_PASS = 0
EXIT_FAIL = 1


@dataclass
class GateResult:
    passed: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)
    exit_code: int = EXIT_PASS

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "checks": self.checks, "exit_code": self.exit_code}


class QualityGate:
    """对评测结果做阈值否决。

    规则：对每个后端，检查指定指标是否达到阈值；
    任一后端不达标即整体不通过。
    """

    def __init__(self, thresholds: Dict[str, float]):
        # thresholds: {metric: min_value}，如 {"f1": 0.7, "recall": 0.6}
        self.thresholds = thresholds

    def check(self, metrics_by_backend: Dict[str, Dict[str, float]]) -> GateResult:
        checks: List[Dict[str, Any]] = []
        all_pass = True
        for backend, metrics in metrics_by_backend.items():
            for metric, threshold in self.thresholds.items():
                value = metrics.get(metric, 0.0)
                ok = value >= threshold
                if not ok:
                    all_pass = False
                checks.append(
                    {
                        "backend": backend,
                        "metric": metric,
                        "value": value,
                        "threshold": threshold,
                        "ok": ok,
                    }
                )
        return GateResult(passed=all_pass, checks=checks, exit_code=EXIT_PASS if all_pass else EXIT_FAIL)


def detect_regression(
    current: Dict[str, float],
    previous: Optional[Dict[str, float]],
    metric: str,
    tolerance: float = 0.02,
) -> Dict[str, Any]:
    """对比历史，识别指标退化。

    tolerance 是允许的波动幅度：当前值比历史低超过 tolerance 才判定为退化，
    避免噪声导致误报。
    """
    if previous is None:
        return {"regressed": False, "metric": metric, "current": current.get(metric), "previous": None}
    prev_value = previous.get(metric)
    curr_value = current.get(metric)
    if prev_value is None or curr_value is None:
        return {"regressed": False, "metric": metric, "current": curr_value, "previous": prev_value}
    regressed = curr_value < prev_value - tolerance
    return {
        "regressed": regressed,
        "metric": metric,
        "current": curr_value,
        "previous": prev_value,
        "delta": round(curr_value - prev_value, 4),
    }
