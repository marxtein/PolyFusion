"""Context-aware user manual generator for PolyFusion.

Produces a structured, language-aware manual for each magnetic configuration
based on the live ``ConfigSpec`` registry. The output is a plain dict so the
HTTP layer can either ship it as JSON (slide-out panel) or wrap it in a
standalone HTML page.
"""

from __future__ import annotations

from polyfusion.configs.base import REGISTRY, get

_OVERVIEW = {
    "tokamak": (
        "托卡马克是环向磁场约束位形。本模块用 0-D 功率平衡和约束标度快速筛查参数，重点看聚变功率、增益、比压、密度极限和第一壁负荷。",
        "The tokamak module screens parameters with a 0-D power balance and confinement scalings, focusing on fusion power, gain, beta, density limits and wall loading.",
    ),
    "mirror": (
        "磁镜是开端直线型位形，强端部磁场提供约束。本模块尤其需要同时看功率账和端部热流，因为端损失可能先成为限制。",
        "The mirror is an open-field-line linear concept. Read the power balance together with end heat flux, because end losses can be the limiting constraint.",
    ),
    "frc": (
        "FRC 是紧凑的场反位形，密度和压强由分离面几何与外部磁场共同约束。除功率账外，应重点看 s、s/E、磁通和电阻扩散诊断。",
        "The FRC is a compact field-reversed concept. Besides power balance, inspect s, s/E, trapped flux and resistive-diffusion diagnostics.",
    ),
    "dipole": (
        "偶极场位形由环形线圈产生磁场，当前模型用于概念初筛。它依赖人工能量约束时间，应重点检查内外 beta、U_ratio 和压强梯度。",
        "The dipole module is a concept-screening model driven by a prescribed energy confinement time; inspect inner/outer beta, U_ratio and pressure slope.",
    ),
    "stellarator": (
        "仿星器支持默认近轴、磁轴 Fourier、边界 Fourier 和外部平衡输入。功率公式只认标量几何，但边界形状会通过 Vp、Sw、Sp、a_vol 和 iota 影响结果。",
        "The stellarator supports simple near-axis, axis Fourier, boundary Fourier and imported equilibrium inputs. Shape affects the 0-D model through Vp, Sw, Sp, a_vol and iota.",
    ),
}


def _doc(
    zh: str,
    en: str | None = None,
    unit: str = "",
    effect: str = "",
    note: str = "",
    formula: str = "",
    reading: str = "",
    adjust: str = "",
) -> dict:
    return {
        "zh": zh,
        "en": en or zh,
        "unit": unit,
        "effect": effect,
        "note": note,
        "formula": formula,
        "reading": reading,
        "adjust": adjust,
    }


