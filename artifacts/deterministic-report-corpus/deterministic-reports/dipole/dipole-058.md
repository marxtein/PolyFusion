# 1. 核心结论
- 本次案例为 `config=dipole`（偶极场 Dipole），`preset=Dipole-DD`。
- 当前运行点：`valid=1`、`ignited=0`；`Pfus=2.191`、`Qfus=0.4795`、`Pheat=4.569`、`Pwall=0.00538`。
- 当前点是数值有效的 0-D 解。`Qfus` 低于 1，当前点表现为外部加热主导。
- POPCON 扫描为 `Ti0 × n0`，`n_invalid=0`；当前准则下未找到最佳区。
- `use_tauE=1`，结果依赖固定约束时间假设。

# 2. 关键指标解读
- 功率与损失：`Pfus=2.191`、`Qfus=0.4795`、`Pheat=4.569`、`Pwall=0.00538`、`Ptrans=5.474`、`Pbrem=0.5299`、`Pcycl=0.0217`、`P_line=0`、`Pn=0.7351`。
- 约束、成分与几何：`tau_E=5`、`Zeff=1`、`Vp=1890`、`Sw=1257`。
- 偶极场 Dipole 专属指标：`beta_in=0.5529`、`beta_out=0.127`、`tauC_eff=210.3`、`cyclotron_model=equatorial_shell_proxy`。
- 当前点对默认 best 准则的逐项核对：`Pfus=2.191` 满足 `>=1`；`Qfus=0.4795` 不满足 `>=1`；`beta_in=0.5529` 满足 `<=1`。

# 3. 风险与不确定性
- `valid` 只描述单点数值有效性，不能替代 POPCON 工作窗证据。
- 扫描缺少完整 `x/y` 坐标证据，不能给出最佳区实际边界或敏感性方向。
- best 全为 0 只表示当前筛选准则未命中，不等于所有网格点都数值无效。
- 当前点未满足默认 best 准则中的：`Qfus`。
- 固定 `tauE` 会直接影响功率平衡、增益和点火判断，需做约束时间敏感性扫描。
- `P_line=0` 只代表当前成分和模型输出，不能外推为线辐射始终可忽略。

# 4. 下一步建议
1. 加密 `Ti0 × n0` POPCON 网格，保存完整 `x/y/best/valid`；监控 `best_fraction`、`n_invalid`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
2. 扫描 `tauE` 或切换约束标度；监控 `tauE_used/tau_E`、`ignited`、`Pfus`、`Qfus`、`Ptrans`。
3. 扫描 r_ring、R_p、B_ring；监控 beta_in、beta_out、Pwall，并逐项复核默认 best 准则。
4. 扫描 `fHe`、`fimp`、`Zimp`；监控 `Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Qfus`。
