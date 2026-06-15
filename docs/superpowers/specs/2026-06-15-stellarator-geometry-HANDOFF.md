# 仿星器几何 — 交接文档（下一个聊天无缝衔接）

> 给下一个聊天的 Claude：本文件是完整上下文。你 COLD 启动，按本文件即可继续。
> 仓库 `E:\work\digitalfusion-release`，git 分支 **`nearaxis-r2-and-sw`**（未合并、未推送）。
> 先读：本文件 + `docs/superpowers/specs/2026-06-15-stellarator-geometry-integral-design.md`（积分设计）+ `docs/40_仿星器几何与功率账报告.tex`（几何怎么进功率）。

---

## 0. 环境 / 怎么跑

- Windows。Python = Microsoft Store Python 3.11。**bash 工具里路径用 `/e/work/...`，但 Windows Python 进程内路径要用 `E:/work/...`**（`open('/e/...')` 会失败）。
- 跑测试：`cd /e/work/digitalfusion-release && PYTHONPATH=/e/work/digitalfusion-release python polyfusion/tests/test_X.py`（exit 0 = pass）。`test_golden.py` 用 pytest：`python -m pytest polyfusion/tests/test_golden.py -q`。
- 起 app（前端验证）：用 preview MCP `preview_start name=polyfusion`（`.claude/launch.json` 已配，autoPort）。后端 `app/server.py`，`/api/run` `POST {config,preset|overrides}`。
- **已知坑**：preview 的 `preview_screenshot` 本环境经常超时、`clientWidth` 有时读到 0（渲染退化）。**前端验证改用 `preview_eval` 读 DOM/状态 + 离线 matplotlib 渲染**（`matplotlib` 可用，存 PNG 到 `E:/work/xxx.png` 再用 Read 看）。
- **scipy 装不上**（PyPI 镜像哈希不匹配）。pyQSC 不可直接 import。真机边界系数已离线取好存在预设里，无需再取。
- 纪律：superpowers TDD（先写失败测试）、systematic-debugging（先根因再修）、verification-before-completion（claim 前先跑）。每个改动单独 commit，消息结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。**不要 merge / push**。

---

## 1. 已完成（本轮 + 前几轮，分支共 23 commit）

仿星器几何系列。关键文件：
- `polyfusion/configs/stellarator.py` — 求解 + 几何（核心）。
- `polyfusion/nearaxis.py` — 近轴 r1/r2 求解器（对齐 pyQSC <2e-12）。
- `polyfusion/presets/stellarator.json` — 预设（含真机 `shape` 谐波 + `Vp_override`/`Sw_override`）。
- `polyfusion/configs/base.py` — ConfigSpec（`_STELL_PARAMS` 白名单、validate、solve 只传白名单参数给求解器）。
- `app/index.html` — 单文件前端（`buildParams` 渲染参数、`drawShape` 画截面、`applyModeLocks` 锁字段）。
- `docs/39_*.md`（系列报告）、`docs/40_*.tex`（几何→功率，已编译 PDF）。

做成的事（按 commit）：
- **二阶 r2 近轴 bean**（`cf6bef9` `dab8de7`）。
- **真机用真实 DESC 公开平衡边界谐波**（W7-X/HSX/ESTELL→CFQS/HELIOTRON→LHD，截断 |m|,|n|≤2，归一化）（`22d5421`）。预设 `shape={kind:"fourier",nfp,R:[[m,n,c]...],Z:[...],source}`。DESC 双 Fourier 乘积基：`R=R0+a·ΣRmn·A_m(θ)·B_n(φ)`，`A_m=cos(mθ)|sin(|m|θ)`，`B_n=cos(n·nfp·φ)|sin(|n|·nfp·φ)`。
- **LHD「只画一个」修复**（平面轴）、**壁外磁面修复**（质心缩放 `ec6558e`）。
- **Bug：改 Sw 几何突变** → Plotly scaleanchor+autorange 崩，改显式等比例范围（`5e29048`）。
- **Bug：嵌套面自相似 mini-bean** → ρ^|m| 谐波缩放（`de29d48`）。**← 用户说还不够好，见 Task 2。**
- **几何精确积分** `boundary_metrics`（环向体积 `∫½R²dZ`、壁面 `∬|∂θP×∂φP|`，一周期×N_fp，对圆环面验到 0.004%）（`8ebe0ee`）。
- **Vp/Sw 接积分**：`solve_stellarator(shape=...)`，有 shape → Vp/Sw = 边界精确积分；覆写可选（`ab75214`）。**概念堆仍用 πa²·L_ax，← Task 1 要改。**
- **高级模式开关**（普通只露 R0/A/N_fp/δh/η̄/g；高级露 rc/zs/Vp*/Sw*）（`72ab28e`）。**← 位置要改，见 Task 3。**
- **相位滑块**（后端 24 帧 `frames`；前端「φ slider」开关）（`117e642`）。

