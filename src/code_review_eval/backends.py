"""真实模型后端：OpenAI 兼容的异步后端。

让工业级异步评测链路（AsyncEvaluator）能接真实模型跑评测，
而非只能用 FakeAsyncBackend 演示。

设计要点：
1. 异步调用（AsyncOpenAI），和 AsyncEvaluator 的 asyncio 模型对齐；
2. 单次调用自带超时，避免单条样本卡死整批；
3. 可选限流（最小间隔），避免并发打爆上游 rate limit；
4. 出错时抛出明确异常，交给 AsyncEvaluator 的重试/隔离逻辑处理。

「OpenAI 兼容」意味着任意实现了 /v1/chat/completions 协议的服务都能接：
OpenAI / DeepSeek / 通义千问 / Moonshot / 本地 Ollama / vLLM 等。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .async_eval import AsyncBackend


class OpenAIAsyncBackend(AsyncBackend):
    """OpenAI 兼容的异步后端。

    参数：
    - base_url: 兼容服务的 API 地址，默认 OpenAI 官方；
    - api_key: 鉴权密钥；可省略（本地 Ollama 等无需 key）；
    - model: 模型名，如 gpt-4o-mini / deepseek-chat / qwen-plus；
    - timeout: 单次调用的超时（秒）；
    - min_interval: 两次调用的最小间隔（秒），用于温和限流，默认不限。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
        timeout: float = 120.0,
        min_interval: float = 0.0,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call: float = 0.0
        self._client = None

    def _get_client(self):
        """惰性创建 AsyncOpenAI 客户端，避免 import 时依赖 openai。"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "使用 OpenAIAsyncBackend 需要安装 openai："
                    "pip install 'openai>=1.0'"
                ) from e
            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def _throttle(self) -> None:
        """最小间隔限流，避免并发打爆上游。"""
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        wait = self._last_call + self.min_interval - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()

    async def acomplete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """异步调用一次 chat completion，返回模型文本。"""
        client = self._get_client()
        await self._throttle()
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=self.model, messages=messages, **kwargs
            ),
            timeout=self.timeout,
        )
        content = resp.choices[0].message.content
        return content or ""


class OpenAICompatibleBackend:
    """同步 OpenAI 兼容后端，供同步 Harness 使用。

    唯一维护入口，异步评测请优先用 OpenAIAsyncBackend。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "使用 OpenAICompatibleBackend 需要安装 openai："
                    "pip install 'openai>=1.0'"
                ) from e
            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._get_client()
        resp = client.chat.completions.create(
            model=self.model, messages=messages, **kwargs
        )
        return resp.choices[0].message.content or ""


class AnthropicAsyncBackend(AsyncBackend):
    """Anthropic（Claude）异步后端。

    需安装 anthropic：pip install anthropic。用 AsyncAnthropic 客户端。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-3-5-haiku-latest",
        timeout: float = 120.0,
        max_tokens: int = 1024,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "使用 AnthropicAsyncBackend 需要安装 anthropic："
                    "pip install anthropic"
                ) from e
            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    async def acomplete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._get_client()
        # Anthropic 要求 system 与 user 分离
        system = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )
        user_msgs = [m for m in messages if m.get("role") != "system"]
        resp = await asyncio.wait_for(
            client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system or None,
                messages=user_msgs,
                **kwargs,
            ),
            timeout=self.timeout,
        )
        # 拼接所有文本块
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts)


class OllamaAsyncBackend(AsyncBackend):
    """本地 Ollama 异步后端（零 SDK 依赖，直接走 HTTP）。

    Ollama 默认监听 http://localhost:11434，模型需先 `ollama pull` 好。
    用标准库 urllib + asyncio.to_thread 实现，避免引入 aiohttp 依赖。
    """

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def acomplete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        def _sync_call() -> str:
            from urllib import request

            payload = json.dumps(
                {"model": self.model, "messages": messages, "stream": False}
            ).encode("utf-8")
            req = request.Request(
                f"{self.base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "")

        return await asyncio.wait_for(asyncio.to_thread(_sync_call), timeout=self.timeout)
