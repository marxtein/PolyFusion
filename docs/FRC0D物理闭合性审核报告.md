# FRC 0D 物理闭合性审核报告

日期：2026-06-10  
对象：`polyfusion/configs/frc.py`、`polyfusion/configs/base.py`、`polyfusion/scan.py`，对照 `docs/25_FRC代码说明文档.md`、`docs/08_FRC0D物理调研.md`、`docs/09_FRC模型实现报告.md`  
结论级别：物理审稿式问题清单；本报告不修改源码

## 1. 总结结论

FRC 模块的主干物理是能跑通的，而且在几个非托卡马克位形里属于结构比较清楚的一类。它不是随便把托卡马克公式改名，而是用了 FRC 自己的闭合链条：

```text
x_s = r_s/r_w
  -> <beta> = 1 - x_s^2/2
  -> 解 tanh(K)/K = <beta>
  -> rigid-rotor 剖面 G1/G2/GB
  -> 压强平衡定峰值密度 n_m
  -> Pfus / Pbrem / Pcycl / Eth
  -> LSX 经验 tau_E
  -> Pheat / Qfus
```

所以它可以作为“FRC 0D 教学与参数初筛模型”。它能告诉我们：在 rigid-rotor 热等离子体、稳态功率平衡、LSX 约束定标这些假设下，FRC 的功率账和约束趋势会如何变化。

但它还不能作为真实 FRC 反应堆性能预测工具。关键原因是：真实 FRC 反应堆通常涉及形成与维持、旋转/倾斜/平移不稳定性、NBI 快离子、脉冲压缩、开端损失、直接能量转换和 alpha/高能离子动力学；当前模型只覆盖闭合场线区的热麦克斯韦 0D 功率账。

当前最重要的代码级风险是：**FRC 的物理域没有被保护**。例如 `x_s > 1` 时平均 beta 会变成负数，代码仍继续计算并可能给出 `Q > 1`；这不是一个“激进点”，而是已经离开 FRC 模型定义域的点。

## 2. 已经闭合的部分

### 2.1 rigid-rotor 剖面与平均 beta 定理

代码采用：

```text
n/n_m = sech^2(Ku)
B/B_e = tanh(Ku)
u = 2(r/r_s)^2 - 1
<beta> = 1 - x_s^2/2
tanh(K)/K = <beta>
```

这个结构是 FRC 模块最可信的部分。`test_frc_benchmark.py` 已验证：

- 多个 K 值下，`<sech^2>`、`<sech^4>`、`<|tanh|>` 的解析/数值平均一致。
- `tanh(K)/K = 1 - x_s^2/2` 在多个 `x_s` 点上闭合。
- 场零点处 `beta_null = 1`，符合 FRC 的定义性压强平衡。

这说明剖面和体平均的数学实现是自洽的。

### 2.2 压强平衡定密度

FRC 代码不是把密度和磁场完全独立输入，而是用：

```text
p_m = B_e^2/(2 mu0)
n_i,m = p_m / [(Ti + zeta Te) * keV_J]
```

这符合 FRC 场反位形的定义性关系：场零点附近等离子体压强由外部磁压支撑。因此 `B_e` 提高会直接提高可容纳密度，进而强烈提高聚变功率。现有 sanity 测试也验证了 `B_e` 上升时 `ni0` 与 `Pfus` 上升。

### 2.3 功率账闭合

FRC-DT 当前预设复算结果：

| 量 | 数值 |
|---|---:|
| `Pfus` | 487.815 MW |
| `Pn` | 390.252 MW |
| `Ptrans` | 4991.806 MW |
| `Pbrem` | 4.974 MW |
| `Pcycl` | 0.004 MW |
| `Pheat` | 4899.221 MW |
| `Qfus` | 0.0996 |
| `tau_E` | 3.642 ms |
| `<beta>` | 0.745 |
| `s_param` | 88.45 |

带电聚变功率约为 `Pfus - Pn = 97.563 MW`，损失约为 `Ptrans + Pbrem + Pcycl = 4996.784 MW`，所以：

