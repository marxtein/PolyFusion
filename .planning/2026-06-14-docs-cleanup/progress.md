# Progress

## 2026-06-14
- 读取 `using-superpowers` 与 `planning-with-files`。
- 盘点 release docs、old docs、release 代码清单。
- 发现 `rg.exe` 在当前环境被拒绝执行，切换为 PowerShell 原生命令。
- 创建文档整理计划，准备进入标题索引与代码事实核对。
- 抽取 release/old docs 标题索引，确认旧文档存在大量历史过程型重复。
- 抽取 release Python 模块的函数/类索引，确认新版文档应以 `polyfusion` 与 `configs` 为核心组织。
- 核对 `ConfigSpec`、注册表、API、CLI、扫描、验证边界，修正一次错误字段假设。
- 生成 `docs/clean` 下 7 篇整理版 Markdown 文档。
- 校验整理版文档相对链接，结果无缺失。
- 校验整理版文档中无 `etsc_core`、`TODO`、`待补`、`旧路径` 残留。
- 运行 `python -m polyfusion --list` 成功列出五个位形。
- 运行五个位形首个预设单点计算和 4x4 扫描，均返回有效结果。
- `python -m pytest polyfusion/tests` 未运行成功，原因是当前 Python 环境未安装 `pytest`。
