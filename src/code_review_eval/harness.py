"""Harness 层：统一 LLM 调用脚手架，隔离工程噪声。

这一层评测的是「脚手架本身靠不靠谱」，而非模型能力。它负责：
1. 用 `BaseBackend` 抽象统一不同后端（fake / 各类真实模型）的调用接口；
2. 用结构化 prompt 强制模型输出 JSON 评审意见；
3. 校验输出是否可解析、格式是否合规，记录解析成功率。

设计意图：如果 Harness 层不稳定（比如 prompt 有 bug、JSON 解析失败率高），
那 Model 层的分数就不可信。所以先保证 Harness 层本身可被评测。
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from .schema import DEFECT_TYPES, SEVERITIES, ReviewIssue, Sample

# 结构化评审 prompt：要求模型按固定 JSON 输出，便于解析和对齐
SYSTEM_PROMPT = (
    "你是一名资深代码评审专家。请评审下面这段代码变更（diff），"
    "找出其中的缺陷。只输出 JSON，不要输出任何其他文字。"
    "JSON 格式必须严格如下："
    '{"issues": [{"type": "logic|security|performance|style", '
    '"severity": "critical|major|minor", '
    '"message": "缺陷描述", "location": "文件:行号或符号名"}]}。'
    "如果没有发现缺陷，输出 {\"issues\": []}。"
)


class BaseBackend(ABC):
    """LLM 后端抽象：Harness 不关心具体模型，只关心「输入 prompt 输出文本」."""

    @abstractmethod
    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """给定消息列表，返回模型生成的文本。"""


class FakeBackend(BaseBackend):
    """离线可复现的假后端：直接返回预置文本，不依赖任何模型或网络。

    用途：
    - 单元测试与 CI 里跑通全链路，不烧 API 额度；
    - 验证 Harness 层的解析/校验逻辑本身是否正确。
    """

    def __init__(self, responses: list[str] | None = None):
        self.responses = list(responses or [])
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        # 默认：声明没有缺陷，保证可解析
        return '{"issues": []}'


class Harness:
    """统一调用脚手架：给定样本 + 后端，产出结构化评审结果。

    评测指标（Harness 层）：
    - parse_rate: 输出能成功解析成 JSON 的比例；
    - format_ok_rate: 解析后字段类型/枚举合法的比例。
    这两项反映的是「工程脚手架」质量，和模型好坏无关。
    """

    def __init__(self, backend: BaseBackend, system_prompt: str = SYSTEM_PROMPT):
        self.backend = backend
        self.system_prompt = system_prompt

    def build_messages(self, sample: Sample) -> list[dict[str, str]]:
        user = f"代码变更（diff）：\n```\n{sample.diff}\n```\n"
        if sample.context:
            user += f"\n上下文：{sample.context}\n"
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user},
        ]

    def review(self, sample: Sample) -> dict[str, Any]:
        """评审单个样本，返回 {issues, parse_ok, format_ok, raw}."""
        raw = self.backend.complete(self.build_messages(sample))
        return self._parse(raw)

    def _parse(self, raw: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "issues": [],
            "parse_ok": False,
            "format_ok": False,
            "raw": raw,
        }
        data = self._extract_json(raw)
        if data is None:
            return result
        result["parse_ok"] = True

        issues_raw = data.get("issues")
        if not isinstance(issues_raw, list):
            return result

        issues: list[ReviewIssue] = []
        format_ok = True
        for it in issues_raw:
            if not isinstance(it, dict):
                format_ok = False
                continue
            issue = ReviewIssue(
                type=it.get("type", ""),
                severity=it.get("severity", ""),
                message=it.get("message", ""),
                location=it.get("location", ""),
                category=it.get("category"),
            )
            if (
                issue.type not in DEFECT_TYPES
                or issue.severity not in SEVERITIES
                or not issue.message
            ):
                format_ok = False
            issues.append(issue)

        result["issues"] = issues
        result["format_ok"] = format_ok
        return result

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any] | None:
        """从模型输出里提取 JSON，容忍 ```json 包裹或前后杂字。"""
        if not raw:
            return None
        text = raw.strip()
        # 去掉 markdown 代码块包裹
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        # 截取第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