```text
Pheat ≈ 4996.784 - 97.563 = 4899.221 MW
```

账本内部是闭合的。这里也能看出 FRC-DT 预设的核心问题不是“功率不够”，而是输运损失极大，导致 Q 只有约 0.1。

### 2.4 LSX 约束定标有量级锚点

代码用：

```text
tau_E = 3.2e-15 * elongation^0.5 * x_s^2 * r_s^2.1 * n_m^0.6
```

现有 benchmark 显示 LSX-like 点给出 `tau_E = 0.27 ms`，与文档记录的 LSX 实测 `0.3-0.5 ms` 同量级。这说明该定标作为实验尺度 FRC 的量级锚点是有意义的。

但它仍是经验式，不能自动推广到 Helion/TAE 类强束驱动或脉冲压缩反应堆。

## 3. 代码证据

### 3.1 现有测试结果

已运行：

```powershell
python polyfusion/tests/test_frc_sanity.py
python polyfusion/tests/test_frc_benchmark.py
```

结果：

```text
RESULT: ALL SANITY CHECKS PASS
RESULT: FRC BENCHMARK PASS
```

测试覆盖了输出有限正值、`B_e` 单调性、`r_s` 单调性、`x_s` 对 beta 的影响、`B_int < B_e`、D-He3 可运行、rigid-rotor 解析平均、trapped flux、LSX 量级等。

### 3.2 名义预设复算

| 预设 | `Pfus` MW | `Pheat` MW | `Qfus` | `tau_E` s | `<beta>` | `s_param` | 主要解读 |
---|---:|---:|---:|---:|---:|---:|---|
| FRC-DT | 487.8 | 4899.2 | 0.0996 | 3.64e-3 | 0.745 | 88.4 | 热稳态功率账可跑，但输运功率巨大 |
| Helion-DHe3 | 22.27 | 8259.5 | 0.00270 | 1.41e-3 | 0.719 | 56.2 | 代码可跑，但不含 Helion 的脉冲压缩和能量回收 |
| C-2W | 0.118 | 416.6 | 2.83e-4 | 1.43e-3 | 0.778 | 55.4 | 实验尺度点只可做趋势，不代表束驱动 FRC |

### 3.3 边界测试暴露的问题

#### P0：`x_s > 1` 仍给出结果

测试：

```python
run_case({"r_s": 1.0, "r_w": 0.7}, preset="FRC-DT", config="frc")
```

输出摘要：

```text
x_s = 1.4286
beta = -0.0204
Pfus = 87.71 MW
Pheat = 71.80 MW
Qfus = 1.22
```

这在物理上不成立。`x_s = r_s/r_w` 表示分离面半径与壁半径之比，FRC 闭合场线区必须在壁内，因此应有：

```text
0 < x_s < 1
```

当 `x_s > 1` 时，`<beta> = 1 - x_s^2/2` 甚至可以变成负数。当前代码仍解剖面、算密度、算 Q，这会制造假可行点。

#### P1：`f_shape` 超出几何范围仍线性放大体积和功率

测试：

```python
run_case({"f_shape": 1.5}, preset="FRC-DT", config="frc")
```

输出：

```text
Vp = 5.89 m^3
Pfus = 860.85 MW
Pheat = 8645.68 MW
Qfus = 0.0996
```

文档说 `f_shape` 应在椭圆 `2/3` 到跑道形 `1` 之间。当前 `1.5` 没有物理几何意义，却直接放大体积、功率和热储能。应校验：

```text
2/3 <= f_shape <= 1
```

#### P0：组分分数非法仍给结果

测试：

```python
run_case({"fHe": 0.7, "fimp": 0.4}, preset="FRC-DT", config="frc")
```

输出仍为 OK：

```text
Zeff = 8.0566
Pfus = 0.576 MW
Pheat = 3609.55 MW
```

此时 `f12 = 1 - fHe - fimp = -0.1`，燃料份额已经为负。FRC 的压强平衡又会用这个组分影响 `zeta` 和密度，因此会产生看似合理但物理错误的结果。这个问题是多位形共性问题。