_PARAM_DOCS = {
    "R0": _doc("大半径", "major radius", "m", "设定主尺度，进入体积、约束标度、密度极限和几何显示。"),
    "a": _doc("小半径", "minor radius", "m", "设定仿星器截面尺度；体积等效半径 a_vol 会进入 Pcycl、ISS04 和 Sudo。"),
    "A": _doc("环径比 R0/a", "aspect ratio R0/a", "", "托卡马克中由 a=R0/A 得到小半径，影响体积、壁面积、q 和密度极限。"),
    "kappa": _doc("伸长比", "elongation", "", "改变截面面积、体积、q95、betaN 和工程稳定性诊断。"),
    "delta": _doc("三角度", "triangularity", "", "改变托卡马克边界成形、表面积和边缘安全因子估算。"),
    "g": _doc("第一壁间隙", "wall gap", "m", "把等离子体边界外扩到第一壁，主要改变 Sw 和 Pwall。"),
    "geom_model": _doc("托卡马克几何模型", "tokamak geometry model", "", "0=双椭圆，1=Miller，2=CF/真实平衡。"),
    "eq": _doc("托卡马克平衡对象", "tokamak equilibrium object", "object", "G-EQDSK 导入后用于真实几何、q95 和回旋 B^2.5 诊断。", "通常由导入按钮生成，不手动编辑。"),
    "Vp_override": _doc("体积覆写", "volume override", "m³", "大于 0 时替代几何积分体积。", "应与 shape/iota/Sw_override 来自同一平衡或实验数据。"),
    "Sw_override": _doc("第一壁面积覆写", "wall-area override", "m²", "大于 0 时替代几何壁面积，直接影响 Pwall。", "Pwall≈(Pfus+Pheat)/Sw。"),
    "BT0": _doc("轴上环向磁场", "toroidal field", "T", "进入 beta、安全因子、回旋辐射和托卡马克约束标度。"),
    "B0": _doc("代表磁场", "representative field", "T", "进入 beta、回旋辐射、ISS04/Sudo 或对应位形磁场尺度。"),
    "B_vac": _doc("磁镜真空中心磁场", "mirror vacuum central field", "T", "峰值 beta 会抗磁削弱实际中心场 B0。"),
    "B_e": _doc("FRC 外部磁场", "FRC external field", "T", "通过压力平衡决定 FRC 峰值压强和密度。"),
    "B_ring": _doc("偶极环磁场尺度", "dipole ring field scale", "T", "标定点偶极或有限环磁场强度。"),
    "Ip": _doc("等离子体电流", "plasma current", "MA", "进入 Greenwald 密度、q/q95、betaN 和 H 模约束标度。"),
    "ni0": _doc("中心离子密度", "central ion density", "m⁻³", "增大通常提高 Pfus，但也提高辐射、储能和密度极限压力。"),
    "n0": _doc("内边界峰值密度", "inner-boundary peak density", "m⁻³", "偶极场剖面归一化密度，进入储能、聚变和辐射。"),
    "Ti0": _doc("中心离子温度", "central ion temperature", "keV", "决定反应率和离子储能，是 POPCON 常用扫描轴。"),
    "Te0": _doc("中心电子温度", "central electron temperature", "keV", "决定轫致、回旋、电子储能和碰撞诊断。"),
    "Ti": _doc("离子温度", "ion temperature", "keV", "FRC 当前按均匀离子温度处理。"),
    "Te": _doc("电子温度", "electron temperature", "keV", "FRC 当前按均匀电子温度处理。"),
    "fT": _doc("Te0/Ti0 比", "Te0/Ti0 ratio", "", "为 0 时托卡马克/仿星器尝试自洽求电子温度。"),
    "Sn": _doc("密度峰化指数", "density peaking", "", "控制 n(r)=n0(1-rho²)^Sn，影响平均密度、聚变和辐射体积分。"),
    "ST": _doc("温度峰化指数", "temperature peaking", "", "控制 T(r)=T0(1-rho²)^ST，影响反应率、储能和辐射平均。"),
    "use_tauE": _doc("使用输入 τE", "use input tauE", "0/1", "为 1 时直接用 tauE；为 0 时使用经验标度或自洽损失闭合。"),
    "tauE": _doc("能量约束时间", "energy confinement time", "s", "控制输运损失，典型关系 Ptrans=Eth/tauE。"),
    "H_fac": _doc("目标约束增强因子", "target confinement factor", "", "预测模式下反解 tauE，使约束品质达到目标 H。"),
    "tauE_scaling": _doc("托卡马克约束标度", "tokamak confinement scaling", "string", "选择 ipb98、st 或 itpa20 预测闭合。"),
    "use_tauC": _doc("使用输入 τC", "use input tauC", "0/1", "为 1 时用人工回旋损失时间替代公式估算。"),
    "tauC": _doc("回旋损失时间", "cyclotron loss time", "s", "人工模式下近似 Pcycl=Eth_e/tauC。"),
    "Rw": _doc("壁反射率", "wall reflectivity", "", "越接近 1，净回旋/同步辐射损失越小。"),
    "cyclotron_B_nonuniform": _doc("非均匀磁场回旋修正", "nonuniform-B cyclotron correction", "0/1", "启用 B^2.5 矩修正；主要用于托卡马克和仿星器。"),
    "f_aux_e": _doc("电子加热份额", "electron auxiliary-heating fraction", "", "电子温度自洽求解时，指定外加加热进入电子通道的份额。"),
    "icase": _doc("聚变反应类型", "fusion reaction type", "int", "决定反应率函数、总释能、中子份额和带电产物份额。"),
    "f1": _doc("第一燃料份额", "first fuel fraction", "", "双组分燃料中第一种离子的份额；D-T 可理解为 D 份额。"),
    "fHe": _doc("氦灰份额", "helium ash fraction", "", "稀释燃料并改变电子密度、Zeff 和辐射。"),
    "fimp": _doc("杂质份额", "impurity fraction", "", "进入 Zeff、轫致和线辐射；需满足 fHe+fimp<1。"),
    "Zimp": _doc("杂质电荷数", "impurity charge", "", "与 fimp 共同决定电子密度和有效电荷。"),
    "imp_name": _doc("杂质物种", "impurity species", "string", "给定且 fimp>0 时启用 Mavrin 线辐射近似。"),
    "fsig": _doc("反应率修正因子", "reactivity multiplier", "", "Pfus 近似正比于 fsig，常用于保守系数或灵敏度扫描。"),
    "a_c": _doc("磁镜中央半径", "mirror central radius", "m", "决定中央段体积、喉口面积和回旋辐射尺度。"),
    "L_c": _doc("磁镜中央长度", "mirror central length", "m", "决定体积、端损失路径和壁面积。"),
    "R_mirror": _doc("真空镜比", "vacuum mirror ratio", "", "结合 beta 得到有效镜比 R_mc，影响端损失约束。"),
    "f_throat": _doc("喉段长度份额", "throat-length fraction", "", "单侧喉段长度占中央段长度比例，影响端区体积和表面积。"),
    "f_alpha": _doc("带电产物沉积份额", "charged-product deposition", "", "磁镜中为空时按损失锥上界估计；给 1 表示理想沉积。"),
    "B_expand": _doc("扩张器磁场稀释比", "expander field dilution", "", "把喉口端损失热流折算到收集器热流。"),
    "phi_i_over_Te": _doc("离子势垒/Te", "ion barrier over Te", "", "为空时用 Te0*ln(R_mirror) 估计离子约束电势。"),
    "lnLambda": _doc("库仑对数", "Coulomb logarithm", "", "进入碰撞、均化和 Pastukhov 端损失估算。"),
    "geom_weighted": _doc("FRC 几何加权", "FRC geometry weighting", "0/1", "用有限长度分离面体积权重重算刚性转子平均因子。"),
    "sep_model": _doc("FRC 分离面模型", "FRC separatrix model", "string", "superellipse 为默认；ma_xie 使用 Ma-Xie 幂律分离面。"),
    "m": _doc("Ma-Xie 形状指数", "Ma-Xie shape exponent", "", "m=2 为椭圆，越大越接近直边/跑道形。"),
    "r_s": _doc("FRC 分离面半径", "FRC separatrix radius", "m", "必须小于壁半径 r_w，影响体积、磁通和稳定性参数。"),
    "l_s": _doc("FRC 分离面长度", "FRC separatrix length", "m", "影响体积、伸长比和壁面积。"),
    "r_w": _doc("FRC 壁半径", "FRC wall radius", "m", "用于 x_s=r_s/r_w 和壁面积，壁应在分离面外。"),
    "f_shape": _doc("FRC 体积形状因子", "FRC volume shape factor", "", "控制 Vp≈f_shape*pi*r_s²*l_s；Ma-Xie 中为 m/(m+1)。"),
    "r_ring": _doc("偶极环半径", "dipole ring radius", "m", "设定内边界和磁场标定长度。"),
    "R_p": _doc("偶极外边界半径", "dipole plasma outer radius", "m", "必须大于 L_in，决定壳层体积和壁面积。"),
    "L_in_fac": _doc("偶极内边界因子", "dipole inner-boundary factor", "", "L_in=L_in_fac*r_ring，表示线圈/SOL 清空区。"),
    "ring_model": _doc("偶极磁场模型", "dipole field model", "0/1", "0 为点偶极近似，1 为有限电流环几何。"),
    "N_fp": _doc("场周期数", "field periods", "", "仿星器环向周期数，影响轴长、相位切面和几何周期。"),
    "delta_h": _doc("轴螺旋偏移", "helical axis excursion", "m", "默认近轴磁轴的螺旋幅度，要求 0<=delta_h<R0。"),
    "etabar": _doc("近轴形参 η̄", "near-axis eta-bar", "1/m", "Garren-Boozer 近轴成形参数，决定截面伸长与近轴几何。", "不能为 0；真机边界模式下多为显示/诊断参数。"),
    "iota": _doc("旋转变换", "rotational transform", "", "仿星器中进入 ISS04 约束，约以 iota^0.41 影响 tau_ISS04。", "边界 Fourier/真机模式下应来自同一平衡或实测数据。"),
    "f_ren": _doc("ISS04 归一化因子", "ISS04 renormalisation", "", "装置归一化因子，随 ISS04 经验约束时间线性变化。"),
    "rc": _doc("磁轴 R Fourier", "magnetic-axis R Fourier", "array", "近轴/pyQSC 路径的磁轴 R 余弦系数。", "这是磁轴 Fourier，不是边界面 Fourier。"),
    "zs": _doc("磁轴 Z Fourier", "magnetic-axis Z Fourier", "array", "近轴/pyQSC 路径的磁轴 Z 正弦系数。"),
    "shape": _doc("边界 Fourier 几何", "boundary Fourier geometry", "object", "真机或 DESC/VMEC 路径的边界面 R/Z Fourier 三元组。", "shape 通过边界积分得到的 Vp/Sw/Sp 影响结果。"),
    "geometry_variants": _doc("几何变体缓存", "geometry variant cache", "object", "前端保存不同仿星器几何输入模式的权威数据。", "通常不手动编辑。"),
    "equilibrium": _doc("VMEC/DESC 平衡", "VMEC/DESC equilibrium", "object", "外部平衡导入对象，携带边界、iota 和几何诊断。", "应保持 shape、iota、体积来自同一平衡。"),
}

