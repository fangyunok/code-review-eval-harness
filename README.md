# code-review-eval-harness

代码评审 Agent 双层评测框架：用可复现的评测集 + 双层评测（Harness / Model）+ 异步并发执行 + 质量门禁，量化「AI 代码评审工具（ai-review）」到底评得准不准，并把结果接进 CI 当质量否决项。

## 先看结论

| 能力 | 指标 | 说明 |
| --- | --- | --- |
| 评测集管线 | 真实 PR 抽取 + 合成生成 + 去重/完整性/一致性校验 | 从真实研发链路整理评测用例，规模化可扩展 |
| 工程脚手架稳定性 | 解析成功率 / 格式合规率 | Harness 层，隔离工程噪声 |
| 模型评审能力 | Precision / Recall / F1 | Model 层，字段级缺陷对齐打分 |
| 对齐算法 | 位置区间重叠 + 类型强约束 + 可选语义嵌入 | 容忍行号偏移、区分语义、可插拔 embedding |
| 失败归因 | 按缺陷类型 / 严重度 / 产品线聚合漏报 | 定位「哪类缺陷漏得最多」 |
| 异步并发 | 并发度 / 重试 / 超时 / 失败隔离 | 吞吐从串行到批量 |
| 可复现 | run_id + 配置快照 + 结构化产物 | 每次评测可追溯、可重现 |
| 质量门禁 | 阈值否决 + 语义化退出码 | 评测结果作为质量否决项接入 CI |
| 工程规范 | ruff / mypy / pre-commit / Makefile / CI 矩阵 | 代码质量有门禁，多版本 Python 验证 |

## 为什么是「双层」评测

评测对象是两个不同的东西，不是把同一个东西评两遍：

- **Harness 层**：评「调用脚手架」——统一 LLM 接口、结构化 prompt、JSON 可解析性、格式合规率。这一层保证的是「模型输出能被稳定地拿来做评测」，隔离的是工程噪声。
- **Model 层**：评「模型评审能力」——把模型输出的评审意见和人工标注的标准缺陷做**字段级对齐**，算 Precision / Recall / F1，区分「漏报关键 bug」和「误报」。

先保证 Harness 稳定，Model 层的分数才可信。

## 对齐算法（Model 层的核心）

模型输出的措辞和位置几乎不可能与标注逐字相同，对齐用三层信号取加权最高分：

1. **位置区间重叠**：location 解析成「文件 + 行号区间」，用行号距离衰减打分，容忍 ±几行的偏移（比字符串相等鲁棒得多）；
2. **类型强约束**：缺陷类型不同直接判定不匹配，避免位置巧合导致的乱配；
3. **语义相似**（可选）：用 embedding 算「意见文本」与「缺陷描述」的语义距离，措辞完全不同也能识别同一件事。默认零依赖词法兜底，接 `[embeddings]` 可插拔 embedding 模型。

## 快速开始

```bash
# 依赖仅需 Python 3.10+，核心评测零第三方依赖
pip install -e ".[dev]"   # 跑测试；可选 openai 后端 ".[openai]"、语义对齐 ".[embeddings]"

# 一键质量门禁（测试 + lint + 类型检查）
make check

# 跑单元测试
pytest -q

# 构建评测集（合成 200 条，确定性可复现）
python -m code_review_eval.datasets.pipeline --output data/benchmark.jsonl --synthetic 200

# 工业级评测：构建 + 异步评测 + 质量门禁（退出码 0=通过 1=不通过）
creh eval --benchmark data/benchmark.jsonl --synthetic 50 --thresholds '{"f1": 0.5}'

# 真实数据验证（需 GitHub token，网络正常时运行）
python scripts/verify_real_data.py --repo psf/requests --token-file .gh-token

# 离线演示：模拟两个模型跑完整链路
python demo.py
```

## 评测集管线

支持两种数据来源，混合构建，统一经质量校验：

```bash
# 合成数据：程序化生成，确定性可复现（seed 固定则结果一致）
python -m code_review_eval.datasets.pipeline --synthetic 500

# 真实 PR 抽取：从 GitHub API 拉取 PR 的 diff + review comment 构造成评测集
python -m code_review_eval.datasets.pipeline --repo pandas-dev/pandas --token-file .gh-token

# 混合：合成 + 真实
python -m code_review_eval.datasets.pipeline --synthetic 200 --repo psf/requests --token-file .gh-token
```

真实 PR 抽取把「已经发生的代码评审（reviewer 提出的问题）」转成标准评测样本——review comment 的位置映射为 `location`，正文映射为缺陷描述，类型/严重度通过正文关键词归类。质量校验在入库前做三道把关：字段完整性、diff 内容去重、标注一致性。

## 评测集格式

每条样本 = 一段代码 diff + 上下文 + 人工标注的标准缺陷列表，每条缺陷带「类型 / 严重度 / 位置」：

```json
{
  "id": "sample-001",
  "title": "SQL 注入：字符串拼接构造查询",
  "repo": "payment-service",
  "context": "user_id 来自用户输入。",
  "diff": "def get_order(user_id):\n-    ...\n+    query = \"SELECT * FROM orders WHERE user_id = '\" + user_id + \"'\"",
  "defects": [
    {"id": "d001-1", "type": "security", "severity": "critical",
     "message": "字符串拼接构造 SQL，存在注入风险", "location": "payment.py:42"}
  ]
}
```