#### P0：`Rw > 1` 会进入复数路径并导致异常

测试：

```python
run_case({"Rw": 1.2}, preset="FRC-DT", config="frc")
```

结果：

```text
TypeError: '>' not supported between instances of 'complex' and 'int'
```

原因是回旋辐射中有 `(1 - Rw)^0.5`。反射率必须限制在：

```text
0 <= Rw <= 1
```

#### P1：POPCON 可以画出未加稳定性/工程限制的“好点”

小扫描 `Ti x B_e` 中，FRC-DT 有一个 best point：

```text
Ti = 15 keV, B_e = 8 T:
Pfus = 13315 MW
Pheat = 7144 MW
Qfus = 1.86
```

这个点在 0D 功率账上 Q>1，但还没有检查：

- 形成与维持功率。
- n=2 rotational/tilt modes。
- open-field-line 端损和 scrape-off region。
- 高热流和能量回收。
- 脉冲压缩或束驱动的非热物理。

因此 best region 不能被读作“FRC 反应堆可行窗口”，只能读作“这个 0D 热模型里的功率账窗口”。

## 4. 关键物理缺口

### 4.1 FRC 的形成、维持与稳定性缺失

FRC 的可行性高度依赖形成和维持：

- theta-pinch 或 merging formation。
- 旋转不稳定性，尤其 n=2 rotational mode。
- tilt/shift/translation modes。
- separatrix 附近开场线损失。
- 中性束驱动、旋转剪切、端部稳定和反馈。

当前模块只描述已经存在的闭合场线区热等离子体，不判断这个 FRC 能否形成、能维持多久、是否会被不稳定性破坏。

### 4.2 Helion/TAE 类预设的真实物理不在模型里

Helion 类路线强调 D-He3、脉冲压缩、磁能/粒子能直接回收；TAE/C-2W 类 FRC 强烈依赖 NBI 快离子维持和稳定。当前模型：

- 温度是热麦克斯韦。
- 没有 beam-target 反应。
- 没有快离子压力。
- 没有压缩升温时间史。
- 没有能量回收效率。

所以 Helion-DHe3 或 C-2W 预设只能作为“热 FRC 等效参数点”，不能作为对应公司/实验路线的复现。

### 4.3 LSX 定标外推风险

LSX 定标有实验量级锚点，但它是小型 FRC 实验经验式。把它直接外推到反应堆尺度、高温高磁场、高功率束驱动时，风险很高。

报告中应持续标注：

```text
tau_E 是 LSX-family empirical scaling，不是第一性原理预测。
```

### 4.4 alpha、辐射、SOL 和壁负载处理不足

当前功率账默认带电聚变产物按 `fion * Pfus` 沉积。FRC 真实装置中：

- 高能离子轨道可能很大。
- separatrix 和 open-field region 会影响能量沉积。
- 端部或排气区域的热流工程没有闭合。
- D-He3 或 p-B11 的直接能量转换不在模型中。

这些会显著改变 `Pheat` 和 Q 的解释。

## 5. 文献对照

可作为审核依据的高可信来源：

- Steinhauer, "Review of field-reversed configurations", Physics of Plasmas 18, 070501 (2011). DOI: https://doi.org/10.1063/1.3613680  
  用于核对 FRC rigid-rotor、平均 beta、s 参数和 FRC 稳定性背景。
- Hoffman & Slough, LSX/FRC confinement scaling, Nuclear Fusion 33 (1993).  
  用于核对 LSX 量级和 `tau_N` 定标背景。
- US9082516B2, "Method and apparatus for forming and maintaining a field reversed configuration". https://patents.google.com/patent/US9082516B2/en  
  用于核对 FRC 工程路线中束驱动、维持和定标被如何使用。
- `docs/25_FRC代码说明文档.md`  
  明确声明模型边界：热麦克斯韦、闭合场线区功率平衡；不含旋转不稳定性、束驱动、压缩瞬态。

对照结论：代码主干符合 FRC 0D scoping model；但真实反应堆判断还缺稳定性、维持、束驱动、开端损失和能量回收。

