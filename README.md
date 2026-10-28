# code-review-eval-harness

代码评审 Agent 双层评测框架：用一个可复现的评测集 + 双层评测（Harness / Model），量化「AI 代码评审工具（ai-review）」到底评得准不准。

## 先看结论

| 能力 | 指标 | 说明 |
| --- | --- | --- |
| 工程脚手架稳定性 | 解析成功率 / 格式合规率 | Harness 层，隔离工程噪声 |
| 模型评审能力 | Precision / Recall / F1 | Model 层，字段级缺陷对齐打分 |
| 失败归因 | 按缺陷类型 / 严重度 / 产品线聚合漏报 | 定位「哪类缺陷漏得最多」 |
| 质量门禁 | 低于阈值即挂 | 评测结果作为质量否决项接入 CI |

## 为什么是「双层」评测

评测对象是两个不同的东西，不是把同一个东西评两遍：

- **Harness 层**：评「调用脚手架」——统一 LLM 接口、结构化 prompt、JSON 可解析性、格式合规率。这一层保证的是「模型输出能被稳定地拿来做评测」，隔离的是工程噪声。
- **Model 层**：评「模型评审能力」——把模型输出的评审意见和人工标注的标准缺陷做**字段级对齐**，算 Precision / Recall / F1，区分「漏报关键 bug」和「误报」。

先保证 Harness 稳定，Model 层的分数才可信。

## 快速开始

```bash
# 依赖仅需 Python 3.10+，核心评测零第三方依赖
pip install -e ".[dev]"   # 跑测试；可选 openai 后端用 ".[openai]"

# 离线跑通全链路（不烧任何 API，纯 FakeBackend 模拟两个模型）
python demo.py

# 跑单元测试
pytest -q
```

`demo.py` 会加载 `data/samples.jsonl` 评测集，模拟「模型 A / 模型 B」两个后端跑完整链路，并在 `reports/` 下产出 `report.md` 和 `report.json`。

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

## 架构

```
评测集 (samples.jsonl)
      │
      ▼
Harness 层 ── 统一 LLM 接口 · 结构化 JSON 输出 · 可解析性校验
      │
      ▼
Model 层 ── 缺陷对齐打分（Precision / Recall / F1）
      │
      ├── 归因分析：哪个模型哪类缺陷漏报最多
      └── 质量门禁 + Markdown/JSON 报告
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
  schema.py     数据模型（Sample / Defect / ReviewIssue）
  harness.py    Harness 层（统一调用 + 解析校验）
  aligner.py    Model 层（缺陷对齐 + 打分 + 归因）
  report.py     归因分析 + 报告输出
  evaluate.py   评测集加载 + 一键评测入口
data/samples.jsonl   样例评测集（离线可复现）
tests/test_core.py    单元测试
demo.py               离线演示入口
```

## Roadmap

- 从真实 PR/MR 数据自动构造评测集的数据管线（对接 GitHub API）
- 更多对齐策略：嵌入相似度对齐、位置区间重叠判定
- 按产品线聚合的归因看板与历史趋势追踪
- 更多后端适配与并发评测