- 缺陷类型：`logic` / `security` / `performance` / `style`
- 严重度：`critical` / `major` / `minor`
- `location` 是对齐的关键：缺陷必须能落到具体位置，模型输出和标准答案之间才能判定「是否同一条缺陷」。

## 异步并发执行

评测执行用 asyncio 并发，支持重试、超时、失败隔离：

```python
from code_review_eval.async_eval import AsyncEvaluator, FakeAsyncBackend
from code_review_eval.harness import Harness

runner = AsyncEvaluator(
    harness=Harness(None),
    backend=FakeAsyncBackend(),
    max_concurrency=8,   # 并发度
    max_retries=3,       # 瞬时失败重试
    timeout=60.0,        # 单次调用超时
)
```

重试采用指数退避 + 抖动，避免同时重试打爆上游限流；单条样本失败被隔离，不拖垮整批，失败原因被记录。

## 可复现 run 管理

每次评测生成唯一 `run_id`，产物落到独立目录，配置快照随结果一起落盘：

```
runs/<run_id>/run.json   完整结果（固定 schema，供程序化消费）
runs/<run_id>/report.md  人类可读报告
```

支持历史 run 的趋势对比，识别指标退化（防止「这次比上次差了」但没人发现）。

## 质量门禁

评测结果作为质量否决项：

```python
from code_review_eval.gate import QualityGate

gate = QualityGate({"f1": 0.7, "recall": 0.6})
result = gate.check(metrics_by_backend)
# result.exit_code: 0=通过 1=不通过，可直接接 CI
```

## 归因可视化看板

评测后可生成自包含的交互式 HTML 看板，四板块：

1. **跨模型指标对比**：分组柱状图（Precision / Recall / F1）；
2. **缺陷类型归因**：堆叠柱状图（每个模型各类缺陷的漏报数）；
3. **critical 漏报明细**：最不能漏的缺陷，谁漏了、漏了什么；
4. **历史趋势**：多次 run 的 F1 走向，识别退化。

```bash
# 评测同时产出看板
creh eval --benchmark data/benchmark.jsonl --synthetic 50 --dashboard dashboard.html

# 或从已有评测结果直接生成
python -c "
from code_review_eval.dashboard import extract_from_report, write_dashboard
from code_review_eval.evaluate import evaluate, load_samples
# ... 拿到 report 后：
write_dashboard(extract_from_report(report), 'dashboard.html')
"
```

看板数据内嵌在 HTML 里，ECharts 也内嵌（完全离线可用，不依赖 CDN），单文件可直接浏览器打开、无需后端。

示例看板见 `examples/dashboard.html`（用「模型 A / 模型 B」对比数据生成，浏览器直接打开即可预览效果）。

## 架构

```
评测集管线（真实 PR 抽取 + 合成生成）
      │  质量校验（去重/完整性/一致性）
      ▼
评测集 (benchmark.jsonl)
      │
      ▼
Harness 层 ── 统一 LLM 接口 · 结构化 JSON 输出 · 可解析性校验
      │
      ▼
Model 层 ── 缺陷对齐打分（Precision / Recall / F1）
      │
      ├── 归因分析：哪个模型哪类缺陷漏报最多
      ├── 质量门禁 + 语义化退出码
      ├── run 产物落盘 + 历史趋势
      └── 归因可视化看板（交互式 HTML）
```

## 接入真实模型

框架内置 `OpenAICompatibleBackend`，可连任意 OpenAI 兼容服务：

```python
from code_review_eval.harness import OpenAICompatibleBackend

backend = OpenAICompatibleBackend(
    base_url="https://api.openai.com/v1",  # 或本地 vLLM 等
    api_key="sk-...",
    model="gpt-4o-mini",
)
```

## 目录结构

```
src/code_review_eval/
  schema.py        数据模型（Sample / Defect / ReviewIssue）
  harness.py       Harness 层（统一调用 + 解析校验）
  aligner.py       Model 层（缺陷对齐 + 打分 + 归因）
  location.py      位置区间解析（LocationSpan / 行号距离衰减）
  semantic.py      语义匹配（cosine / embedding / 零依赖兜底）
  report.py        归因分析 + 报告输出
  evaluate.py      同步 + 异步评测入口
  async_eval.py    异步并发执行器（并发/重试/超时/隔离）
  runstore.py      可复现 run 管理（run_id/配置快照/趋势）
  gate.py          质量门禁 + 退出码 + 防退化
  dashboard.py     归因可视化看板（结论先行 + 交互式 HTML）
  cli.py           工业级评测 CLI
  datasets/
    synthetic.py   合成数据生成
    github_source.py  真实 PR 抽取（含非缺陷评论过滤）
    validation.py  数据质量校验
    pipeline.py    数据管线统一入口
data/samples.jsonl   样例评测集（离线可复现）
scripts/verify_real_data.py   真实数据验证脚本
tests/               单元测试（核心 + 对齐 + 数据管线 + 工业级 + 看板）
demo.py              离线演示入口
Makefile             统一工程入口（test/lint/typecheck/ci）
.pre-commit-config.yaml   提交前自动检查
```

## Roadmap

- 更多后端适配（Anthropic / 本地模型服务）
- 评测集版本管理（数据集快照与变更追踪）
- 按产品线聚合的归因看板细化
