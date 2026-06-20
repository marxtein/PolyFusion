# 多位形升级任务计划 (2026-06-20)

项目：`E:\work\digitalfusion-release` (polyfusion 0D 多位形系统设计台)
前端：`app/index.html` (1361 行, 单文件 Plotly SPA)
后端：`app/server.py` (stdlib), 物理核 `polyfusion/`
平衡文件：`app/equilibria/{tokamak/*.geqdsk, stellarator/*.nc}` + `manifest.json`
预设：`polyfusion/presets/{tokamak,stellarator,mirror,frc,dipole}.json`

## 任务清单（来自用户）

- [ ] T1 托卡马克平衡文件增多（来源 veqpy `data/*.geqdsk` + OMAS samples + veqpy 导出）
- [ ] T2 仿星器平衡文件增多（联网搜：simsopt test_files / DESC / 公开 VMEC wout .nc）
- [ ] T3 仿星器导入确认弹窗去掉（index.html L485-492 `confirm()`）
- [ ] T4 托卡马克几何输入第一项 `传统` → `双椭圆`（L441；L1120 文案核对）
- [ ] T5 全位形磁面渲染统一：磁面=很细灰线，壁=较粗红线，等离子体边界=青色（对齐现托卡马克）。重点修仿星器、偶极场。(GEO()/SHAPE_GROUPS L1063+)
- [ ] T6 几何输入参数尽量标注在图上正确位置；抽象参数配公式说明。各位形几何图加合理标注。
- [ ] T7 磁镜/FRC/偶极子 最佳判别区间 合理性与缺漏审查（polyfusion configs best_window）。必要时联网。
- [ ] T8 托卡马克温度/密度剖面更像 H 模（带 pedestal）；仿星器是否有 H 模→联网，有则像，无则合理。(L1309+)
- [ ] T9 每个预设各加一个"用户设计"占位预设（5 个 json）
- [ ] T10 通用优化 + bug 排查

## Agent 架构（避免同文件并发写冲突）

- 主线程：编排 + 计划 + index.html 所有编辑（串行，单写者，避免 112KB 文件冲突）+ 验收协调
- 并行执行 agent（互不冲突文件）：
  - **EQ agent**：下载/生成平衡文件 → `app/equilibria/*` + `manifest.json`（联网 curl）
  - **PRESET/PHYS agent**：5 个 preset json 加"用户设计" + best_window 物理审查（只改 json / python configs）
  - **RESEARCH agent**：联网调研（仿星器 H 模、mirror/frc/dipole 判别区间文献）→ 写 findings.md
- 验收 agent：cavecrew-reviewer 审 diff + 跑 pytest + 起 server 验证

## 阶段 + 检查点

- P0 侦察 + 计划（✅ 当前，checkpoint 1 已存）
- P1 联网调研 (RESEARCH) → findings.md  ← checkpoint 2
- P2 并行：EQ 平衡文件 + PRESET/PHYS  ← checkpoint 3
- P3 index.html 编辑：T3 弹窗 → T4 双椭圆 → T5 颜色统一 → T6 参数标注 → T8 剖面  ← 每子项后存
- P4 验收：pytest + server 起动 + 浏览器验证 + reviewer  ← checkpoint final
- P5 verification-before-completion + 总结

## 决策记录

- 平衡文件数量：托卡马克目标 +4~6（覆盖更多预设），仿星器 +3~4。来源优先公开真实文件，注明 source/url。
- index.html 串行单写，降低风险（用户强调"不要出问题"）。
- git 已存在 → 可回滚，但仍按检查点存盘。