_PARAM_GROUP = {
    "R0": "geo", "a": "geo", "A": "geo", "kappa": "geo", "delta": "geo",
    "g": "geo", "geom_model": "geo", "eq": "geo", "Vp_override": "geo",
    "Sw_override": "geo", "a_c": "geo", "L_c": "geo", "f_throat": "geo",
    "geom_weighted": "geo", "sep_model": "geo", "m": "geo", "r_s": "geo",
    "l_s": "geo", "r_w": "geo", "f_shape": "geo", "r_ring": "geo",
    "R_p": "geo", "L_in_fac": "geo", "ring_model": "geo", "N_fp": "geo",
    "delta_h": "geo", "etabar": "geo", "iota": "geo",
    "BT0": "field", "B0": "field", "B_vac": "field", "B_e": "field",
    "B_ring": "field", "Ip": "field", "R_mirror": "field",
    "ni0": "plasma", "n0": "plasma", "Ti0": "plasma", "Te0": "plasma",
    "Ti": "plasma", "Te": "plasma", "fT": "plasma",
    "Sn": "prof", "ST": "prof",
    "icase": "fuel", "f1": "fuel", "fHe": "fuel", "fimp": "fuel",
    "Zimp": "fuel", "imp_name": "fuel", "fsig": "fuel", "f_alpha": "fuel",
    "use_tauE": "conf", "tauE": "conf", "H_fac": "conf", "tauE_scaling": "conf",
    "use_tauC": "conf", "tauC": "conf", "Rw": "conf", "cyclotron_B_nonuniform": "conf",
    "f_aux_e": "conf", "B_expand": "conf", "phi_i_over_Te": "conf",
    "lnLambda": "conf", "f_ren": "conf",
    "rc": "advanced", "zs": "advanced", "shape": "advanced",
    "geometry_variants": "advanced", "equilibrium": "advanced",
}

