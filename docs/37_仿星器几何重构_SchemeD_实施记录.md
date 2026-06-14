# 仿星器几何重构 Scheme D — 实施记录

> 分支 `scheme-d-stellarator`。计划见 `docs/superpowers/plans/2026-06-14-stellarator-scheme-d.md`。
> 起因：审核发现 legacy 旋转椭圆模式下 `kappa_s` 在近轴模式完全失效、`delta_h` 在 legacy 不驱动 iota（见 `仿星器0D物理闭合性审核报告.md`）。

## 决策（用户确认）
- **D1**：近轴 Garren-Boozer 为唯一解析几何；真机（W7-X 准等动、LHD heliotron）用**实测 iota 覆盖**兜底。
- **删 `kappa_s`**：`etabar` 为唯一塑形旋钮，拉长比（`kappa_eff`/`elong_max`）变为**派生输出**。
- **重定基线**：概念堆用近轴计算值；真机锚真机（实测 `iota` + `Vp_override`）。
- 新增**自定义轴** `rc`/`zs` 与 **`Vp_override`/`Sw_override`** 实测覆盖。

## 几何解析优先级（`solve_stellarator`）
```
轴 = (rc,zs) 若给定，否则 [R0,delta_h]/[0,-delta_h]
近轴 = solve_near_axis(轴, N_fp, etabar)        # etabar 必填 !=0
iota = iota 覆盖 if >0 else 近轴 iota_geom
Vp   = Vp_override if >0 else πa²·L_ax
Sw   = Sw_override if >0 else 周长·L_ax
iota_geom 始终输出；iota<=1e-6 报错（ISS04 需 iota>0）
```
关键：体积不依赖近轴收敛（L_ax 对平面轴=2πR0），LHD（delta_h=0）喂 iota 覆盖即可。

## 代码改动（提交于 `scheme-d-stellarator`）
| 提交 | 内容 |
|---|---|
| `eef02f3` | solve_stellarator 单一近轴路径；删 kappa_s/legacy；加 iota/Vp/Sw 覆盖 + 自定义轴；新增 test_stellarator_param_activity（参数活性门禁） |
| `568d083` | section_outlines 近轴截面 + 壁面轮廓（边界沿外法线偏移 g）；删 fourier-display 卡通 |
| `60b025a` | base.py ConfigSpec 参数（etabar/rc/zs/Vp_override/Sw_override）；预设重定基线；HELIAS delta_h=0.32→iota_geom 0.822 |
| `364bec2` | 测试改写：sanity/validation/benchmark 迁到近轴 API；新增 override+自定义轴测试；删 legacy 公式断言（保留全部真实物理锚点） |
| `f714bb8` | UI：etabar/覆盖/自定义轴面板 + 壁面图层；删 kappa_s |

## 预设（重定基线后）
- **概念堆（纯近轴，无覆盖）**：HELIAS（N_fp=5, delta_h=0.32, etabar=0.05 → iota_geom 0.82, Q 4.55）、NAE-QA（N_fp=3, etabar=0.05 → iota 0.418）。
- **真机（实测 iota + Vp_override）**：W7-X(iota=0.88, Vp=30)、LHD(iota=0.40, Vp=30, 平面轴)、HSX(iota=1.05, Vp=0.4)、CFQS(iota=0.45, Vp=1)。Vp 为近似值，待文献核实。

## 验证
- 全部仿星器测试通过：param_activity、sanity、overrides、validation、benchmark、nearaxis_benchmark。
- benchmark 删除的只是已删除 legacy 公式的断言；保留全部真实物理锚点（退化到托卡马克机器精度、W7-X ISS04 H=1.11 用实测 iota=0.88、NAE-QA 近轴 iota_geom=0.4183 <1e-9）；未放松任何容差。
- 浏览器实测：5 位形 shape 图统一图层；仿星器壁面图层绘制；自定义轴 rc/zs 端到端生效（iota_geom 2.726→1.302）；无 console 报错。
- **无回归**：mirror_sanity / physics_p2 / golden 三处失败在本次工作前的检查点 `d03bebd` 即已存在（前一会话未提交状态 + golden 依赖未安装的 pytest），与 Scheme D 无关。

## 已知边界
- 一阶近轴截面恒为椭圆，**没有**真机的 bean/月牙高阶形变（需二阶近轴 pyQSC r2，列为未来阶段）。
- 三处预存失败（mirror Q 截断 sanity、mirror Te0=0 自洽、golden 需 pytest）非本次引入，建议单独处理。
