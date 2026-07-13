1. 核心结论
- 本次结果来自 `config=tokamak`、`preset=ITER`。当前运行点 `valid=1.0`、`ignited=0.0`，`Pfus=1472.30`、`Qfus=38.62`、`Pheat=38.12`、`Pwall=2.05`。
- 就当前运行点而言，0-D 模型给出了有效解，但该单点结果未点火；“运行点有效”只说明这一个参数点被模型接受，不等同于扫描已经证明存在明确工作窗。
- 就 POPCON 扫描而言，扫描轴为 `xkey=Ti0`、`ykey=ni0`，`n_invalid=0`；`best` 矩阵并非全 0，说明在当前准则下至少有少数网格单元被标记为最佳。
- 同时，扫描缺少 `x/y` 坐标数组且未给出 `nx/ny`，因此“扫描网格证据不足，不能判断工作窗形状或敏感性趋势”。
- `use_tauE=1.0` 且 `tauE=2.0`，结果依赖固定约束时间假设；`geom_model=0.0`，几何模型较简化。

2. 关键指标解读
- 运行点功率面：`Pfus=1472.30`、`Qfus=38.62`、`Pheat=38.12`、`Pwall=2.05`，并给出 `Pn=1177.84`、`Pth=272.84`、`Ptrans=272.84`；这些是当前单点的 0-D 功率收支结果。
- 约束与阈值模型：`tauE_used=2.0`、`tau_ITPA20=1.365`、`H98=1.160`、`H_ITPA20=1.465`。由于 `use_tauE=1`，这些结果建立在固定约束时间输入上。`LH_ratio=3.063` 对应 `P_LH=89.07` 的阈值模型比较，只能理解为模型中的相对关系，不能表述为保证进入或维持 H 模。
- 边界类指标：`betaN=2.589`、`betaT=0.0366`、`betap=1.020`、`q=2.12`、`q95=3.866`、`nbar_o_nGw=1.115`；这些数值可作为当前点的边界约束观察量，但仅凭本次 JSON 不能外推其余量。
- 成分与辐射：`Zeff=1.867`、`fHe=0.04`、`fimp=0.01`、`Zimp=10`；辐射/损失项中 `Pbrem=53.83`、`Pcycl=5.91`、`P_line=0.0`，说明本次输出中线辐射通道未给出非零贡献。
- 几何与体表面积：`Vp=888.33`、`Sw=735.45`，且 `Vp_geom=888.33`、`Sw_geom=735.45`、`geom_volume_ratio=1.0`、`geom_wall_ratio=1.0`；结合 `geom_model=0`，本次几何处理偏简化。
- POPCON 扫描证据：`best` 矩阵中存在值为 1 的单元，`n_invalid=0` 说明扫描结果里没有被标记为 invalid 的点；但由于缺少 `x/y` 数组及 `nx/ny`，不能据此判断最佳区的位置、边界、连通性或敏感性趋势。

3. 风险与不确定性
- 最大的不确定性来自 `use_tauE=1`：当前 `Pfus`、`Qfus`、`LH_ratio`、`ignited` 等结果都依赖固定 `tauE=2.0` 的假设，若约束时间假设变化，结论可能随之变化。
- `geom_model=0` 表明几何模型较简化，因此 `Vp`、`Sw`、`Pwall` 及相关派生量的解释应保留模型层面的不确定性。
- 虽然当前运行点 `valid=1.0`，且扫描 `n_invalid=0`，但这两者不能替代对扫描工作窗的完整判断；当前仍需明确区分“单点有效”与“扫描找到可用区域”。
- 扫描层面缺少 `x/y` 坐标数组和 `nx/ny`，因此无法判断最佳区是否连续、是否贴近边界，也无法判断 `Ti0` 或 `ni0` 的敏感性方向。
- `P_line=0.0` 只能按本次模型输出理解，不能仅凭这一条就把线辐射影响视为普遍可忽略。
- 当前点 `ignited=0.0`，说明在本次模型设定下未达到点火状态；这与 `Pfus`、`Qfus` 较高并不矛盾，因为二者描述的是不同维度的输出。

4. 下一步建议
- 1. 补全 `Ti0`-`ni0` 扫描导出：重新输出 `x`、`y`、`nx`、`ny`、`best` 以及对应的 `valid`/`ignited` 掩码；重点监控 `best`、`n_invalid`、`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`Pwall`、`betaN`、`q95`、`nbar_o_nGw`。
- 2. 围绕当前点 `Ti0=20.0`、`ni0=1.5e20` 做局部加密扫描：缩小步长检查最佳单元是否连续出现；重点监控 `best`、`Pfus`、`Qfus`、`Pheat`、`Pwall`、`betaN`、`q`、`q95`、`nbar_o_nGw`、`LH_ratio`。
- 3. 做约束时间敏感性验证：在 `use_tauE=1` 条件下扫描 `tauE`，并把结果与 `tau_ITPA20`、`H98`、`H_ITPA20` 对照；重点监控 `tauE_used`、`Pfus`、`Qfus`、`ignited`、`valid`、`LH_ratio`、`Pwall`。
- 4. 做成分与辐射参数扫描：扫描 `fimp`、`Zimp`、`fHe`，必要时联动 `Sn`；重点监控 `Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Pfus`、`Qfus`、`Pwall`、`LH_ratio`。
- 5. 做几何模型对照验证：若工具支持，比较 `geom_model=0` 与更详细几何设定，或对 `Vp_override`、`Sw_override` 做一致性检查；重点监控 `Vp`、`Sw`、`Pwall`、`Pfus`、`Qfus`、`betaN`、`q95`。