_GROUPS = [
    ("geo", "几何 Geometry", "Geometry"),
    ("field", "场·电流 Field & Current", "Field & Current"),
    ("plasma", "等离子体 Plasma", "Plasma"),
    ("prof", "剖面 Profiles", "Profiles"),
    ("fuel", "燃料·杂质 Fuel & Impurity", "Fuel & Impurity"),
    ("conf", "约束·修正 Confinement", "Confinement"),
    ("advanced", "高级几何对象 Advanced Geometry", "Advanced Geometry"),
    ("other", "其它 Other", "Other"),
]

_OUTPUT_DOCS = {
    "Pfus": _doc("聚变总功率", "fusion power", "MW", "由体积分 n1*n2*<σv>*E 得到。", reading="越高越好，但要同时检查 Pheat、Pwall、beta 和密度极限。", adjust="若太低，通常提高 Ti0、ni0、体积或磁场；若壁负荷过高，降低密度或增大 Sw。"),
    "Pn": _doc("中子功率", "neutron power", "MW", "聚变功率中非带电产物份额。", reading="D-T 下通常是主要输出功率；高中子功率意味着屏蔽和材料压力增加。", adjust="降低 Pfus 或更换反应类型可降低中子功率。"),
    "Pheat": _doc("所需外加加热", "required auxiliary heating", "MW", "维持该点还需补充的净加热。", reading="接近 0 或为负表示接近点火；过高表示该工作点难以维持。", adjust="提高 tauE/H_fac、降低辐射损失、提高 Ti0 到反应率更优区。"),
    "Qfus": _doc("截断聚变增益", "capped fusion gain", "", "展示用 Pfus/Pheat，上限截断到 1000。", reading="Q>1 表示聚变功率超过外加加热；显示 1000/∞ 多半是点火截断。", adjust="降低 Pheat 或提高 Pfus；异常大时同时查看 Qfus_raw 和 ignited。"),
    "Qfus_raw": _doc("未截断聚变增益", "raw fusion gain", "", "原始 Pfus/Pheat。", reading="负值通常表示 Pheat<=0；极大值表示非常接近功率平衡分母为 0。", adjust="结合 Pheat 和 ignited 解读，不要单独比较极大值。"),
    "ignited": _doc("点火标志", "ignition flag", "0/1", "Pheat<=0 时为 1。", reading="1 表示 0-D 功率账自持，不等同于工程可建。", adjust="若始终为 0，可提高 tauE/H_fac、降低辐射或寻找更优 Ti0/ni0。"),
    "Pbrem": _doc("轫致辐射", "bremsstrahlung", "MW", "主要随 ne²、sqrt(Te) 和 Zeff 增大。", reading="过高会吞噬聚变加热，常见于密度或杂质过高。", adjust="降低 ni0/fimp/Zimp，或降低过高 Te0/fT。"),
    "Pcycl": _doc("回旋/同步辐射", "cyclotron radiation", "MW", "随电子温度、磁场和尺寸因子变化。", reading="高磁场、高 Te、小尺寸时可能很大。", adjust="提高 Rw、降低 Te0/fT，或调整几何尺寸/非均匀磁场设置。"),
    "P_line": _doc("杂质线辐射", "line radiation", "MW", "由 imp_name 和 fimp 启用。", reading="非零时说明杂质线辐射参与损失；过高通常表示杂质设定过激。", adjust="降低 fimp，选择更轻杂质或关闭 imp_name 做对照。"),
    "Ptrans": _doc("输运损失功率", "transport loss", "MW", "常见闭合为 Eth/tau_E。", reading="过高说明约束时间短或储能过大。", adjust="提高 tauE/H_fac，或降低温度/密度到更可约束区。"),
    "Pwall": _doc("第一壁平均负荷", "first-wall loading", "MW/m²", "通常按 (Pfus+Pheat)/Sw 估计。", reading="工程上常希望低于用户设定阈值，如 5–10 MW/m²；过高意味着壁面积不足或功率过大。", adjust="增大 Sw/g/装置尺寸，降低 Pfus 或 Pheat，避开过高密度温度区。"),
    "Eth": _doc("总热储能", "thermal stored energy", "MJ", "约为 1.5*∫(niTi+neTe)dV。", reading="过高会推高输运损失和控制难度；过低可能 Pfus 不足。", adjust="调低体积、密度或温度；或提高 tauE 来承受更高储能。"),
    "Vp": _doc("等离子体体积", "plasma volume", "m³", "进入聚变、辐射和储能体积分。", reading="体积越大，功率和损失常一起放大。", adjust="需要更高 Pfus 可增大体积；壁负荷过高时同时增大 Sw。"),
    "Sw": _doc("第一壁面积", "first-wall area", "m²", "主要用于 Pwall。", reading="Sw 太小会放大壁负荷；实测覆写不一致会误导 Pwall。", adjust="增大 g/装置尺寸，或确保 Sw_override 来源可靠。"),
    "Sp": _doc("等离子体表面积", "plasma surface area", "m²", "边界/分离面表面积诊断。"),
    "ne0": _doc("中心/峰值电子密度", "central electron density", "m⁻³", "由离子组分和准中性得到。", reading="过高会增加辐射并触碰密度极限。", adjust="降低 ni0、fHe、fimp 或提高密度极限相关几何/磁场。"),
    "nbar": _doc("平均或线平均密度", "average/line density", "m⁻³", "定义随位形略有差异。", reading="应结合 nbar_o_nGw 或 nbar_o_Sudo 判断是否过激。", adjust="降低 ni0/n0，或调整装置尺寸、磁场和加热功率。"),
    "Zeff": _doc("有效电荷", "effective charge", "", "进入轫致和碰撞诊断。", reading="接近 1 较干净；过高通常表示杂质负担大。", adjust="降低 fimp/Zimp 或选择更低 Z 杂质。"),
    "M": _doc("平均燃料质量数", "mean fuel mass", "", "影响热速度、回旋半径和快离子沉积。"),
    "Ecrit": _doc("快产物临界能量", "fast-product critical energy", "keV"),
    "f_fast_ion": _doc("快产物离子沉积份额", "fast-product ion deposition", ""),
    "tau_eq_ie": _doc("离子-电子弛豫时间", "ion-electron equilibration time", "s"),
    "P_ei": _doc("离子到电子能量交换", "ion-electron energy exchange", "MW"),
    "tauC_eff": _doc("回旋等效损失时间", "effective cyclotron loss time", "s", reading="越短表示回旋损失越强。", adjust="提高 Rw 或降低 Te0/B。"),
    "valid": _doc("数值有效标志", "numeric validity flag", "0/1", reading="0 表示至少一个数值输出非有限，应视为无效点。", adjust="检查输入是否越界、几何是否退化、tauE 或体积是否异常。"),
    "H98": _doc("IPB98 增强因子", "IPB98 enhancement", "", reading="约 1 表示达到 IPB98 经验水平；远高于 1 表示约束假设激进。", adjust="若要求过高，降低功率目标或改用更保守 tauE/H_fac。"),
    "HST": _doc("球形托卡马克增强因子", "ST enhancement", ""),
    "H_ISS04": _doc("ISS04 增强因子", "ISS04 enhancement", "", "仿星器实际 tauE 与 ISS04 预测 tau 的比值。", reading="约 1–1.4 较接近经验增强；过高表示约束假设激进。", adjust="降低 H_fac/tauE 目标，或调整 a_vol、B0、iota、密度。"),
    "betaN": _doc("归一化 beta", "normalised beta", "", reading="过高表示托卡马克稳定性压力大。", adjust="降低压力/密度/温度，或提高磁场和电流裕度。"),
    "betaT": _doc("环向/平均 beta", "toroidal beta", "", reading="过高表示压强相对磁压过强。", adjust="降低 ni0/Ti0/Te0 或提高磁场。"),
    "nbar_o_nGw": _doc("Greenwald 密度比", "Greenwald fraction", "", reading="接近或超过 1 表示托卡马克密度激进。", adjust="降低 ni0，或提高 Ip/改变尺寸。"),
    "nbar_o_Sudo": _doc("Sudo 密度比", "Sudo fraction", "", reading="接近或超过 1 表示仿星器密度接近经验极限。", adjust="降低 ni0，或提高 B0/PL、调整 a_vol/R0。"),
    "n_Sudo": _doc("Sudo 密度极限", "Sudo density limit", "m⁻³"),
    "q": _doc("柱形安全因子", "cylindrical q", "", reading="过低表示 kink 等稳定性风险。", adjust="提高 BT0/R0 或降低 Ip/改变截面。"),
    "q95": _doc("工程边缘安全因子", "engineering q95", "", reading="通常希望高于约 3；过低说明边缘安全因子不足。", adjust="提高 BT0、降低 Ip，或增加成形裕度。"),
    "tau_E": _doc("实际约束时间", "actual confinement time", "s", reading="越长输运损失越低，但假设也可能更激进。", adjust="若 Ptrans 高，提高 tauE/H_fac；若结果过乐观，使用更保守 tauE。"),
    "tauE_used": _doc("实际使用 tauE", "used tauE", "s"),
    "taue_mode": _doc("tauE 模式", "tauE mode", ""),
    "Te0": _doc("实际电子温度", "used electron temperature", "keV"),
    "fT_used": _doc("实际 Te0/Ti0", "used Te0/Ti0", ""),
    "te_mode": _doc("电子温度模式", "electron-temperature mode", ""),
    "te_resid": _doc("电子通道残差", "electron-channel residual", "MW", reading="自洽模式下越接近 0 越好。", adjust="若残差大，避免 fT=0 或调整 tauE/Rw/加热份额。"),
    "ntau": _doc("密度约束乘积", "density-confinement product", "m⁻³ s", reading="越高越接近 Lawson 类要求，但也可能意味着密度/约束假设激进。"),
    "P_end_flux": _doc("磁镜喉口热流", "mirror throat heat flux", "MW/m²", reading="过高说明端损失热流可能不可承受。", adjust="提高 R_mirror/B_expand 或降低功率密度。"),
    "P_coll_flux": _doc("收集器热流", "collector heat flux", "MW/m²", reading="扩张器后的收集器负荷，仍过高则工程压力大。", adjust="增大 B_expand 或降低端损失功率。"),
    "Past_domain": _doc("Pastukhov 适用域", "Pastukhov validity flag", "0/1", reading="0 表示 Pastukhov 公式处于回退或边界处理。", adjust="检查 R_mirror、phi_i_over_Te、lnLambda 和温度密度。"),
    "R_mc": _doc("beta 修正镜比", "beta-corrected mirror ratio", ""),
    "A_throat": _doc("喉口面积", "throat area", "m²"),
    "K_rr": _doc("刚性转子参数", "rigid-rotor parameter", ""),
    "G1": _doc("FRC 一阶平均因子", "FRC first moment", ""),
    "G2": _doc("FRC 二阶平均因子", "FRC second moment", ""),
    "GB25": _doc("FRC B^2.5 矩", "FRC B^2.5 moment", ""),
    "x_s": _doc("分离面/壁半径比", "separatrix-wall radius ratio", "", reading="应小于 1 且留出壁裕度。", adjust="降低 r_s 或增大 r_w。"),
    "s_param": _doc("FRC 尺度参数", "FRC scale parameter", "", reading="过低通常表示动理学尺度不够。", adjust="增大 r_s/B_e 或降低温度以减小回旋半径。"),
    "s_over_E": _doc("倾斜稳定性诊断", "tilt-stability diagnostic", "", reading="经验上小于约 3–4 更有利于动理学稳定。", adjust="增大伸长比 E=l_s/(2r_s)，或降低 s_param。"),
    "flux_p": _doc("陷获极向磁通", "trapped poloidal flux", "Wb", reading="越高代表磁通保持能力更强。", adjust="增大 B_e、r_s 或优化分离面尺寸。"),
    "tau_eta": _doc("电阻扩散时间", "resistive diffusion time", "s"),
    "tauN_o_taueta": _doc("约束/扩散时间比", "confinement-to-diffusion ratio", "", reading="过大表示能量约束比磁通扩散慢很多，磁通保持可能成问题。"),
    "beta_in": _doc("偶极内边界 beta", "dipole inner beta", "", reading="过高表示压强相对磁场过强。", adjust="降低 n0/Ti0/Te0 或提高 B_ring。"),
    "beta_out": _doc("偶极外边界 beta", "dipole outer beta", ""),
    "U_ratio": _doc("磁通管比体积比", "flux-tube volume ratio", "", reading="过高表示外侧体积膨胀很强。", adjust="调整 R_p/L_in_fac/r_ring。"),
    "p_slope": _doc("压强 L 梯度", "pressure L-gradient", "", reading="用于偶极互换稳定性粗诊断。"),
    "L_in": _doc("偶极内边界半径", "dipole inner radius", "m"),
    "iota": _doc("实际旋转变换", "used rotational transform", "", "仿星器中进入 ISS04，约以 0.41 次幂影响 tau_ISS04。", reading="真机模式下应来自同一平衡/实验数据；为 0 或过小会使 ISS04 不可靠。", adjust="给定权威 iota，或切换到自洽近轴几何。"),
    "iota_geom": _doc("几何旋转变换诊断", "geometric iota diagnostic", "", reading="近轴路径可作为自洽值；真机边界无可靠 iota 时应以外部平衡为准。"),
    "L_ax": _doc("磁轴长度", "magnetic-axis length", "m"),
    "kappa_eff": _doc("有效截面伸长", "effective elongation", "", reading="真机模式下常是近轴估计，主要作几何诊断。"),
    "elong_max": _doc("最大截面伸长", "maximum elongation", ""),
    "tau_ISS04": _doc("ISS04 约束时间", "ISS04 confinement time", "s"),
    "PL_ISS04": _doc("ISS04 损失功率", "ISS04 loss power", "MW"),
    "A_flux": _doc("有效磁通截面积", "effective flux area", "m²", "A_flux=Vp/L_ax。"),
    "a_vol": _doc("体积等效小半径", "volume-equivalent minor radius", "m", "a_vol=sqrt(Vp/(2*pi²*R0))，进入 Pcycl、ISS04 和 Sudo。"),
    "Vp_geom": _doc("几何积分体积", "geometric volume", "m³", "覆盖前的边界积分体积诊断。", reading="与 Vp 差异大时说明使用了实测覆写或几何截断近似。"),
    "Sp_geom": _doc("几何等离子体面积", "geometric plasma area", "m²"),
    "Sw_geom": _doc("几何壁面积", "geometric wall area", "m²", "覆盖前的边界积分壁面积诊断。"),
    "geom_volume_ratio": _doc("体积几何比", "geometry volume ratio", "", reading="偏离 1 表示几何积分和实际用于功率账的体积不一致。", adjust="检查 Vp_override 与 shape 是否来自同一数据源。"),
    "geom_wall_ratio": _doc("壁面积几何比", "geometry wall-area ratio", "", reading="偏离 1 表示 Sw 覆写或几何壁面积估计差异明显。", adjust="检查 Sw_override、g 和边界几何。"),
    "geom_is_measured": _doc("实测几何标志", "measured-geometry flag", "0/1"),
    "nbar_geom": _doc("几何线平均密度", "geometric line density", "m⁻³"),
    "nbar_geom_o_nbar": _doc("几何/经验线平均比", "geometric-to-model line-density ratio", "", reading="偏离 1 表示几何线平均与功率账经验平均差异明显。"),
    "cyclotron_B25_factor": _doc("B^2.5 回旋修正因子", "B^2.5 cyclotron factor", "", reading="大于 1 表示非均匀磁场提高回旋损失估计。", adjust="关闭非均匀修正做对照，或检查平衡/边界磁场输入。"),
}

