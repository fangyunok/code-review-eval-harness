"""真实 PR 抽取：从 GitHub API 抽取 PR 的 diff + review comment，构造成评测集。

这是「从真实研发链路整理评测任务与用例」的落地——把真实代码评审里
已经发生的缺陷（reviewer 提出来的问题）转成标准评测样本。

抽取逻辑：
1. 拉取目标仓库的 PR 列表（限定状态/数量）；
2. 对每个 PR，拉取 diff（评审对象）和 review comments（人工标注的缺陷来源）；
3. 把 review comment 映射成标准缺陷：comment 的位置 -> location，正文 -> message；
4. 缺陷类型/严重度通过正文关键词启发式归类（见 _classify）。

注意：真实 comment 的类型/严重度是启发式推断的，这是数据管线的已知权衡，
在质量校验环节会显式记录推断置信度。
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

# 缺陷类型关键词 -> 类型映射（启发式）
_TYPE_RULES = [
    ("security", ["inject", "xss", "csrf", "auth", "secret", "credential", "sql"]),
    ("performance", ["o(n", "o(1", "slow", "cache", "memory", "leak", "n+1"]),
    ("style", ["naming", "style", "format", "lint", "convention", "indent"]),
    # logic 作为兜底类型
]

# 严重度关键词 -> 严重度映射
_SEVERITY_RULES = [
    ("critical", ["critical", "severe", "crash", "security", "data loss", "vulnerab"]),
    ("major", ["bug", "wrong", "should", "must", "error", "fix", "broken"]),
    # minor 作为兜底
]


def _classify_type(text: str) -> str:
    low = text.lower()
    for t, kws in _TYPE_RULES:
        if any(k in low for k in kws):
            return t
    return "logic"


def _classify_severity(text: str) -> str:
    low = text.lower()
    for s, kws in _SEVERITY_RULES:
        if any(k in low for k in kws):
            return s
    return "minor"


class GitHubPRSource:
    """从 GitHub API 抽取 PR 评测数据。

    可选 token 用于提高 rate limit；无 token 也能跑（60 req/h 匿名限制）。
    """

    API = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token

    def _request(self, path: str) -> Any:
        url = f"{self.API}{path}"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "code-review-eval-harness"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_prs(self, repo: str, state: str = "closed", per_page: int = 10) -> List[Dict]:
        """拉取仓库的 PR 列表（含 diff_url 和 review_comments_url）。"""
        return self._request(
            f"/repos/{repo}/pulls?state={state}&per_page={per_page}&sort=updated"
        )

    def fetch_diff(self, diff_url: str) -> str:
        """拉取 PR 的 unified diff 文本。"""
        headers = {"Accept": "application/vnd.github.v3.diff", "User-Agent": "code-review-eval-harness"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(diff_url, headers=headers)
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def fetch_review_comments(self, comments_url: str) -> List[Dict]:
        return self._request(comments_url.split(self.API)[1])

    def to_samples(self, repo: str, state: str = "closed", per_page: int = 10) -> List[Dict]:
        """把仓库的 PR 转成评测样本列表。

        只保留「有 review comment 的 PR」——comment 是缺陷标注的来源，
        没有 comment 的 PR 无法作为有监督评测样本。
        """
        samples: List[Dict] = []
        prs = self.fetch_prs(repo, state=state, per_page=per_page)
        for pr in prs:
            if not pr.get("diff_url"):
                continue
            diff = self.fetch_diff(pr["diff_url"])
            if not diff.strip():
                continue
            comments_url = pr.get("review_comments_url")
            if not comments_url:
                continue
            try:
                comments = self.fetch_review_comments(comments_url)
            except Exception:
                continue
            if not comments:
                continue

            defects = []
            for c in comments:
                body = c.get("body", "")
                if not body.strip():
                    continue
                path = c.get("path", "")
                line = c.get("line") or c.get("original_line") or ""
                location = f"{path}:{line}" if line else path
                defects.append(
                    {
                        "id": f"{pr['number']}-{c['id']}",
                        "type": _classify_type(body),
                        "severity": _classify_severity(body),
                        "message": body.strip(),
                        "location": location,
                        "category": None,
                    }
                )

            if not defects:
                continue

            samples.append(
                {
                    "id": f"pr-{pr['number']}",
                    "title": pr.get("title", ""),
                    "repo": repo,
                    "context": pr.get("body") or "",
                    "diff": diff,
                    "defects": defects,
                }
            )
        return samples
