1. 核心结论
- 本次结果对应 `config=stellarator`（`config_label=仿星器 Stellarator`），`preset=HELIAS`。
- 当前运行点结果为：`valid=1.0`，`ignited=0.0`，`Pfus=5717.492`，`Qfus=14.807`，`Pheat=386.131`，`Pwall=3.830`。
- 这说明当前这个单点求解在内部判据下是有效的，但按输出标签并未处于 `ignited` 状态；“单点有效”不等同于“扫描已确认工作窗”。
- POPCON 扫描信息显示 `xkey=Ti0`、`ykey=ni0`，`best` 矩阵非全零，说明离散扫描点中存在满足当前 `best` 判据的单元；同时 `n_invalid=0`，表示扫描结果里未标出无效点。
- 但当前 JSON 未给出 `x/y` 数组，且未提供 `nx/ny` 字段，因此必须说明：扫描网格证据不足，不能判断工作窗形状或敏感性趋势；也不能据此确认当前运行点是否落在被标记为 `best` 的单元内。

2. 关键指标解读
- 运行点功率侧：`Pfus=5717.492`，`Pn=4573.994`，`Pheat=386.131`；显式给出的辐射/辐射相关损失为 `Pbrem=142.126`、`Pcycl=26.212`、`P_line=0.0`。
- 约束时间侧：`use_tauE=1.0`，`tauE=1.0`，`tauE_used=1.0`，因此结果依赖固定约束时间假设；同时给出了与 ISS04 相关的对照量：`tau_ISS04=0.613`、`H_ISS04=1.632`、`PL_ISS04=1529.629`。
- 边界/裕度侧：输出含 `betaT=0.0794`、`beta_soft_limit=0.05`、`beta_o_limit=1.588`，以及密度相关量 `nbar=1.712e20`、`n_Sudo=2.866e20`、`nbar_o_Sudo=0.5973`；这些字段可作为后续扫描监控量，但仅凭当前 JSON 不能展开更强结论。
- 成分与辐射侧：`Zeff=1.867`，`fHe=0.04`，`fimp=0.01`，`Zimp=10`；在当前设置下，线辐射字段为 `P_line=0.0`，而韧致辐射和回旋辐射为非零。
- 几何侧：`Vp=1149.070`，`Sw=1593.493`，`Sp=1521.056`，`aspect_geom=10.0`，`geom_is_measured=0.0`；同时 `Vp_override=0.0`、`Sw_override=0.0`，`geom_volume_ratio=1.0`、`geom_wall_ratio=1.0`，说明当前结果未显示几何覆盖修正。
- POPCON 侧：按已给出的 8x8 `best` 矩阵直接计数，值为 1 的单元有 14 个；这只能说明“当前判据下存在被标记为 best 的离散单元”，不能据此描述最佳区位置、边界或趋势。

3. 风险与不确定性
- 最大的不确定性来自 `use_tauE=1.0`：当前 `Pfus`、`Qfus`、`Pwall`、`betaT` 等结果都依赖固定 `tauE=1.0` 的假设，若约束时间设定变化，结论可能同步变化。
- POPCON 证据不完整：虽然 `best` 矩阵非全零，但缺少 `x/y` 数组与 `nx/ny` 元数据，无法把 `best` 单元映射回具体 `Ti0/ni0` 数值，也无法判断工作窗形状、边界连通性或敏感性趋势。
- 几何输入的不确定性仍在：`geom_is_measured=0.0`，且未见几何覆盖量生效；这意味着当前 `Vp`、`Sw`、`Pwall` 等量对几何假设较敏感，但 JSON 不足以量化这种敏感性。
- 辐射与杂质设定可能显著影响功率平衡：当前 `fimp=0.01`、`Zimp=10`、`Zeff=1.867`，同时 `P_line=0.0`；若成分设定改变，`Pbrem`、`P_line`、进而 `Pfus/Qfus/Pwall` 都可能变化。
- 若把 `PL_ISS04` 视作阈值参照，也只能理解为与阈值模型的比较，不能据此写成保证进入或维持某种约束模式；当前 JSON 也未提供可支持更强模式判断的额外证据。
- `betaT`、`beta_soft_limit`、`beta_o_limit` 同时出现，但 JSON 未给出 `best` 判据的精确定义，因此不能仅凭单次输出判断这些约束在筛选中各自起了多大作用。

4. 下一步建议
1. 重新导出完整 POPCON 网格，至少补齐 `x`、`y`、`nx`、`ny` 和 `best_fraction`；监控指标：`xkey/ykey`、`n_invalid`、`best` 单元数、`best_fraction`、当前运行点在网格中的坐标映射。
2. 围绕当前点做约束时间敏感性扫描，分别测试固定 `tauE` 的多个取值，或改为不固定 `tauE` 的求解；监控指标：`valid`、`ignited`、`tauE_used`、`tau_ISS04`、`H_ISS04`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
3. 对 `Ti0` 与 `ni0` 做二维复扫，并与当前 `last_scan` 使用同一 `best` 判据；监控指标：`best` 矩阵、`n_invalid`、`Pfus`、`Qfus`、`Pwall`、`betaT`、`nbar_o_Sudo`、`ignited`。
4. 做成分/辐射敏感性扫描，优先改变 `fimp`、`Zimp`、`fHe`；监控指标：`Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Pfus`、`Qfus`、`Pwall`。
5. 做几何输入核对与替代计算：若后续有更可信几何，替换默认几何后复算；若暂无，则扫描 `Vp_override`、`Sw_override` 或相关几何尺寸参数；监控指标：`Vp`、`Sw`、`Sp`、`Pwall`、`aspect_geom`、`iota_geom`、`geom_is_measured`。
