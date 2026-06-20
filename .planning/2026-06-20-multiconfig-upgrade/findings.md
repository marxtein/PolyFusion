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
- （待填）tanh pedestal + 芯部抛物，pedestal 宽度/高度典型值。