_CONFIG_OUTPUT_KEYS = {
    "tokamak": ["Pfus", "Qfus", "Qfus_raw", "Pheat", "ignited", "Pwall", "Pbrem", "Pcycl", "P_line", "Ptrans", "H98", "HST", "betaN", "betaT", "nbar_o_nGw", "q", "q95", "tauE_used", "Te0", "te_mode", "te_resid", "Vp", "Sw", "Vp_geom", "Sw_geom", "geom_volume_ratio", "geom_wall_ratio", "cyclotron_B25_factor", "valid"],
    "mirror": ["Pfus", "Qfus", "Qfus_raw", "Pheat", "ignited", "Pwall", "P_end_flux", "P_coll_flux", "Pbrem", "Pcycl", "Ptrans", "tau_E", "ntau", "Past_domain", "R_mc", "A_throat", "Zeff", "tauC_eff", "valid"],
    "frc": ["Pfus", "Qfus", "Qfus_raw", "Pheat", "ignited", "Pwall", "Pbrem", "Pcycl", "Ptrans", "tau_E", "ntau", "K_rr", "G1", "G2", "GB25", "x_s", "s_param", "s_over_E", "flux_p", "tau_eta", "tauN_o_taueta", "valid"],
    "dipole": ["Pfus", "Qfus", "Qfus_raw", "Pheat", "ignited", "Pwall", "Pbrem", "Pcycl", "Ptrans", "tau_E", "ntau", "beta_in", "beta_out", "U_ratio", "p_slope", "L_in", "Vp", "Sw", "valid"],
    "stellarator": ["Pfus", "Qfus", "Qfus_raw", "Pheat", "ignited", "Pwall", "Pbrem", "Pcycl", "P_line", "Ptrans", "H_ISS04", "tau_ISS04", "PL_ISS04", "betaT", "beta_o_limit", "nbar_o_Sudo", "n_Sudo", "iota", "iota_geom", "A_flux", "a_vol", "Vp", "Sw", "Sp", "Vp_geom", "Sw_geom", "Sp_geom", "geom_volume_ratio", "geom_wall_ratio", "geom_is_measured", "nbar_geom_o_nbar", "cyclotron_B25_factor", "valid"],
}

