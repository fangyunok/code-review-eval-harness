"""异步并发评测执行器：asyncio + 重试 + 超时 + 失败隔离。

工业级评测要同时打大量样本，串行跑不可接受。本模块提供：
1. 异步后端（AsyncBackend）：await 一次模型调用；
2. 并发执行器：限制并发度批量评测，避免打爆上游限流；
3. 重试：瞬时失败（超时/网络）自动重试，指数退避；
4. 失败隔离：单条样本失败不拖垮整批，记录失败原因继续。

与同步 Harness 的关系：异步执行器复用 Harness 的 prompt 构造与解析逻辑，
只把「调用后端」这一步换成异步。
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .harness import Harness
from .schema import ReviewIssue, Sample


class AsyncBackend(ABC):
    """异步后端抽象：await 一次模型调用。"""

    @abstractmethod
    async def acomplete(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """异步返回模型生成的文本。"""


class FakeAsyncBackend(AsyncBackend):
    """离线可复现的异步假后端：从预置响应队列里取值，可模拟延迟与失败。"""

    def __init__(
        self,
        responses: Optional[List[str]] = None,
        delay: float = 0.0,
        fail_times: int = 0,
    ):
        self.responses = list(responses or [])
        self.delay = delay
        self.fail_times = fail_times  # 前 N 次调用抛异常，用于测试重试逻辑

    async def acomplete(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise TimeoutError("simulated transient failure")
        if self.responses:
            return self.responses.pop(0)
        return '{"issues": []}'


@dataclass
class AsyncReviewOutcome:
    """单条样本的异步评审结果。"""

    sample_id: str
    issues: List[ReviewIssue]
    parse_ok: bool
    format_ok: bool
    raw: str
    failed: bool = False
    error: Optional[str] = None
    attempts: int = 1


class AsyncEvaluator:
    """异步并发评测：并发 + 重试 + 超时 + 失败隔离。"""

    def __init__(
        self,
        harness: Harness,
        backend: AsyncBackend,
        max_concurrency: int = 8,
        max_retries: int = 3,
        timeout: float = 60.0,
        backoff_base: float = 1.0,
    ):
        self.harness = harness
        self.backend = backend
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base

    async def _review_with_retry(self, sample: Sample) -> AsyncReviewOutcome:
        messages = self.harness.build_messages(sample)
        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self.backend.acomplete(messages), timeout=self.timeout
                )
                parsed = self.harness._parse(raw)
                return AsyncReviewOutcome(
                    sample_id=sample.id,
                    issues=parsed["issues"],
                    parse_ok=parsed["parse_ok"],
                    format_ok=parsed["format_ok"],
                    raw=raw,
                    attempts=attempt,
                )
            except (TimeoutError, asyncio.TimeoutError, ConnectionError) as e:
                last_error = str(e)
                # 指数退避 + 抖动，避免同时重试打爆上游
                backoff = self.backoff_base * (2 ** (attempt - 1))
                await asyncio.sleep(backoff + random.uniform(0, 0.5))
            except Exception as e:  # 其他非瞬态错误，不重试直接隔离
                return AsyncReviewOutcome(
                    sample_id=sample.id,
                    issues=[],
                    parse_ok=False,
                    format_ok=False,
                    raw="",
                    failed=True,
                    error=str(e),
                    attempts=attempt,
                )
        # 重试耗尽仍失败
        return AsyncReviewOutcome(
            sample_id=sample.id,
            issues=[],
            parse_ok=False,
            format_ok=False,
            raw="",
            failed=True,
            error=last_error or "max retries exceeded",
            attempts=self.max_retries,
        )

    async def _worker(self, queue: asyncio.Queue, results: Dict[str, AsyncReviewOutcome]):
        while True:
            sample = await queue.get()
            try:
                results[sample.id] = await self._review_with_retry(sample)
            finally:
                queue.task_done()

    async def evaluate_all(self, samples: List[Sample]) -> Dict[str, AsyncReviewOutcome]:
        """并发评测所有样本，返回 sample_id -> 结果映射。"""
        queue: asyncio.Queue = asyncio.Queue()
        results: Dict[str, AsyncReviewOutcome] = {}
        for s in samples:
            queue.put_nowait(s)

        workers = [
            asyncio.create_task(self._worker(queue, results))
            for _ in range(self.max_concurrency)
        ]
        await queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        return results
