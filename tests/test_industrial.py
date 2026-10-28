"""工业级能力单元测试：异步并发、重试、门禁、run store 趋势。"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_review_eval.async_eval import AsyncEvaluator, FakeAsyncBackend
from code_review_eval.evaluate import evaluate_async, load_samples
from code_review_eval.gate import QualityGate, detect_regression
from code_review_eval.harness import Harness
from code_review_eval.runstore import RunStore
from code_review_eval.schema import Sample


def _samples(n=5):
    from code_review_eval.schema import Defect

    out = []
    for i in range(n):
        out.append(
            Sample(
                id=f"s{i}",
                title="t",
                diff=f"def f{i}(): return {i}",
                defects=[
                    Defect(id=f"s{i}-1", type="security", severity="critical",
                           message="sql injection", location=f"a{i}.py:1")
                ],
            )
        )
    return out


def test_async_evaluator_concurrent():
    backend = FakeAsyncBackend(
        responses=['{"issues": []}'] * 5, delay=0.01
    )
    harness = Harness(None)
    runner = AsyncEvaluator(harness, backend, max_concurrency=4)
    outcomes = asyncio.run(runner.evaluate_all(_samples(5)))
    assert len(outcomes) == 5
    assert all(not o.failed for o in outcomes.values())


def test_async_retry_recovers():
    # 前 2 次调用失败，第 3 次成功 -> 重试后恢复
    backend = FakeAsyncBackend(
        responses=['{"issues": []}'], delay=0.0, fail_times=2
    )
    harness = Harness(None)
    runner = AsyncEvaluator(harness, backend, max_concurrency=1, max_retries=3)
    outcomes = asyncio.run(runner.evaluate_all(_samples(1)))
    o = list(outcomes.values())[0]
    assert not o.failed
    assert o.attempts == 3


def test_async_isolates_failure():
    # 持续失败，重试耗尽 -> 标记 failed，不抛异常
    backend = FakeAsyncBackend(responses=[], delay=0.0, fail_times=10)
    harness = Harness(None)
    runner = AsyncEvaluator(harness, backend, max_concurrency=1, max_retries=2)
    outcomes = asyncio.run(runner.evaluate_all(_samples(1)))
    o = list(outcomes.values())[0]
    assert o.failed


def test_quality_gate_pass_and_fail():
    gate = QualityGate({"f1": 0.7})
    r_pass = gate.check({"m": {"f1": 0.8}})
    assert r_pass.passed and r_pass.exit_code == 0
    r_fail = gate.check({"m": {"f1": 0.5}})
    assert not r_fail.passed and r_fail.exit_code == 1


def test_detect_regression():
    assert detect_regression({"f1": 0.6}, {"f1": 0.7}, "f1")["regressed"] is True
    assert detect_regression({"f1": 0.69}, {"f1": 0.7}, "f1")["regressed"] is False
    assert detect_regression({"f1": 0.6}, None, "f1")["regressed"] is False


def test_run_store_roundtrip_and_trend():
    with tempfile.TemporaryDirectory() as d:
        store = RunStore(base_dir=d)
        samples = _samples(2)
        backend = FakeAsyncBackend(responses=['{"issues": []}'] * 2)
        r1 = evaluate_async(samples, {"m": backend}, run_store=store)
        r2 = evaluate_async(samples, {"m": backend}, run_store=store)
        assert r1["run_id"] and r2["run_id"]
        runs = store.list_runs()
        assert len(runs) == 2
        trend = store.trend(metric="f1")
        assert len(trend) == 2