## 6. 修正优先级

### P0：必须防止假物理结果

- 校验 `0 < r_s < r_w`，即 `0 < x_s < 1`。
- 校验 `2/3 <= f_shape <= 1`。
- 校验 `0 <= f1 <= 1`、`0 <= fHe`、`0 <= fimp`、`fHe + fimp <= 1`、`Zimp > 0`。
- 校验 `0 <= Rw <= 1`。
- 禁止 `beta <= 0`、`tau_E <= 0`、`Vp <= 0`、`ne0 <= 0` 的结果进入有效输出。

### P1：把 POPCON 的 best region 变成“物理域窗口”

建议 FRC best region 至少增加：

```text
0 < x_s < 1
s_param >= s_min
Pwall <= 用户阈值
```

其中 `s_param` 的阈值可先作为软提示，不要冒充硬边界。

### P2：如果要判断真实 FRC 路线

需要新增：

- NBI 快离子压力与 beam-target 反应。
- 脉冲压缩/膨胀循环能量账。
- 形成和维持功率。
- n=2/tilt/shift 稳定性判据。
- separatrix/open-field-line/SOL 损失。
- alpha 和高能离子轨道沉积。
- 直接能量转换效率。

## 7. 推荐对外表述

建议将 FRC 模块描述为：

> FRC 模块是基于 rigid-rotor 剖面、平均 beta 定理、压强平衡和 LSX 经验约束的 0D 热等离子体功率平衡模型。它适合教学、趋势扫描和参数初筛；不包含 FRC 形成维持、NBI 快离子、脉冲压缩、开场线 SOL、n=2/tilt 稳定性和直接能量转换，因此不应用于直接声称 Helion/TAE 类装置的真实性能。

## 8. 可复现实验命令

在 `E:\work\digitalfusion-release` 下运行：

```powershell
python polyfusion/tests/test_frc_sanity.py
python polyfusion/tests/test_frc_benchmark.py
```

边界问题复现：

```powershell
@'
from polyfusion.io import run_case

cases = [
    ("x_s_gt_1", {"r_s": 1.0, "r_w": 0.7}),
    ("f_shape_bad", {"f_shape": 1.5}),
    ("bad_composition", {"fHe": 0.7, "fimp": 0.4}),
    ("Rw_gt_1", {"Rw": 1.2}),
]

for name, extra in cases:
    try:
        r = run_case(extra, preset="FRC-DT", config="frc")
        print(name, r.get("errors") or {k: r["outputs"].get(k) for k in ["Pfus", "Pheat", "Qfus", "beta", "x_s", "Zeff"]})
    except Exception as e:
        print(name, type(e).__name__, e)
'@ | python -
```

## 9. 最终判断

FRC 模块的数学闭合度较好，适合作为“FRC 为什么靠压强平衡和 rigid-rotor 剖面闭合”的教学模型。现有 benchmark 能支撑“内部公式实现正确”和“LSX 量级锚点合理”。

但当前不能支撑真实 FRC 反应堆可行性判断。最紧急的问题不是再加复杂物理，而是先加输入域保护，避免 `x_s>1`、负燃料份额、非法几何和复数回旋辐射这类假点进入 POPCON 或单点输出。

## 10. 物理可靠性再审：能不能用于装置设计？

本节补充的是“公式闭合以后，物理上能信到什么程度”。结论要收紧：

```text
FRC 当前模型可以作为 0D 热平衡 scoping model；
不能作为 Helion/TAE/PFRC 类真实装置设计模型；
不能仅凭 Qfus 或 tau_E 扫描窗口判断 FRC 反应堆可行。
```

### 10.1 可靠的部分

- Rigid-rotor 剖面、平均 beta 定理、压强平衡定密度，是 FRC 0D 模型中物理根基最强的部分。它确实抓住了 FRC 的定义性事实：高 beta、反转场、密度由磁压和温度闭合。
- 聚变功率、轫致辐射、回旋辐射和热能账本作为“给定剖面后的体积分功率账”是合理的。
- `s_param` 作为诊断量有价值，因为 FRC 稳定性和输运确实强烈依赖离子轨道尺度。

