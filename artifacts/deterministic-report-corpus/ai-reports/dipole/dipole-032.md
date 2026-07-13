1. 核心结论
- 本次数据对应 `config=dipole`、`preset=Dipole-DD`。当前运行点 `valid=1.0`、`ignited=0.0`，`Pfus=21.982910585070492`、`Qfus=1.2971542213188554`、`Pheat=16.947029292106695`、`Pwall=0.030979461828615214`。
- 就当前运行点而言，这是一个有效计算点，但不是点火点；`Qfus_raw=1.2971542213188554`，与 `Qfus` 一致。
- 就 POPCON 扫描而言，扫描变量是 `xkey=Ti0`、`ykey=n0`；给出的 `best` 矩阵全为 0，因此“当前准则下未找到最佳区”。
- 运行点有效不等于扫描找到了工作窗；本次数据只能说明当前单点可计算且 `valid=1.0`，不能据此推出扫描中存在满足当前准则的区域。
- 扫描结果未提供 `x/y` 数组，也未显式提供 `nx/ny`；“扫描网格证据不足，不能判断工作窗形状或敏感性趋势”。

2. 关键指标解读
- 当前运行点的功率相关量为：`Pfus=21.9829`、`Pheat=16.9470`、`Ptrans=16.1410`、`Pn=7.3753`、`Pwall=0.0310`；在这个单点上，`Pheat` 与 `Ptrans` 数值接近。
- 辐射与损失项中，`Pbrem=15.3633`、`Pcycl=0.05034`、`P_line=0.0`；按已给出的三个辐射通道看，轫致辐射项最大，线辐射在当前输入下为 0。
- 约束方面，`use_tauE=1.0`、`tauE=5.0`，输出也给出 `tau_E=5.0`；这表示结果依赖固定约束时间假设。另有 `tauC_eff=487.8944`、`tau_eq_ie=0.05122`。
- 成分设定为 `Zeff=1.0`、`fHe=0.0`、`fimp=0.0`、`Zimp=10`；因此本次结果对应的是一个不含 He 灰、也不含杂质分数的输入点。
- 密度与相关量包括 `n0=2e+21`、`ne0=2e+21`、`nbar=7.882282451346217e+19`、`ntau=1e+22`；压力相关输出给出 `beta_in=1.6303361449091331`、`beta_out=0.3745231463025947`。
- 几何/模型信息里可直接读取 `Vp=1890.3037`、`Sw=1256.6371`、`ring_model=1.0`，以及 `cyclotron_model=equatorial_shell_proxy`；本次数据未给出 `geom_model` 字段。

3. 风险与不确定性
- 最大的不确定性来自 `use_tauE=1.0`：由于 `tau_E` 被固定为 5.0，当前 `valid`、`ignited`、`Pfus`、`Qfus` 等结果都依赖这一固定约束时间假设，而不是来自一套独立给出的约束时间标度扫描。
- POPCON 证据不足：虽然给出了 `best` 矩阵和 `n_invalid=0`，但缺少 `x/y` 数组以及显式 `nx/ny`，所以不能判断最佳区位置、边界、连通性，亦不能判断对 `Ti0` 或 `n0` 的敏感性趋势。
- `best` 全零只说明在当前判据下没有被标记为最佳的扫描点；这不能与“当前运行点 `valid=1.0`”混为一谈，也不能据此推出更广义的参数空间结论。
- 成分与辐射设定较理想化：`fHe=0.0`、`fimp=0.0`、`Zeff=1.0`，同时 `P_line=0.0`；因此本次结果没有覆盖 He 灰或杂质引入后对辐射和功率平衡的影响。
- `geom_model` 未报告，因此无法确认几何是否采用了更简化或更完整的处理；当前只能依据 `Vp`、`Sw`、`ring_model` 和场量输出做有限解读。

4. 下一步建议
- 先补齐同一组 `Ti0-n0` POPCON 扫描输出：显式导出 `x`、`y`、`nx`、`ny`、`best_fraction`。需要监控的指标：`best`、`n_invalid`、`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
- 在当前 `config=dipole`、`preset=Dipole-DD` 下做 `tauE` 敏感性扫描，重点围绕固定值 `tauE=5.0` 展开。需要监控的指标：`tau_E`、`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`Ptrans`、`Pwall`、`tauC_eff`。
- 做成分/辐射敏感性扫描，优先变化 `fimp`、`Zimp`、`fHe`。需要监控的指标：`Zeff`、`Pbrem`、`P_line`、`Pcycl`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
- 若要继续用 POPCON 判断参数空间，建议分别执行 `Ti0-n0` 与 `Te0-n0` 或 `Ti0-tauE` 扫描。需要监控的指标：`best`、`n_invalid`、`valid`、`ignited`、`Pfus`、`Qfus`、`Ptrans`、`beta_in`、`beta_out`。
- 补充导出几何模型元数据，至少确认是否有 `geom_model` 及其取值。需要监控的指标：`Vp`、`Sw`、`ring_model`，以及任何几何覆盖或修正字段。