_OUTPUT_GROUPS = [
    ("power", "功率与增益 Power & Gain", "Power & Gain"),
    ("conf", "约束与运行边界 Confinement", "Confinement"),
    ("limit", "稳定性与极限 Stability", "Stability & Limits"),
    ("geo", "几何诊断 Geometry", "Geometry Diagnostics"),
    ("plasma", "等离子体与组分 Plasma", "Plasma & Species"),
]

_OUTPUT_GROUP = {k: "power" for k in ("Pfus", "Pn", "Pheat", "Qfus", "Qfus_raw", "ignited", "Pbrem", "Pcycl", "P_line", "Ptrans", "Pwall")}
_OUTPUT_GROUP.update({k: "conf" for k in ("H98", "HST", "H_ISS04", "tau_E", "tauE_used", "tau_ISS04", "PL_ISS04", "tauC_eff", "ntau", "te_mode", "te_resid", "Te0")})
_OUTPUT_GROUP.update({k: "limit" for k in ("betaN", "betaT", "beta_in", "beta_out", "beta_o_limit", "nbar_o_nGw", "nbar_o_Sudo", "n_Sudo", "q", "q95", "x_s", "s_param", "s_over_E", "Past_domain")})
_OUTPUT_GROUP.update({k: "geo" for k in ("Vp", "Sp", "Sw", "Vp_geom", "Sp_geom", "Sw_geom", "geom_volume_ratio", "geom_wall_ratio", "geom_is_measured", "A_flux", "a_vol", "iota", "iota_geom", "L_ax", "kappa_eff", "elong_max", "R_mc", "A_throat", "K_rr", "G1", "G2", "GB25", "flux_p", "U_ratio", "p_slope", "L_in", "cyclotron_B25_factor")})
_OUTPUT_GROUP.update({k: "plasma" for k in ("ne0", "nbar", "nbar_geom", "nbar_geom_o_nbar", "Zeff", "M")})

