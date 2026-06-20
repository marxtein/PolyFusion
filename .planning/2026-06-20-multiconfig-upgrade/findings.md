# 发现与调研 (2026-06-20)

## 代码结构侦察

### 平衡文件机制
- `app/server.py` L121-140：`/api/equilibria` 读 `equilibria/manifest.json`；`/equilibria/{tokamak|stellarator}/{name}` 服务二进制文件（路径白名单防穿越）。
- `manifest.json`：preset → {file, format, source, url, note, proxy?}。tokamak=geqdsk，stellarator=vmec(.nc)。
- 现有 tokamak：ITER.geqdsk, DIII-D.geqdsk（仅 2）。stellarator：W7-X.nc, precise-QA.nc, precise-QH.nc, QH-nfp3.nc（manifest 还含 NAE-QA、HELIAS 用 proxy 复用）。
- 来源线索：tokamak DIII-D 来自 OMAS samples (g145419.02100)；stellarator 全来自 simsopt tests/test_files 的 wout_*.nc（github raw 可 curl）。

### veqpy（平衡生成/导出库）
- 路径 `E:\work\velo\work\workbuddy\2026-06-19-09-44-20\veqpy-dev`
- `data/`：CHEASE.geqdsk, EFIT.geqdsk, SOLOVEV.geqdsk（真实 geqdsk，可直接拿）
- `tests/`：demo_veqpy.geqdsk, EFIT.geqdsk
- `tests/demo_export_geqdsk.py`：可导出 geqdsk → 能生成更多托卡马克平衡
- ⚠ 已弃用 repo，官方迁移到 github.com/zhangtakeda/veqpy

### index.html UI 锚点（行号）
- L441：几何输入 modebar `item('0','传统','legacy')` `item('1','Miller','Miller')` `item('2','平衡','equilibrium')` → T4 改 `传统`→`双椭圆`
- L1120：`传统解析几何（双椭圆示意）` 文案 → 改为 `双椭圆解析几何`
- L485-492：`importStellEquilibriumBuffer(buf,name,confirmFirst)`，`if(confirmFirst){...if(!confirm(summary))return false;}` → T3 去弹窗
- L1063-1064：`SHAPE_GROUPS` boundary/wall/flux 来自 `GEO()` → T5 颜色统一锚点（需找 GEO() 与各位形 trace 颜色）
- L1309+：`// Each config gets the profile...` 各位形剖面；L1330 dipole 绝热剖面注释 → T8
- L180：`最佳区判据 Operating Window`；best_window 在 polyfusion configs（python）

## 待联网调研（RESEARCH agent 填写）

### Q1 仿星器是否有 H 模？
- （待填）W7-AS 观测到 H 模；剖面带 edge pedestal? 是否给仿星器加 pedestal。

### Q2 mirror/FRC/dipole 最佳判别区间参数合理性
- （待填）各位形关键无量纲判据：mirror（镜比 R_m、β、Q）、FRC（s 参数、归一化、β~1）、dipole（临界压强梯度 / 绝热判据 d(pV^γ)）。

### Q3 H 模 pedestal 剖面合理形式
- tanh 台基 + 芯部峰化。托卡马克宽 Δ≈3-5%a，台顶≈0.3-0.6 芯部峰；仿星器仅弱密度台基、无 T 台基。已实现于 drawProfiles。

## T7 best_window 物理审查结论（research + 代码核对）
- **磁镜** beta≤0.6 合理（标注应为"元胞 β"；2XII-B 曾达~70%）。**缺**：镜比阈值 R_m≳5-10、最小-B 磁阱稳定、Pastukhov/Yushmanov 双极势、串联镜 Q≈5-10。这些多为输入量/未计算输出，best_window 只能门控输出场 → 仅文档化建议，不改默认门（避免破坏 POPCON）。
- **FRC** β≈1 是定义（⟨β⟩=1−0.5(r_s/r_w)²），任何 β 上限无意义 → 现状正确（le 为空）。s≥2 合理。**最大缺漏=倾斜稳定 s/E≲3-4** → 已实现：frc.py 新增输出 `s_over_E=s_param/elongation`，base.py 加 `optional_window le s_over_E≤4`（默认关，零风险），index.html PR 标签 's/E'。C-2W 实测 s/E≈14.8（确会触发倾斜门，物理合理）。
- **偶极** beta_in≤1 近乎无意义（偶极 β 局域、近环很高）。真正判据=可压缩交换稳定 δ(p·δV^γ)≤0，即 −dlnp/dlnV<γ=5/3（δV=∮dl/B∝R⁴）。需新增交换裕度输出（较大改动）→ 本轮文档化建议，保留 beta_in 默认门不动。

## T10 Bug 审查（pytest 全量 = 98 通过 / 2 失败 + presets-io ITER）
本轮我方改动**零**触碰 mirror.py / stellarator.py（git diff 证实）。以下 3 项均为**预存**（WIP 分支 nearaxis-r2-and-sw），非本次引入：
1. `test_mirror_geometry::test_solve_mirror_multi_zone` — solve_mirror() 不接受 `geometry` 关键字（签名漂移，疑似未完成的 multi_zone 特性）。
2. `test_stellarator_geometry_variants_sync::test_frontend_restores_...` — index.html 缺 `function normalizeStellBoundaryIota(`（测试引用了代码中不存在的函数）。
3. `test_presets_io` ITER Pfus golden=381.39 但实际 433.55 — 上个提交 "correct ITER params" 改了机器参数，golden 未同步。**不擅自改物理 golden**，留给用户确认。
本次我方引入并已修复：geometry_variants AUTHORITY 注册新预设；volume_rho 断言对齐（tokamak 也用体积 ρ）。