测试：29 个独立脚本全 exit 0 + golden 5 passed（**做完每个 task 都要全绿**）。

### 关键架构事实（务必记住）
- **两个几何角色**：前端截面视图（cartoon）vs 后端功率标量 `a=R0/A, Vp, Sw, L_ax, iota`。绑定锚：截面面积 = `A_flux=πa²`。
- 功率怎么进：`Pfus,Pbrem,Pcycl,Eth ∝ Vp`；`Pwall=(Pfus+Pheat)/Sw`；ISS04/Sudo 经 `a,R0,iota`。**形状不进功率。** 细节见 docs/40。
- 真机：功率用实测 `Vp_override/Sw_override`（保留），`shape` 只供显示 + 报告积分估算 `Vp_geom/Sw_geom`。
- `shape` 是后端专用参数：在 `_STELL_PARAMS` 白名单但 **无 META 条目**，`buildParams` 跳过无 META 的参数（别再让它崩）。
- `solve_stellarator` 有自洽递归（tauE=0、fT=0），递归调用都带 `shape=shape`。

---

## 2. 待办（用户本轮新要求，按优先级）

### Task 1 — 概念堆也上几何精确积分
**现状**：`solve_stellarator` 里 `if shape is not None: Vp_geom,Sw_geom = boundary_metrics(...)`，否则概念堆用 `geom["Vp_geom"]=πa²·L_ax`。
**要做**：概念堆（无 shape，近轴）也用 `boundary_metrics` 积分，实现彻底前后端一致。
**怎么做**：
- 写一个近轴 `boundary_fn(phi)->(R[nθ],Z[nθ])`：用 `solve_near_axis(rc,zs,nfp,etabar,order="r2")` 的结果，在 φ 处重建 r2 边界（axis + r·一阶·(n̂,b̂) + r²·二阶·(n̂,b̂,t̂)，r=a）。near-axis 结果是一周期 φ 网格上的数组（`na.phi`, `na.R0_arr`, `na.normal`, `na.binormal`, `na.tangent`, `na.X1c/Y1s/Y1c`, `na.second_order.*`）——对任意 φ 用周期插值（`np.interp`，网格末尾接首点）。
- **一致性要点**：积分用的边界要和前端 `section_outlines` 概念堆画的**同一条**。注意前端概念堆有「r2 wobble 显示限幅」（`_R2_DISPLAY_CAP`，见 `section_outlines` 里 `r2r[j]`）——决定积分用限幅后还是真 r2 边界。建议：用**真 r2 边界**（不限幅）算体积/面积（物理量），显示限幅只是 cartoon；并在前端把概念堆边界也改成真 r2（配合 Task 2 统一画法）。
- `stellarator_geometry_metrics` 或 `solve_stellarator`：概念堆也走 `boundary_metrics`。
- **会动概念堆 Vp（πa²L_ax → 积分，差 ~1-5%）→ 诚实重定基准**：`test_stellarator_benchmark.py`、`test_stellarator_sanity.py` 可能要更新数值。不许 fake。
- **TDD**：新测试 — 概念堆 `solve` 的 Vp == 其近轴边界 `boundary_metrics` 积分（同函数恒等）。