### 10.2 不可靠的设计环节

最关键的不可靠点是：`tau_E` 采用 LSX 经验定标外推。LSX 是低温、短脉冲、实验尺度 FRC；反应堆尺度 FRC 往往依赖束驱动快离子、旋转、合并形成、脉冲压缩或直接能量回收。把 LSX 定标直接外推到 10-100 keV、强场、大尺寸、长寿命或脉冲燃烧区，物理可信度不足。

第二个问题是稳定性没有闭合。`s_param` 只是输出，不会进入 `valid` 判据。真实 FRC 的 n=2 rotational mode、tilt/shift、离子轨道稳定、快离子稳定化、端部开场线/SOL 都可能决定装置能否存在，而不只是功率账能否为正。

第三个问题是现代 FRC 路线不是纯热麦克斯韦等离子体。TAE 类路线依赖 NBI 形成/维持和快离子电流；Helion 类路线依赖脉冲合并、绝热压缩和磁能回收。当前模型没有快离子分布函数、束沉积、慢化、逃逸、脉冲能量回收，也没有把反应堆 Q 与墙插电效率区分开。

### 10.3 设计使用等级

| 用途 | 当前可信度 | 说明 |
|---|---:|---|
| 教学解释 FRC 压强平衡和高 beta | 高 | 核心公式抓住 FRC 定义 |
| 参数趋势初筛 | 中 | 只适合看 B、T、尺寸、密度趋势 |
| 热麦克斯韦稳态 FRC 概念比较 | 低-中 | 需要给 tau_E 外推范围和不确定性 |
| TAE/Helion 真实路线设计 | 低 | 缺 NBI/快离子/脉冲压缩/能量回收 |
| 反应堆可行性证明 | 不足 | 缺稳定性、形成维持和工程闭合 |

### 10.4 更可靠的 FRC 方案

建议把 FRC 模块拆成两个模式，而不是一个 `solve_frc()` 覆盖所有路线：

1. 热 0D FRC scoping mode：保留当前 rigid-rotor + 压强平衡 + 功率账；加 `valid_physics_flag`，限制 `0 < x_s < 1`、合理 elongation、`s_param`、`beta`、组分、`Rw`、剖面和功率非有限结果。`tau_E` 不给单值结论，而给 `tau_E_low/base/high` 三档不确定性。
2. 束驱动稳态 FRC mode：加入 NBI 功率、束能量、束捕获率、快离子压力份额、快离子电流、慢化时间、shine-through、charge-exchange 和快离子损失；稳定性至少加入 n=2/tilt proxy 和 `s_param` 有效域。
3. 脉冲压缩 FRC mode：把单点功率平衡换成循环能量账，显式计算压缩功、磁能回收、燃烧时间、重复频率、直接能量转换效率和脉冲平均功率。

最低可接受升级：

```text
FRC 设计判断 = 热功率账
             + tau_E 不确定性包络
             + 稳定性有效域
             + 形成/维持功率
             + 快离子或脉冲能量账
             + alpha/带电产物沉积与逃逸
```

如果暂时不实现高阶模型，POPCON 图至少要把 FRC 高 Q 区域标为“热 0D 可行窗口”，不能标为“装置可行窗口”。

新增参考锚点：

- Steinhauer FRC 综述，强调 FRC 是 little/no toroidal field、very high beta 的紧凑环，也明确综述重点是物理而不是完整工程反应堆：https://www.osti.gov/biblio/22043504 （DOI: 10.1063/1.3613680）
- TAE/C-2W NBI 形成与维持路线，说明现代 FRC 性能强依赖束驱动快离子而非纯热 0D：https://pmc.ncbi.nlm.nih.gov/articles/PMC11993635/
- Helion 公开技术路线，说明其关键是 D-He3、高 beta FRC、脉冲压缩和直接电能回收，当前稳态热功率账没有覆盖：https://www.helionenergy.com/technology
