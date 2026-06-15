# 仿星器几何精确积分（前后端一致的 Vp / Sw）设计

日期：2026-06-15　分支：`nearaxis-r2-and-sw`

## 目标
让仿星器的体积 $\Vp$、第一壁面积 $\Sw$ 由\textbf{前端实际画的那条边界}精确积分得到，实现前后端彻底一致；几何值作\textbf{默认估算}，`Vp_override`/`Sw_override` 变成\textbf{可选覆写}（有实测值的高级用户填，一般用户用几何估算）。

## 数学（已对解析圆环面验证，误差 0.004%）
边界 $R(\theta,\varphi),Z(\theta,\varphi)$。利用 $N_\mathrm{fp}$ 周期性，只积一个场周期再 $\times N_\mathrm{fp}$（与整圈积分差 ~1e-14）：

- 体积（圆柱坐标 $dV=R\,dR\,dZ\,d\varphi$，截面用 Green 定理 $\iint_S R\,dR\,dZ=\oint \tfrac12 R^2 dZ$）：
  $$\Vp = N_\mathrm{fp}\int_{0}^{2\pi/N_\mathrm{fp}}\!\!d\varphi\oint \tfrac12 R^2\,\partial_\theta Z\,d\theta.$$
- 壁面积（3-D 面元，$\vec P=(R\cos\varphi,R\sin\varphi,Z)$，取壁边界 = 边界沿外法向外扩 $g$）：
  $$\Sw = N_\mathrm{fp}\int_{0}^{2\pi/N_\mathrm{fp}}\!\!\!\int_0^{2\pi}\big|\partial_\theta\vec P\times\partial_\varphi\vec P\big|\,d\theta\,d\varphi.$$
  切向用\textbf{中心差分}（验证过比前向差分准）。

## 架构（单一路径，概念堆与真机统一）
1. **`boundary_metrics(boundary_fn, nfp, g, n_phi, n_theta) -> (Vp, Sw)`**（`nearaxis.py` 或 `stellarator.py` 模块级，numpy-only）。纯积分器，输入一个 `boundary_fn(phi)->(R[nθ], Z[nθ])`。
2. **边界提供者**：
   - 真机（有 `shape`）：DESC 双 Fourier 乘积基求值（已实现于 `_machine_boundary_outlines`，抽成可复用 `eval`）。
   - 概念堆（无 `shape`）：近轴 r2 边界——`solve_near_axis(order="r2")` 已给一个场周期的 $\varphi$ 网格上各点的一/二阶系数；在该网格上重建边界直接积分（天生一周期）。
3. **`stellarator_geometry_metrics`**：`Vp_geom`、`Sw_geom` 改由 `boundary_metrics` 给（精确积分），取代旧的 $\pi a^2 L_\mathrm{ax}$ / 周长$\times L_\mathrm{ax}$。`A_flux=\pi a^2` 保留（截面积锚，仅诊断/报告，辐射用 $a$ 本身）。
4. **`solve_stellarator`**：加 `shape=None` 形参；`shape` 加进 `_STELL_PARAMS` 白名单（`ConfigSpec.solve` 才会传入；`validate` 忽略未知键，安全）。
   - `Vp = Vp_override if >0 else Vp_geom`（精确积分）。
   - `Sw = Sw_override if >0 else Sw_geom`。
   - `geom_is_measured` 维持（两覆写都给=1）。

## 预设处置（用户拍板项，本设计取 (a)）
- **真机** W7-X/LHD/HSX/CFQS：\textbf{保留实测覆写}（30/128 等是已知真值）。新自定义配置/概念堆无覆写 → 用精确积分，前后端完全一致。
- 概念堆 HELIAS/NAE-QA：无覆写 → 由 $\pi a^2 L_\mathrm{ax}$ 改为 r2 边界精确积分（差 ~1–5%，诚实重定基准，不 fake）。

## 前端
`Vp^*`/`Sw^*` 字段标注改为「可选：实测覆写（留空=几何估算）」。结果面板已有 `geom_is_measured` 标注逻辑。

## 一致性结果
- 概念堆 / 自定义配置：前端边界 = 后端 $\Vp/\Sw$ 积分用的同一条边界 → \textbf{逐点一致}。
- 真机：保留实测覆写（权威），几何估算同时算出可对照；UI 标清「实测 vs 几何估算」。

## 测试（TDD）
1. `test_geometry_integral.py`：解析圆环面 $V=2\pi^2R_0a^2$、$S=4\pi^2R_0a$ 验证积分器（rtol 1e-3）；一周期$\times N_\mathrm{fp}$ == 整圈（1e-10）。
2. 一致性：每个无覆写预设/自定义配置，后端 `Vp` == 前端边界积分体积（同函数，恒等）。
3. 既有套件保持绿：rebaseline `test_stellarator_benchmark`/`sanity` 概念堆 Vp 数值；真机覆写不变。
4. `verification-before-completion`：全套 + golden。

## 不做（YAGNI）
- 不做完整 VMEC 体积（雅可比 $\sqrt g$ 积分）——边界 cartoon 的几何体积已足够 0-D。
- 不改真机实测覆写值。
- 不动 `A_flux=\pi a^2` 语义。
