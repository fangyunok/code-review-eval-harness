# Changelog

本文件记录项目的所有重要变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed

- 对齐算法升级：位置从字符串升级为「文件+行号区间」，用行号距离衰减打分（容忍偏移），替代脆弱的字符串相等匹配。
- 对齐加入「类型强约束」：缺陷类型不同直接判定不匹配，避免位置巧合导致的乱配。
- 新增可选语义嵌入对齐（`EmbeddingSemanticMatcher`），双模式设计：默认零依赖词法兜底，可选 `[embeddings]` 接入 embedding 模型。
- 真实 PR 抽取加入「非缺陷评论过滤」：过滤纯赞同/感谢/表情/过短评论，避免把 `+1`、`LGTM` 当成缺陷标注。

### Added

- 真实模型后端 `backends.py`：`OpenAIAsyncBackend`（异步、超时、可选限流）、`AnthropicAsyncBackend`（Claude 异步）、`OllamaAsyncBackend`（本地 Ollama，零 SDK 依赖）、`OpenAICompatibleBackend`（同步）。
- CLI 新增 `--model / --api-key / --base-url / --min-interval` 参数，一条命令接真实模型跑评测（单模型或多模型逗号分隔对比）。
- 位置区间解析模块 `location.py`（`LocationSpan` / `parse_location`）。
- 语义嵌入端到端：`SentenceTransformerEmbedder`（本地模型）与 `OpenAIEmbeddingEmbedder`（云端 API）。
- 评测集版本快照（manifest）：记录样本数、来源、seed、时间戳、内容 SHA256。
- 多仓库批量抽取：`--repo` 支持逗号分隔多个仓库。
- 语义匹配模块 `semantic.py`（`cosine_similarity` / `EmbeddingSemanticMatcher` / `NoopSemanticMatcher`）。
- 代码质量工具链：ruff（lint+format）、mypy（类型检查）、Makefile 统一入口、pre-commit 配置。
- MIT License、CHANGELOG.md。
- 看板「结论先行」区块：第一屏展示最优模型、F1 领先幅度、最薄弱缺陷类型、critical 漏报数。
- 真实数据验证脚本 `scripts/verify_real_data.py`。

### Fixed

- 修复对齐算法死代码：原「语义兜底」分支因条件重复永不执行，已重构。

## [0.2.0] - 2026-10-28

### Added

- 评测集管线：真实 PR 抽取（GitHub API）+ 合成数据生成 + 质量校验（去重/完整性/一致性）。
- 异步并发评测（asyncio + 重试 + 超时 + 失败隔离）。
- 可复现 run 管理（run_id + 配置快照 + 历史趋势）。
- 质量门禁（阈值否决 + 语义化退出码 + 防退化）。
- 工业级评测 CLI（`creh eval`）。

### Changed

- 版本号从 0.1.0 升到 0.2.0。

## [0.1.0] - 2026-10-28

### Added

- 双层评测架构：Harness 层（统一调用 + 解析校验）+ Model 层（缺陷对齐打分）。
- 缺陷对齐打分（Precision / Recall / F1）+ 归因分析 + 报告输出。
- 离线样例评测集 + 单元测试 + 演示入口。