### Task 2 — 统一、好看的磁面画法（W7-X φ=0 磁面仍不对，磁面与边界重叠）
**症状**：W7-X φ=0 截面，嵌套磁面和边界**重叠**，「差点意思」。当前 ρ^|m| 缩放（`de29d48`）改善了内面圆化，但还不够。
**目标参考**（用户给的示意图，很好）：两个截面（φ=0 黑、φ=π/Nfp 红），嵌套磁面从边界平滑套到芯部、**互不重叠、间距均匀**，像 VMEC / NSE-global。
**根因调查方向**（systematic-debugging，先复现）：
- 复现：`section_outlines(**presets['W7-X'])`，画 `sections[0]`（φ=0）的所有 `surfaces` + 边界 + wall（离线 matplotlib 存 PNG 看）。量化：相邻 ρ 面的最小间距、是否有交叉、最外 ρ=0.85 面是否贴/穿边界。
- 可能根因：(a) ρ^|m| 缩放使外侧几面在 bean 凹口处挤在一起/贴边界；(b) 边界(ρ=1) 与 ρ=0.85 面间距 vs 内侧不均匀；(c) m=0 轴点 ≠ 视觉中心，导致偏心。
- **统一画法建议**（要设计一个好的）：考虑把嵌套面定义成「边界谐波 → 芯部椭圆」的平滑插值，高 m 内容随 ρ 衰减（near-axis 标度 m 阶 ~ ρ^m），且 **ρ 取非均匀**（外密内疏或反之）使视觉间距均匀，像参考图。可能需要：磁轴位置用真实芯部（不是面积质心也不是 m=0 谐波点，而是 r→0 极限）。
- **概念堆和真机用同一套画法**（统一），配合 Task 1 的真 r2 边界。
- **TDD/验证**：相邻磁面不相交、单调套叠、间距合理（无重叠）；离线渲染对比参考图。`test_stellarator_nesting.py`、`test_stellarator_wall_containment.py` 要保持/加强。

### Task 3 — 高级输入开关位置
**现状**：`buildParams`（`app/index.html`）里高级开关 `advbar` 用 `box.prepend(bar)` 放在**整个参数面板最顶部**。
**要做**：放到**几何参数组（g 壁间隙）下面**，点一下就地展开 rc/zs/Vp*/Sw*（就在它们本来的位置），更直观。
**怎么做**：`advbar` 不要 prepend 到 box 顶；插到「几何」组 `.pgrid` 之后（或几何组末尾）。高级字段 `.advfld` 已有（`.show-adv .advfld{display:flex}`）。把开关按钮渲染在几何组尾部，点击 toggle `ADVANCED` + `buildParams()`。纯前端，无 Python 测试；用 `preview_eval` 验证位置 + 展开。

---

## 3. 下一个聊天的启动指令（直接粘贴）

```
继续 E:\work\digitalfusion-release 的仿星器几何工作，git 分支 nearaxis-r2-and-sw（勿 merge/勿 push）。
先读 docs/superpowers/specs/2026-06-15-stellarator-geometry-HANDOFF.md（完整上下文 + 环境坑 + 三个待办的细节）。
按该文档 Task 1→2→3 顺序做，每步 TDD + 全测试绿 + commit。
重点 Task 2：设计一个统一、好看的嵌套磁面画法（当前 W7-X φ=0 磁面与边界重叠），参考 VMEC/NSE-global 那种平滑均匀套叠，概念堆和真机共用。
前端验证用 preview_eval + 离线 matplotlib（preview_screenshot 本环境会超时）。
```

---

## 4. 做完三个 task 后
- 更新 `docs/40_*.tex`（概念堆也积分、统一画法、高级开关位置）并重编译（`xelatex`，`/d/texlive/2023/bin/windows/xelatex`）。
- 全测试绿 + golden。
- 不 merge 不 push，留分支给用户 review。
