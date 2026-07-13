# 1. 核心结论
- 本次案例为 `config=mirror`（磁镜 Magnetic Mirror），`preset=BEAM`。
- 当前运行点：`valid=1`、`ignited=0`；`Pfus=61.98`、`Qfus=14.05`、`Pheat=4.412`、`Pwall=2.917`。
- 当前点是数值有效的 0-D 解。`Qfus` 较高，但 0-D 增益不能单独证明装置方案成立。
- POPCON 扫描为 `Ti0 × ni0`，命中 `10/64` 个 best 网格（`best_fraction=0.1562`），候选区在当前粗网格中较有限；这不代表当前运行点必然位于 best 区。
- `use_tauE=1`，结果依赖固定约束时间假设。

# 2. 关键指标解读
- 功率与损失：`Pfus=61.98`、`Qfus=14.05`、`Pheat=4.412`、`Pwall=2.917`、`Ptrans=16.63`、`Pbrem=0.1729`、`Pcycl=0.001058`、`P_line=0`、`Pn=49.59`。
- 约束、成分与几何：`tau_E=1`、`Zeff=1`、`Vp=2.884`、`Sw=22.76`。
- 磁镜 Magnetic Mirror 专属指标：`beta=0.99`、`beta_avg=0.396`、`coll_ratio=1187`、`tau_Past=1.361`、`tauC_eff=748.4`。
- 当前点对默认 best 准则的逐项核对：`Pfus=61.98` 满足 `>=1`；`Qfus=14.05` 满足 `>=1`；`beta=0.99` 不满足 `<=0.6`。

# 3. 风险与不确定性
- `valid` 只描述单点数值有效性，不能替代 POPCON 工作窗证据。
- 扫描缺少完整 `x/y` 坐标证据，不能给出最佳区实际边界或敏感性方向。
- 当前点未满足默认 best 准则中的：`beta`。
- 固定 `tauE` 会直接影响功率平衡、增益和点火判断，需做约束时间敏感性扫描。
- `P_line=0` 只代表当前成分和模型输出，不能外推为线辐射始终可忽略。

# 4. 下一步建议
1. 加密 `Ti0 × ni0` POPCON 网格，保存完整 `x/y/best/valid`；监控 `best_fraction`、`n_invalid`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
2. 扫描 `tauE` 或切换约束标度；监控 `tauE_used/tau_E`、`ignited`、`Pfus`、`Qfus`、`Ptrans`。
3. 扫描 B_vac、R_mirror、f_throat；监控 beta、coll_ratio、tau_Past，并逐项复核默认 best 准则。
4. 扫描 `fHe`、`fimp`、`Zimp`；监控 `Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Qfus`。
