# 1. 核心结论
- 本次案例为 `config=stellarator`（仿星器 Stellarator），`preset=HELIAS`。
- 当前运行点：`valid=1`、`ignited=0`；`Pfus=3038`、`Qfus=4.708`、`Pheat=645.2`、`Pwall=2.311`。
- 当前点是数值有效的 0-D 解。`Qfus` 已达到 1 以上，但仍依赖外部加热且不等同于点火。
- POPCON 扫描为 `Ti0 × ni0`，命中 `14/64` 个 best 网格（`best_fraction=0.2188`），候选区在当前粗网格中较有限；这不代表当前运行点必然位于 best 区。
- `use_tauE=1`，结果依赖固定约束时间假设。

# 2. 关键指标解读
- 功率与损失：`Pfus=3038`、`Qfus=4.708`、`Pheat=645.2`、`Pwall=2.311`、`Ptrans=1143`、`Pbrem=65.94`、`Pcycl=43.97`、`P_line=0`、`Pn=2430`。
- 约束、成分与几何：`tauE_used=1`、`Zeff=1.867`、`Vp=1149`、`Sw=1593`。
- 仿星器 Stellarator 专属指标：`H_ISS04=1.855`、`betaT=0.06666`、`nbar_o_Sudo=0.4156`、`iota=0.8221`、`aspect_vol=10.01`。
- 当前点对默认 best 准则的逐项核对：`Pfus=3038` 满足 `>=10`；`Qfus=4.708` 满足 `>=1`；`nbar_o_Sudo=0.4156` 满足 `<=1`；`betaT=0.06666` 不满足 `<=0.05`；`H_ISS04=1.855` 不满足 `<=1.5`。

# 3. 风险与不确定性
- `valid` 只描述单点数值有效性，不能替代 POPCON 工作窗证据。
- 扫描缺少完整 `x/y` 坐标证据，不能给出最佳区实际边界或敏感性方向。
- 当前点未满足默认 best 准则中的：`betaT`、`H_ISS04`。
- 固定 `tauE` 会直接影响功率平衡、增益和点火判断，需做约束时间敏感性扫描。
- `P_line=0` 只代表当前成分和模型输出，不能外推为线辐射始终可忽略。

# 4. 下一步建议
1. 加密 `Ti0 × ni0` POPCON 网格，保存完整 `x/y/best/valid`；监控 `best_fraction`、`n_invalid`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
2. 扫描 `tauE` 或切换约束标度；监控 `tauE_used/tau_E`、`ignited`、`Pfus`、`Qfus`、`Ptrans`。
3. 扫描 B0、N_fp、H_fac、iota；监控 betaT、nbar_o_Sudo、H_ISS04，并逐项复核默认 best 准则。
4. 扫描 `fHe`、`fimp`、`Zimp`；监控 `Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Qfus`。
