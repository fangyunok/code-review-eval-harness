"""真实模型后端（OpenAIAsyncBackend）的单元测试。

不依赖真实网络和 openai 库：用 monkeypatch 注入一个假的
AsyncOpenAI 客户端，验证后端的调用/限流/错误处理逻辑本身正确。
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.backends import OpenAIAsyncBackend


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content='{"issues": []}'):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


def test_acomplete_returns_text(monkeypatch):
    backend = OpenAIAsyncBackend(api_key="sk-test", model="gpt-test")
    fake = _FakeClient('{"issues": [{"type": "security", "severity": "critical", "message": "x", "location": "a.py:1"}]}')
    backend._client = fake
    out = asyncio.run(backend.acomplete([{"role": "user", "content": "hi"}]))
    assert "security" in out
    # 验证 model 名和 messages 被正确传递
    assert fake.chat.completions.calls[0]["model"] == "gpt-test"
    assert fake.chat.completions.calls[0]["messages"][0]["content"] == "hi"


def test_throttle_enforces_min_interval():
    backend = OpenAIAsyncBackend(min_interval=0.2)

    async def run():
        t0 = __import__("time").monotonic()
        await backend._throttle()
        await backend._throttle()
        return __import__("time").monotonic() - t0

    elapsed = asyncio.run(run())
    assert elapsed >= 0.2


def test_missing_openai_raises_friendly_error(monkeypatch):
    # 模拟 openai 未安装
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("No module named openai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    backend = OpenAIAsyncBackend(api_key="sk-test")
    backend._client = None
    with pytest.raises(RuntimeError, match="pip install"):
        backend._get_client()


def test_sync_backend_returns_text(monkeypatch):
    from code_review_eval.backends import OpenAICompatibleBackend

    backend = OpenAICompatibleBackend(api_key="sk-test", model="gpt-test")

    class _SyncFakeCompletions:
        def create(self, **kwargs):
            return _FakeResp('{"issues": []}')

    fake = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": _SyncFakeCompletions().create})()})()})()
    backend._client = fake
    out = backend.complete([{"role": "user", "content": "hi"}])
    assert out == '{"issues": []}'