_CONFIG_DEPENDENCIES = {
    "tokamak": [
        "Vp、剖面平均因子和反应率共同决定 Pfus；Ip/BT0/R0/A 进入 q、q95、Greenwald 与约束标度。",
        "geom_model=2 或导入真实平衡时，几何诊断和回旋 B^2.5 修正更接近真实磁面。",
    ],
    "mirror": [
        "use_tauE=0 时端损失模型决定 tau_E 和 Ptrans；R_mirror、phi_i_over_Te、lnLambda 控制端损失。",
        "除 Pwall 外，还要看 P_end_flux 与 P_coll_flux，因为开端位形的端部热流可能先成为约束。",
    ],
    "frc": [
        "B_e 通过压力平衡决定密度和 beta；r_s、r_w、l_s 决定体积、x_s、s_param 与磁通。",
        "s_over_E、flux_p、tau_eta/tau_E 是判断 FRC 几何与稳定性是否合理的关键诊断。",
    ],
    "dipole": [
        "r_ring、R_p、L_in_fac 定义偶极壳层；Ptrans 当前使用人工 tauE。",
        "U_ratio、p_slope、beta_in/beta_out 用来判断偶极剖面和高 beta 是否过激。",
    ],
    "stellarator": [
        "功率公式没有显式 shape 项；shape 通过边界积分得到的 Vp、Sw、Sp 间接进入功率账。",
        "Vp 线性进入 Pfus、Pbrem、Pcycl 和 Eth；Sw 主要进入 Pwall=(Pfus+Pheat)/Sw。",
        "a_vol=sqrt(Vp/(2*pi²*R0)) 进入 Pcycl、ISS04 和 Sudo；iota 以约 0.41 次幂进入 ISS04。",
        "真实机器模式下，shape、iota、Vp_override、Sw_override 应来自同一平衡或同一套实验/设计数据。",
    ],
}


