# 核心结论
`config=dipole`（`config_label=偶极场 Dipole`），`preset=Dipole-DD`。当前运行点结果为：`valid=1.0`、`ignited=0.0`、`Pfus=11.103`、`Qfus=1.420`、`Pheat=7.817`、`Pwall=0.01506`。

就这个运行点本身看，0-D 计算返回“有效”（`valid=1`），但未标记为点火（`ignited=0`）。这只说明当前参数点被模型接受，不等于 POPCON 扫描已经找到了满足准则的工作窗。

POPCON 扫描方面，`xkey=Ti0`、`ykey=n0`，`n_invalid=0`，但 `best` 矩阵全为 0，所以**当前准则下未找到最佳区**。同时，输入里没有 `x/y` 扫描数组，`nx/ny` 也未提供，因此**扫描网格证据不足，不能判断工作窗形状或敏感性趋势**。

# 关键指标解读
运行点方面，聚变输出 `Pfus=11.103`，对应 `Qfus=1.420`；加热功率字段为 `Pheat=7.817`。损失项里，`Pbrem=3.211`、`Pcycl=0.0340`、`P_line=0.0`，已给出的辐射项中以轫致辐射为主；另有 `Ptrans=11.950`。壁负荷 `Pwall=0.01506`，并给出了几何量 `Sw=1256.637`、`Vp=1890.304`。

约束与假设方面，`tau_E=5.0` 且 `use_tauE=1.0`，所以**结果依赖固定约束时间假设**。本次 JSON 没有提供 `H98/H_ITPA20/H_ISS04` 或 `tauE_scaling` 的替代结果，因此这里不能比较不同约束时间模型。

成分与辐射方面，`Zeff=1.0`、`fHe=0.0`、`fimp=0.0`、`Zimp=10`；这意味着当前结果对应的是这组给定成分参数下的 0-D 输出。密度相关字段给出了 `nbar=3.603e19` 和 `n0=9.143e20`，但没有 `nbar_o_nGw` 或 `nbar_o_Sudo`，因此不能进一步做相应边界比值解读。

POPCON 扫描方面，当前只知道扫描轴是 `Ti0` 与 `n0`，且 `n_invalid=0`，说明已评估点没有被标成无效；但 `best` 全零表示没有点被标成“最佳”。这里必须和运行点分开看：**运行点有效，不代表扫描中存在最佳区**。

# 风险与不确定性
首先，`use_tauE=1` 使结果对固定 `tau_E=5.0` 的设定敏感；如果约束时间改动，`valid`、`ignited`、`Pfus`、`Qfus` 和损失平衡都可能变化。

其次，虽然给出了 `best` 矩阵，但缺少 `x/y` 数组以及 `nx/ny`，所以只能确认“当前准则下未找到最佳区”，不能判断最佳区是否只是出现在未采样位置，也不能判断扫描边界、形状或趋势。

再次，本次 JSON 没有提供 `q/q95`、`betaN/betaT/betap`、`LH_ratio`、`geom_model` 等字段，因此相关约束、L-H 阈值比较、几何简化程度都不能从这份数据里展开判断。

# 下一步建议
1. 重新执行一次 `Ti0-n0` 的 POPCON 扫描，并导出完整 `x`、`y`、`nx`、`ny` 和逐点判据结果。重点监控：`best`、`n_invalid`、`valid`、`ignited`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。

2. 针对 `tau_E=5.0` 做约束时间敏感性扫描；如果工具支持，也可对比固定 `tau_E` 与 `tauE_scaling` 方案。重点监控：`valid`、`ignited`、`Pfus`、`Qfus`、`Ptrans`、`Pbrem`、`Pcycl`、`P_line`。

3. 做成分与辐射参数扫描，至少覆盖 `fimp`、`Zimp`、`fHe`、`Zeff` 的扰动。重点监控：`Pbrem`、`P_line`、`Pcycl`、`Pfus`、`Qfus`、`Pwall`、`nbar`。

4. 做运行点邻域复核，在当前 `Ti0=86.43`、`n0=9.143e20` 附近加密网格。重点监控：`valid` 是否翻转、`ignited` 是否变化，以及 `best` 是否仍全零。
