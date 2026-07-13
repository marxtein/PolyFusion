**1. 核心结论**

- `config=tokamak`，`preset=ITER`。
- 当前运行点：`valid=1`，`ignited=0`，`Pfus=5218.83`，`Qfus=3.42`，`Pheat=1524.86`，`Pwall=9.17`。
- 这说明当前 0-D 运行点求得了有效解，但这不等同于 POPCON 扫描已经确认存在明确工作窗。
- `last_scan` 给出了 `xkey=Ti0`、`ykey=ni0` 的 `best` 矩阵，且矩阵并非全 0，说明当前准则下至少有命中单元。
- 但由于未提供 `x/y` 数组，且 `nx/ny` 缺失，**扫描网格证据不足，不能判断工作窗形状或敏感性趋势**。

**2. 关键指标解读**

- 运行点功率侧：`Pth=Ptrans=1676.03`，`P_LH=89.07`，`LH_ratio=18.82`。这里仅能理解为当前功率与所用 L-H 阈值模型的比较，不能据此表述为保证进入或维持 H 模。
- 约束时间与标度：`use_tauE=1`，`tauE_used=2.0`，结果依赖固定约束时间假设；同时给出 `H98=4.76`、`H_ITPA20=5.47`、`tau_ITPA20=0.366`，可作为与不同约束时间标度的对照。
- 损失与辐射：`Pcycl=727.95`，`Pbrem=164.64`，`P_line=0`。当前输出里相关损失主要来自回旋辐射和轫致辐射。
- 边界/平衡量：`betaN=15.91`，`betaT=0.225`，`betap=6.27`，`q=2.12`，`q95=3.87`，`nbar_o_nGw=1.115`。这些是当前点的状态量，应与功率结果一起看。
- 成分参数：`Zeff=1.867`，`fHe=0.04`，`fimp=0.01`，`Zimp=10`。
- 几何参数：`Vp=888.33`，`Sw=735.45`，`geom_model=0`，因此几何模型较简化。
- POPCON 扫描侧：扫描变量标签是 `Ti0`-`ni0`，`n_invalid=0`。但由于没有 `x/y/nx/ny`，不能把 `best` 命中单元解释成明确的最佳区位置、边界或趋势。

**3. 风险与不确定性**

- `use_tauE=1` 使结果直接依赖固定 `tauE=2.0` 的设定；若改用标度或改变 `tauE`，`Pfus`、`Qfus`、`Pheat` 以及 `best` 判定都可能变化。
- `geom_model=0` 表明几何处理较简化，当前 `Vp`、`Sw`、`Pwall` 的解释受该假设限制。
- 当前运行点 `valid=1` 只说明该点有有效解；`ignited=0` 说明它不是点火解。这与 POPCON 是否存在连续工作窗是两件事，不能混为一谈。
- **扫描网格证据不足，不能判断工作窗形状或敏感性趋势。** 直接原因是 `nx/ny` 缺失，且未提供 `x/y` 坐标数组。
- 虽然 `best` 矩阵不是全 0，但在缺少坐标映射和判据细节的情况下，不能进一步说明最佳区的物理位置、范围或边界。

**4. 下一步建议**

- 重新导出一次 `Ti0`-`ni0` POPCON 全量结果，至少包含 `x`、`y`、`nx`、`ny`、`best`、`n_invalid`。监控指标：`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`Pwall`、`n_invalid`、`best` 分布。
- 在相同基线参数下做 `tauE` 或 `H_fac` 敏感性扫描，专门检验固定约束时间假设的影响。监控指标：`tauE_used`、`H98`、`H_ITPA20`、`tau_ITPA20`、`Pfus`、`Qfus`、`best` 判定。
- 做几何敏感性验证：比较 `geom_model=0` 与替代几何设定，或对 `Vp_override`、`Sw_override` 做受控扫描。监控指标：`Vp`、`Sw`、`Pwall`、`betaN`、`q95`。
- 做成分/辐射扫描：围绕 `fHe`、`fimp`、`Zimp` 逐项扰动。监控指标：`Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Pheat`、`Pfus`、`valid`。
- 对 `Ti0`、`ni0` 做更细步长扫描，并同步记录边界量。监控指标：`nbar_o_nGw`、`betaN`、`betaT`、`betap`、`q`、`q95`、`Pfus`、`Qfus`。