def _lang_idx(lang: str) -> int:
    return 0 if (lang or "zh").lower().startswith("zh") else 1


def _local_doc(raw: dict, lang: str, key: str) -> dict:
    li = _lang_idx(lang)
    desc = raw.get("zh") if li == 0 else raw.get("en", raw.get("zh"))
    out = {"k": key, "desc": desc or key, "unit": raw.get("unit", "")}
    for field in ("effect", "note", "formula", "reading", "adjust"):
        if raw.get(field):
            out[field] = raw[field]
    return out


def _fallback_doc(key: str) -> dict:
    return _doc(key, key, "", "当前接口字段；建议结合源码或详细参考手册核对。")


def _param_row(key: str, lang: str) -> dict:
    return _local_doc(_PARAM_DOCS.get(key, _fallback_doc(key)), lang, key)


def _output_row(key: str, lang: str) -> dict:
    return _local_doc(_OUTPUT_DOCS.get(key, _fallback_doc(key)), lang, key)


def _group_rows(keys: list[str], groups: list[tuple[str, str, str]], group_map: dict, lang: str, row_fn) -> list[dict]:
    grouped = []
    for group_key, zh_title, en_title in groups:
        rows = [row_fn(k, lang) for k in keys if group_map.get(k, "other") == group_key]
        if rows:
            grouped.append({"id": group_key, "title": zh_title if _lang_idx(lang) == 0 else en_title, "items": rows})
    return grouped


def generate_manual(config_name: str, lang: str = "zh") -> dict:
    """Build the manual dict for a configuration.

    Raises ``KeyError`` if the config is not registered.
    """
    spec = get(config_name)
    li = _lang_idx(lang)
    overview = _OVERVIEW.get(config_name, (config_name, config_name))[li]

    param_groups = _group_rows(
        spec.params,
        _GROUPS,
        {p: _PARAM_GROUP.get(p, "other") for p in spec.params},
        lang,
        _param_row,
    )
    output_keys = _CONFIG_OUTPUT_KEYS.get(config_name, [])
    output_groups = _group_rows(output_keys, _OUTPUT_GROUPS, _OUTPUT_GROUP, lang, _output_row)

    presets = list(spec.presets.keys()) if hasattr(spec.presets, "keys") else list(spec.presets)

    workflow = (
        [
            "选择位形与预设机型",
            "阅读输入参数提示，确认几何、等离子体、燃料和约束参数语义",
            "编辑左栏参数，右栏工作点会即时重算",
            "用输出参数解释判断异常：先看 Pfus/Q/Pheat/Pwall，再看位形专属极限",
            "设置最佳区判据，选择 X/Y 扫描轴并运行 POPCON",
            "导出 JSON/CSV/PNG 或仿真报告，保留输入与输出诊断链条",
        ]
        if li == 0
        else [
            "Pick a configuration and preset machine",
            "Read input hints and confirm geometry, plasma, fuel and confinement meanings",
            "Edit the left panel; the operating point recomputes live",
            "Use output explanations to diagnose anomalies: start from Pfus/Q/Pheat/Pwall",
            "Set operating-window thresholds, choose X/Y axes and run POPCON",
            "Export JSON/CSV/PNG or a simulation report with the diagnostic chain",
        ]
    )

    notes = (
        [
            "非托卡马克位形为定性模型，绝对值待标定，请勿直接用于工程设计。",
            "回旋辐射公式为 0-D 工程近似，非完整辐射输运。",
            "0-D 初筛：参数通过不等于可建堆，但不通过通常说明该方向需要调整。",
        ]
        if li == 0
        else [
            "Non-tokamak configurations are qualitative models pending calibration.",
            "Cyclotron formulas are 0-D engineering approximations, not full radiation transport.",
            "0-D screening: passing does not prove viability, but failing usually demands redesign.",
        ]
    )

    config_notes = _CONFIG_DEPENDENCIES.get(config_name, [])
    title = f"PolyFusion · {spec.label} {('使用说明' if li == 0 else 'Manual')}"
    param_docs = {p: _param_row(p, lang) for p in spec.params}
    output_docs = {k: _output_row(k, lang) for k in output_keys}
    return {
        "title": title,
        "config": config_name,
        "config_label": spec.label,
        "lang": "zh" if li == 0 else "en",
        "param_docs": param_docs,
        "output_docs": output_docs,
        "sections": [
            {"id": "overview", "title": "位形概述" if li == 0 else "Overview", "paragraph": overview},
            {"id": "presets", "title": "内置预设" if li == 0 else "Built-in Presets", "items": [{"k": p, "desc": p, "unit": ""} for p in presets]},
            {"id": "params", "title": "输入参数" if li == 0 else "Input Parameters", "groups": param_groups},
            {"id": "outputs", "title": "输出参数解读" if li == 0 else "Output Interpretation", "groups": output_groups},
            {"id": "dependencies", "title": "参数如何影响结果" if li == 0 else "How Inputs Affect Outputs", "steps": config_notes},
            {"id": "workflow", "title": "操作流程" if li == 0 else "Workflow", "steps": workflow},
            {"id": "notes", "title": "注意事项" if li == 0 else "Notes", "steps": notes},
        ],
    }


def list_supported_configs() -> list[str]:
    return sorted(REGISTRY.keys())
