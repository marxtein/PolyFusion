1. 核心结论
- `config=mirror（磁镜 Magnetic Mirror）`，`preset=BEAM`。当前运行点给出的主结果是：`valid=1.0`、`ignited=1.0`、`Pfus=301.29513040513064`、`Qfus=1000.0`、`Pheat=-38.46408443258015`、`Pwall=11.547511432586502`。
- 以上 `valid/ignited` 只说明当前这一个运行点的求解结果；它不等同于参数空间扫描已经证明存在可接受工作窗。
- POPCON 扫描单独看：`xkey=Ti0`、`ykey=ni0`、`n_invalid=0`，且返回的 `best` 矩阵非全 0，说明在已返回的扫描判据下，部分网格点被标记为 `best`。
- 扫描网格证据不足，不能判断工作窗形状或敏感性趋势。原因是 `last_scan` 虽有 `best` 矩阵，但缺少 `x/y` 数组，且未给出 `nx/ny`；因此不能描述最佳区的位置、边界或随 `Ti0/ni0` 的变化趋势。

2. 关键指标解读
- 功率与损失：`Pfus=301.29513040513064`，`Pn=241.0361043241045`，`Ptrans=21.030859050955982`，`Pbrem=0.7625488061766331`，`Pcycl=0.0015337913133576452`，`P_line=0.0`，`Pwall=11.547511432586502`。就已给出的辐射项看，`Pbrem` 高于 `Pcycl`，而 `P_line=0.0`。
- 运行点状态：`valid=1.0` 且 `ignited=1.0`，同时 `Pheat` 为负值（`-38.46408443258015`）；这表明“点火标记”和“净加热项”需要按该模型自身定义联读，不能只抓住其中一个量。
- 约束与输运：`use_tauE=1.0`、`tauE=1.0`，输出中 `tau_E=1.0`，所以结果依赖固定约束时间假设。附带时间尺度还包括 `tauC_eff=1084.5398350837027`、`tau_Past=0.31270693620118806`、`tau_eq_ie=0.07545960680815618`。`tauE_scaling` 以及 `H98/H_ITPA20/H_ISS04` 未提供，无法做缩放律交叉核对。
- 边界与状态量：已提供 `beta=0.99`、`beta_avg=0.396`、`nbar=4.71238898038469e+20`、`ne0=6e+20`、`ni0=6e+20`、`coll_ratio=191.6130341802998`。但 `q/q95`、`nbar_o_nGw`、`nbar_o_Sudo` 未提供，因此不能用这些边界量复核当前点。
- 成分与辐射：`Zeff=1.0`、`fHe=0.0`、`fimp=0.0`、`Zimp=10`，对应输出里 `P_line=0.0`、`Pbrem=0.7625488061766331`、`Pcycl=0.0015337913133576452`。这里能确认的是本次输入/输出下的成分与辐射结果，不能外推到未扫描条件。
- 几何：已给出 `Vp=2.88398205599543`、`Sw=22.76083877525805`、`Sp=19.736508888662737`、`A_throat=0.0028274333882308154`。`geom_model` 未提供，因此不能判断几何是否采用简化模型。

3. 风险与不确定性
- `use_tauE=1.0` 是本报告最直接的不确定性来源之一；如果固定的 `tauE=1.0` 假设变化，`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat` 的结论都可能改变。
- `Qfus=1000.0` 与 `Qfus_raw=-7.8331548729111375` 在符号和量级上不一致；需要核对 `Qfus` 的定义、截断/封顶规则或后处理逻辑，否则对增益的解读存在明显歧义。
- `Pheat` 为负而 `ignited=1.0`，说明这些量的判定口径不应被默认视为同一件事；若不先澄清定义，容易误读当前运行点的能量收支。
- POPCON 只返回了 `best` 矩阵和 `n_invalid`，没有 `x/y` 数组与 `nx/ny`；因此即便知道 `best` 非全 0，也不能判断最佳区的物理坐标、边界宽度，或对 `Ti0/ni0` 的敏感性。
- `tauE_scaling`、`H98/H_ITPA20/H_ISS04`、`q/q95`、`nbar_o_nGw`、`nbar_o_Sudo`、`geom_model` 等关键补充信息缺失，限制了对约束、边界和几何假设的一致性复核。

4. 下一步建议
- 补齐并重做 `Ti0-ni0` 的 POPCON 扫描：输出 `x`/`y` 数组和 `nx/ny`，并在当前点 `Ti0=116.42857142857143`、`ni0=6e+20` 附近加密网格。需监控：`best`、`n_invalid`、`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。
- 做 `tauE` 假设敏感性验证：在其余参数不变下扫描 `tauE`，并对比固定 `use_tauE=1.0` 与非固定约束时间设定。需监控：`tau_E`、`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`tauC_eff`。
- 做功率收支核对任务：逐点复算并核对 `Qfus`、`Qfus_raw`、`Pheat`、`Ptrans`、`Pbrem`、`Pcycl`、`P_line` 的定义与后处理。需监控：`Qfus`、`Qfus_raw`、`Pheat`、`P_alpha_loss`、`P_end_flux`、`P_coll_flux`。
- 做成分/辐射参数扫描：扫描 `fimp`、`Zimp`、`fHe`，必要时联动 `Te0` 与 `ni0`。需监控：`Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Pwall`、`Pfus`、`valid`。
- 做磁镜几何与磁场参数扫描：扫描 `B_vac`、`B_expand`、`R_mirror`、`L_c`、`Rw`、`a_c`。需监控：`beta`、`beta_avg`、`nbar`、`tauC_eff`、`Pfus`、`Pwall`、`valid`。
