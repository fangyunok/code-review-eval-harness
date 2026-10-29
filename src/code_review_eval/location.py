"""位置区间解析与匹配：把 location 字符串升级为「文件 + 行号区间」。

工业级对齐的核心是位置匹配要能容忍「行号偏移」——模型报的位置
很少和标注逐字符相同，可能差几行。把 location 解析成区间后，
用 IoU（交并比）判定是否指向同一段代码，比字符串相等鲁棒得多。

支持的 location 格式（都能解析）：
- "payment.py:42"             单行
- "payment.py:42-45"          区间
- "payment.py:42,44"          多行离散
- "payment.py"                只有文件（无行号）
- 纯函数名（无文件）          降级为符号匹配
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 匹配 "file.py:42" 或 "file.py:42-45" 或 "file.py:42,44"
_LOCATION_RE = re.compile(r"^(.+?):(\d+)(?:[-~](\d+))?(?:,(\d+))*$")


@dataclass
class LocationSpan:
    """一个位置区间：文件 + [start, end] 行号。"""

    file: str
    start: int | None = None
    end: int | None = None

    @property
    def has_line(self) -> bool:
        return self.start is not None

    def overlaps(self, other: LocationSpan, tolerance: int = 3) -> float:
        """返回两个位置的重叠程度（0~1）。

        规则：
        - 文件不同 -> 0（不匹配）；
        - 都没行号 -> 文件相同算 1，否则 0；
        - 都有行号 -> 用「行号距离衰减」打分：重叠/相距 tolerance 内得高分，
          越远越低，超过 2*tolerance 归 0。比纯 IoU 对小偏移更敏感。
        """
        if not self.file or not other.file:
            return 0.0
        if _norm_file(self.file) != _norm_file(other.file):
            return 0.0
        # 文件相同，至少一方无行号 -> 只按文件匹配
        if not self.has_line or not other.has_line:
            return 1.0 if self.has_line == other.has_line else 0.6
        # 两边都有行号：算区间距离，按距离衰减打分
        assert self.start is not None and self.end is not None
        assert other.start is not None and other.end is not None
        gap = _interval_gap(self.start, self.end, other.start, other.end)
        if gap <= 0:
            return 1.0  # 区间重叠
        if gap <= tolerance:
            return 0.8  # 相距在容忍范围内
        if gap <= 2 * tolerance:
            return 0.4  # 稍远，部分置信
        return 0.0  # 太远，不匹配


def _interval_gap(a_s: int, a_e: int, b_s: int, b_e: int) -> int:
    """两个区间 [a_s,a_e] 与 [b_s,b_e] 的最小间隔（重叠为 0 或负）。"""
    if a_e < b_s:
        return b_s - a_e
    if b_e < a_s:
        return a_s - b_e
    return 0  # 重叠


def _norm_file(f: str) -> str:
    """归一化文件名：去空白、统一斜杠、小写。"""
    return f.strip().replace("\\", "/").lower()


def parse_location(location: str) -> LocationSpan | None:
    """把 location 字符串解析成 LocationSpan；解析失败返回 None。"""
    if not location or not location.strip():
        return None
    s = location.strip()
    m = _LOCATION_RE.match(s)
    if m:
        fname = m.group(1)
        start = int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        # 逗号分隔的离散行号：取最小和最大构成区间
        if m.group(4):
            end = max(end, int(m.group(4)))
        return LocationSpan(file=fname, start=start, end=end)
    # 纯文件名（无行号）
    if ":" not in s and "." in s:
        return LocationSpan(file=s)
    return None
