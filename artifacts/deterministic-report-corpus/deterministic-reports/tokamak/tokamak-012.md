# 1. 核心结论
- 本次案例为 `config=tokamak`（托卡马克 Tokamak），`preset=ITER`。
- 当前运行点：`valid=1`、`ignited=1`；`Pfus=7065`、`Qfus=1000`、`Pheat=-374.1`、`Pwall=9.098`。
- 当前点是数值有效的 0-D 解。模型将该点标记为点火态，但仍需通过约束、稳定性与工程模型复核。
- POPCON 扫描为 `Ti0 × ni0`，命中 `2/64` 个 best 网格（`best_fraction=0.03125`），候选区在当前粗网格中非常稀疏；这不代表当前运行点必然位于 best 区。
- `use_tauE=1`，结果依赖固定约束时间假设。
- `geom_model=0`，几何模型较简化。

# 2. 关键指标解读
- 功率与损失：`Pfus=7065`、`Qfus=1000`、`Pheat=-374.1`、`Pwall=9.098`、`Ptrans=831.5`、`Pbrem=149.2`、`Pcycl=58.17`、`P_line=0`、`Pn=5652`。
- 约束、成分与几何：`tauE_used=2`、`Zeff=1.867`、`Vp=888.3`、`Sw=735.5`。
- 托卡马克 Tokamak 专属指标：`H98=2.263`、`H_ITPA20=2.922`、`betaN=7.891`、`q=2.12`、`q95=3.866`、`nbar_o_nGw=1.487`、`LH_ratio=7.595`。
- 当前点对默认 best 准则的逐项核对：`Pfus=7065` 满足 `>=10`；`Qfus=1000` 满足 `>=1`；`nbar_o_nGw=1.487` 不满足 `<=1`；`Pheat=-374.1` 满足 `<=100`。
- `LH_ratio` 仅用于阈值模型比较，不能表述为保证进入或维持 H 模。

# 3. 风险与不确定性
- `valid` 只描述单点数值有效性，不能替代 POPCON 工作窗证据。
- 扫描缺少完整 `x/y` 坐标证据，不能给出最佳区实际边界或敏感性方向。
- best 命中不超过 5%，粗网格下可能是孤立单元，需要局部加密确认连续性。
- 当前点未满足默认 best 准则中的：`nbar_o_nGw`。
- 固定 `tauE` 会直接影响功率平衡、增益和点火判断，需做约束时间敏感性扫描。
- 简化几何会影响体积、壁面积和 `Pwall`，绝对值仅适合初筛。
- `P_line=0` 只代表当前成分和模型输出，不能外推为线辐射始终可忽略。

# 4. 下一步建议
1. 加密 `Ti0 × ni0` POPCON 网格，保存完整 `x/y/best/valid`；监控 `best_fraction`、`n_invalid`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
2. 扫描 `tauE` 或切换约束标度；监控 `tauE_used/tau_E`、`ignited`、`Pfus`、`Qfus`、`Ptrans`。
3. 扫描 Ip、BT0、H_fac；监控 betaN、q95、nbar_o_nGw、H98，并逐项复核默认 best 准则。
4. 扫描 `fHe`、`fimp`、`Zimp`；监控 `Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Qfus`。
