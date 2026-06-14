# 数字聚变堆文档整理计划

## Goal
整理 `E:\work\digitalfusion-release\docs` 与 `E:\work\digitalfusion\docs` 的历史文档，以 `E:\work\digitalfusion-release` 代码为准，产出一套去冗余、可维护的新文档。

## Scope
- 主要依据：`E:\work\digitalfusion-release` 代码、测试、README、release docs。
- 辅助依据：`E:\work\digitalfusion\docs` 中仍有通用价值的说明、调研、教学材料。
- 输出位置：`E:\work\digitalfusion-release\docs\clean`。
- 不删除或覆盖原文档。

## Phases
| Phase | Status | Output |
|---|---|---|
| 1. Inventory | complete | 文件清单、标题索引、代码结构索引 |
| 2. Relevance Filter | complete | 保留/合并/舍弃规则 |
| 3. Code Truth Check | complete | 当前 release 功能事实表 |
| 4. New Docs | complete | 整理版 Markdown 文档集 |
| 5. Verification | complete | 覆盖面、链接、重复度检查 |

## Decisions
- 以 release 代码为最终事实源；旧文档只作为补充素材。
- 过程报告、修复记录、重复调研不逐篇保留，抽取结论进入主题文档。
- 新文档采用“总览、快速开始、模型说明、功率账/物理闭合、配置与 API、验证与测试、前端说明、维护记录”结构。

## Errors Encountered
| Error | Attempt | Resolution |
|---|---|---|
| `rg.exe` access denied | 用 `rg --files` 盘点 | 改用 PowerShell `Get-ChildItem` |
| `ConfigSpec.title` 不存在 | 首次按猜测字段读取注册表 | 改用 `list_configs()` 和 `spec.__dict__` |
| `python -m pytest` 无法运行 | 运行完整测试套件 | 当前 Python 环境缺少 `pytest`，改跑五个位形单点与小网格扫描校验 |
