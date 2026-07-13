1. 核心结论
- 本次 0-D 结果对应 `config=tokamak`、`preset=ITER`。当前运行点 `valid=1.0`、`ignited=0.0`，`Pfus=580.253 MW`、`Qfus=1.035`、`Pheat=560.503 MW`、`Pwall=1.551 MW/m^2`。
- 这说明当前设定下单点解是可计算的，但并未点火；`Qfus` 仅略高于 1，不能把它理解成自持燃烧已经建立。
- 必须把“当前运行点”与“POPCON 扫描”分开看：单点 `valid=1.0` 只说明这个输入点有有效解，不等同于扫描已经证明存在明确工作窗。
- POPCON 扫描的轴为 `xkey=Ti0`、`ykey=ni0`。`best` 矩阵并非全 0，其中有 2 个格点被标记为 1，`n_invalid=0`；这只能说明扫描中存在满足当前最佳判据的离散格点。
- 由于未提供 `x/y` 扫描数组，扫描网格证据不足，不能判断工作窗形状或敏感性趋势。

2. 关键指标解读
- 约束时间与约束因子：`tauE_used=2.0 s`，且 `use_tauE=1.0`，说明结果依赖固定约束时间假设。对应地，`H98=2.972`、`H_ITPA20=2.730`、`tau_ITPA20=0.733 s`，可理解为在该固定 `tauE` 下相对经验标度的反算要求。
- 功率与损失：`Pfus=580.253 MW`，中子功率 `Pn=464.202 MW`；热功率相关量 `Pth=441.746 MW`、`Ptrans=441.746 MW`。损失项中 `Pcycl=219.588 MW` 明显大于 `Pbrem=15.220 MW`，而 `P_line=0.0 MW`。
- L-H 阈值比较：`LH_ratio=10.902`，并给出 `P_LH=40.518 MW`。这里只能表述为当前结果包含了与 L-H 阈值模型的比较，不能据此写成保证进入或维持 H 模。
- 边界与运行状态指标：`betaN=4.192`、`betaT=0.0593`、`betap=1.651`，`q=2.12`、`q95=3.866`，`nbar_o_nGw=0.372`。这些量可用于后续扫描时判断该运行点对边界条件的敏感性，但仅凭当前 JSON 不能下更强结论。
- 成分与辐射相关输入：`Zeff=1.867`，`fHe=0.04`、`fimp=0.01`、`Zimp=10`。这组输入与 `Pbrem`、`P_line`、`Pcycl` 一起决定了当前 0-D 功率平衡中的杂质/辐射表征。
- 几何量：`Vp=888.329 m^3`、`Sw=735.451 m^2`，且 `geom_model=0.0`，必须说明几何模型较简化；同时 `geom_volume_ratio=1.0`、`geom_wall_ratio=1.0`，本次结果没有体现额外几何修正。

3. 风险与不确定性
- `use_tauE=1.0` 是本次结果的主要不确定性来源之一；如果真实约束时间偏离 `2.0 s`，则 `Pfus`、`Qfus`、`Pheat` 以及相关边界量都可能明显变化。
- `geom_model=0.0` 表明几何处理较简化，因此 `Vp`、`Sw`、`Pwall` 以及与几何相关的辐射/表面负荷解读都带有模型依赖性。
- 扫描层面虽然给出了 `best` 矩阵，但缺少 `x/y` 数组，且未见 `nx/ny` 字段；因此只能确认有离散 best 标记，不能判断最佳区的连续性、边界位置或对 `Ti0`、`ni0` 的敏感性趋势。
- 当前点 `ignited=0.0`，说明没有达到点火状态；因此不能把单点的 `Pfus` 或 `Qfus` 表现外推成更广范围的自持特性。
- `Pcycl` 在已列出的损失项中占比很高，而 `P_line=0.0` 是否来自输入设定、模型关闭或该点确实为零，当前 JSON 不足以进一步区分。
- `LH_ratio`/`P_LH` 只提供阈值模型比较证据，不应被当作实际运行模态转换的确定性判断。

4. 下一步建议
1. 重新执行 `Ti0`–`ni0` 的 POPCON 扫描，并在输出中补齐 `x`、`y`、`nx`、`ny`、`best_fraction`；重点监控 `best` 分布、`n_invalid`、`valid`、`Pfus`、`Qfus`、`Pwall`、`betaN`、`q95`、`nbar_o_nGw`。
2. 做约束时间敏感性验证：以当前 `tauE=2.0 s` 为中心做参数扫描，或切换到非固定 `tauE` 的标度运行作对照；重点监控 `tauE_used`、`H98`、`H_ITPA20`、`Pfus`、`Qfus`、`ignited`、`Pheat`、`LH_ratio`、`P_LH`。
3. 做几何模型/受壁面积敏感性扫描：改变 `geom_model`，并对 `Sw_override`、`Vp_override` 做一致性对照；重点监控 `Sw`、`Vp`、`Pwall`、`Pcycl`、`Pbrem`、`betaN`、`q95`。
4. 做成分与辐射参数扫描：围绕 `fHe`、`fimp`、`Zimp`、`Zeff` 相关设定逐项扫描；重点监控 `Zeff`、`Pbrem`、`P_line`、`Pcycl`、`Pheat`、`Pfus`、`Qfus`、`valid`。
5. 做单点复核任务：保持当前 `config=tokamak`、`preset=ITER` 不变，只对 `Ti0`、`ni0` 在当前点附近做小步长局部扫描；重点监控当前点是否稳定保持 `valid=1.0`，以及 `ignited`、`Pfus`、`Qfus`、`Pwall`、`betaN` 是否出现快速跳变。
