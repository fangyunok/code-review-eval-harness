.PHONY: install test lint typecheck format check ci demo dashboard clean

# 安装开发依赖
install:
	pip install -e ".[dev]"

# 跑测试
test:
	pytest -q

# 代码风格检查
lint:
	ruff check src tests

# 自动格式化
format:
	ruff check --fix src tests
	ruff format src tests

# 类型检查
typecheck:
	mypy src

# 一键质量门禁（测试 + lint + 类型检查）
check: test lint typecheck

# CI 全流程
ci: check
	python -m code_review_eval.datasets.pipeline --output data/benchmark.jsonl --synthetic 200
	python demo.py

# 离线演示
demo:
	python demo.py

# 生成归因看板
dashboard:
	python -m code_review_eval.cli eval --benchmark data/benchmark.jsonl --synthetic 50 --thresholds '{"f1": 0.5}' --dashboard dashboard.html

# 清理产物
clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache runs reports
	find . -type d -name __pycache__ -exec rm -rf {} +
