"""Context-aware user manual generator for PolyFusion.

Produces a structured, language-aware manual for each magnetic configuration
based on the live ``ConfigSpec`` registry. The output is a plain dict so the
HTTP layer can either ship it as JSON (slide-out panel) or wrap it in a
standalone HTML page.

Phase 1 is a rule-based generator (no LLM dependency) so the manual works
fully offline.
"""

from __future__ import annotations


from polyfusion.configs.base import REGISTRY, get

# Per-config one-paragraph overview, bilingual.
_OVERVIEW = {
    "tokamak": (
        "托卡马克是环向磁场约束位形，是目前最成熟的聚变路线。本模块基于 0-D "
        "功率平衡与约束标度律进行参数初筛，给出聚变功率、增益、比压与第一壁负荷等指标。",
        "The tokamak is a toroidal magnetic-confinement configuration and the most "
        "mature fusion route. This module runs a 0-D power balance with confinement "
        "scaling laws to screen parameters, reporting fusion power, gain, beta and "
        "first-wall loading.",
    ),
    "mirror": (
        "磁镜位形通过两端强磁场约束带电粒子，是直线型开源位形。本模块使用快工程"
        "公式估计聚变功率与回旋辐射损失，适合概念阶段的参数筛查。",
        "The magnetic mirror confines charged particles with strong end fields; it is "
        "an open-field-line linear concept. This module estimates fusion power and "
        "cyclotron losses with fast engineering formulas, suited for concept screening.",
    ),
    "frc": (
        "场反位形（FRC）是等离子体自洽产生反向环向场的紧凑位形。本模块给出分离面"
        "几何、粒子约束与功率平衡的 0-D 估计。",
        "The field-reversed configuration (FRC) is a compact concept where the plasma "
        "self-generates a reversed toroidal field. This module gives 0-D estimates of "
        "separatrix geometry, particle confinement and power balance.",
    ),
    "dipole": (
        "偶极场位形由悬浮超导环产生的偶极场约束等离子体，具有自然的 beta 高、剖面"
        "自组织特性。本模块给出点偶极/有限环两种几何下的 0-D 估计。",
        "The levitated dipole confines plasma in the dipole field of a floating "
        "superconducting coil, with naturally high beta and self-organised profiles. "
        "This module gives 0-D estimates for both point-dipole and finite-ring geometry.",
    ),
    "stellarator": (
        "仿星器通过复杂三维线圈产生环向旋转变换，可实现稳态运行。本模块支持近轴、"
        "边界 Fourier 与 VMEC/DESC 平衡三种几何输入，给出 0-D 参数筛查。",
        "The stellarator uses complex 3D coils to produce rotational transform, enabling "
        "steady-state operation. This module supports simple near-axis, boundary Fourier "
        "and VMEC/DESC equilibrium geometry inputs for 0-D parameter screening.",
    ),
}

# Param quick-reference, keyed by parameter name. Each entry is
# (zh_short, en_short, unit). Only the most user-facing params are listed;
# others fall back to the raw key.
_PARAM_DOCS = {
    "R0": ("大半径", "major radius", "m"),
    "a": ("小半径", "minor radius", "m"),
    "A": ("环径比 R0/a", "aspect ratio R0/a", ""),
    "kappa": ("拉长比", "elongation", ""),
    "delta": ("三角形变", "triangularity", ""),
    "BT0": ("环向磁场", "toroidal field", "T"),
    "B0": ("磁场", "field", "T"),
    "Ip": ("等离子体电流", "plasma current", "MA"),
    "ni0": ("中心离子密度", "central ion density", "m⁻³"),
    "Ti0": ("离子温度", "ion temperature", "keV"),
    "Te0": ("电子温度", "electron temperature", "keV"),
    "fT": ("Te0/Ti0 比", "Te0/Ti0 ratio", ""),
    "tauE": ("能量约束时间", "energy confinement time", "s"),
    "H_fac": ("目标 H 因子", "target H factor", ""),
    "tauE_scaling": ("约束标度律", "confinement scaling law", ""),
    "Sn": ("密度峰化", "density peaking", ""),
    "ST": ("温度峰化", "temperature peaking", ""),
    "f1": ("燃料配比", "fuel mix", ""),
    "fHe": ("氦灰份额", "helium ash fraction", ""),
    "fimp": ("杂质份额", "impurity fraction", ""),
    "Zimp": ("杂质电荷", "impurity charge", ""),
    "icase": ("反应类型 (1=D-T…)", "reaction type (1=D-T…)", ""),
    "Rw": ("壁反射率", "wall reflectivity", ""),
    "g": ("壁间隙", "wall gap", "m"),
    "use_tauE": ("使用输入 τE", "use input tauE", ""),
    "use_tauC": ("使用输入 τC", "use input tauC", ""),
    "tauC": ("回旋辐射损失时间", "cyclotron loss time", "s"),
    "cyclotron_B_nonuniform": (
        "回旋辐射磁场不均匀修正",
        "cyclotron B nonuniformity",
        "",
    ),
    "N_fp": ("场周期数", "field periods", ""),
    "etabar": ("近轴形参 η̄", "near-axis eta-bar", "1/m"),
    "delta_h": ("轴螺旋偏移", "helical axis excursion", "m"),
    "geom_model": ("几何模型", "geometry model", ""),
    "f_aux_e": ("电子加热份额", "electron heating fraction", ""),
}

# Param -> group, for organising the reference table.
_PARAM_GROUP = {
    "R0": "geo",
    "a": "geo",
    "A": "geo",
    "kappa": "geo",
    "delta": "geo",
    "g": "geo",
    "N_fp": "geo",
    "etabar": "geo",
    "delta_h": "geo",
    "geom_model": "geo",
    "BT0": "field",
    "B0": "field",
    "Ip": "field",
    "ni0": "plasma",
    "Ti0": "plasma",
    "Te0": "plasma",
    "fT": "plasma",
    "Sn": "prof",
    "ST": "prof",
    "f1": "fuel",
    "fHe": "fuel",
    "fimp": "fuel",
    "Zimp": "fuel",
    "icase": "fuel",
    "tauE": "conf",
    "H_fac": "conf",
    "tauE_scaling": "conf",
    "use_tauE": "conf",
    "Rw": "conf",
    "use_tauC": "conf",
    "tauC": "conf",
    "cyclotron_B_nonuniform": "conf",
    "f_aux_e": "conf",
}

_GROUPS = [
    ("geo", "几何 Geometry", "Geometry"),
    ("field", "场·电流 Field & Current", "Field & Current"),
    ("plasma", "等离子体 Plasma", "Plasma"),
    ("prof", "剖面 Profiles", "Profiles"),
    ("fuel", "燃料·杂质 Fuel & Impurity", "Fuel & Impurity"),
    ("conf", "约束·修正 Confinement", "Confinement"),
]

# Key output metrics worth calling out in the manual.
_KEY_OUTPUTS = [
    ("Pfus", "聚变功率", "Fusion power", "MW"),
    ("Qfus", "能量增益", "Energy gain", ""),
    ("Pheat", "辅助加热功率", "Auxiliary heating power", "MW"),
    ("Pbrem", "轫致辐射", "Bremsstrahlung", "MW"),
    ("Pcycl", "回旋辐射", "Cyclotron radiation", "MW"),
    ("Pwall", "第一壁负荷", "First-wall loading", "MW/m²"),
    ("H98", "H98 因子", "H98 factor", ""),
    ("betaN", "归一化比压 βN", "Normalised beta βN", ""),
    ("tau_E", "能量约束时间", "Energy confinement time", "s"),
    ("ntau", "劳森乘积 nτ", "Lawson product nτ", "s/m³"),
]


def _lang_idx(lang: str) -> int:
    return 0 if (lang or "zh").lower().startswith("zh") else 1


def _param_row(key: str, lang: str) -> dict:
    doc = _PARAM_DOCS.get(key)
    if doc:
        unit = doc[2]
        desc = doc[0] if _lang_idx(lang) == 0 else doc[1]
    else:
        unit = ""
        desc = key
    return {"k": key, "desc": desc, "unit": unit}


def generate_manual(config_name: str, lang: str = "zh") -> dict:
    """Build the manual dict for a configuration.

    Raises ``KeyError`` if the config is not registered.
    """
    spec = get(config_name)  # raises KeyError for unknown config
    li = _lang_idx(lang)
    overview = _OVERVIEW.get(config_name, (config_name, config_name))[li]

    # group the params that have a known doc entry, preserving group order
    grouped = []
    for gkey, zh_title, en_title in _GROUPS:
        rows = [
            _param_row(p, lang)
            for p in spec.params
            if _PARAM_GROUP.get(p) == gkey and p in _PARAM_DOCS
        ]
        if rows:
            grouped.append(
                {
                    "id": gkey,
                    "title": zh_title if li == 0 else en_title,
                    "items": rows,
                }
            )

    key_outputs = [
        {"k": k, "desc": (zh if li == 0 else en), "unit": u}
        for k, zh, en, u in _KEY_OUTPUTS
    ]

    presets = (
        list(spec.presets.keys())
        if hasattr(spec.presets, "keys")
        else list(spec.presets)
    )

    workflow = (
        [
            "选择位形与预设机型",
            "在左栏编辑几何 / 等离子体 / 燃料参数，右栏工作点即时重算",
            "在「最佳区判据」设置阈值（如 Q≥1、P_wall≤10 MW/m²）",
            "选择 X/Y 扫描轴与范围，点击「运行 POPCON 扫描」",
            "在结果区查看功率、增益、比压等指标；可导出 JSON/CSV/PNG",
        ]
        if li == 0
        else [
            "Pick a configuration and a preset machine",
            "Edit geometry / plasma / fuel parameters in the left column; the operating point recomputes live",
            "Set thresholds in 'Operating Window' (e.g. Q>=1, P_wall<=10 MW/m²)",
            "Choose X/Y scan axes and ranges, then 'Run POPCON Scan'",
            "Inspect power, gain, beta in the results panel; export JSON/CSV/PNG",
        ]
    )

    notes = (
        [
            "非托卡马克位形为定性模型，绝对值待标定，请勿直接用于工程设计。",
            "回旋辐射公式为 Trubnikov/Kukushkin 标度外推的 0-D 工程近似，非完整辐射输运。",
            "0-D 初筛：参数通过不一定能建成堆，但不通过几乎肯定不行。",
        ]
        if li == 0
        else [
            "Non-tokamak configurations are qualitative models pending calibration; do not use absolute values for engineering design.",
            "Cyclotron formulas are 0-D engineering extrapolations of Trubnikov/Kukushkin scalings, not full radiation transport.",
            "0-D screening: passing the filter does not guarantee a viable reactor, but failing it almost certainly rules one out.",
        ]
    )

    title = f"PolyFusion · {spec.label} {('使用说明' if li == 0 else 'Manual')}"
    return {
        "title": title,
        "config": config_name,
        "config_label": spec.label,
        "lang": "zh" if li == 0 else "en",
        "sections": [
            {
                "id": "overview",
                "title": ("位形概述" if li == 0 else "Overview"),
                "paragraph": overview,
            },
            {
                "id": "presets",
                "title": ("内置预设" if li == 0 else "Built-in Presets"),
                "items": [{"k": p, "desc": p, "unit": ""} for p in presets],
            },
            {
                "id": "params",
                "title": ("关键参数" if li == 0 else "Key Parameters"),
                "groups": grouped,
            },
            {
                "id": "outputs",
                "title": ("关键输出" if li == 0 else "Key Outputs"),
                "items": key_outputs,
            },
            {
                "id": "workflow",
                "title": ("操作流程" if li == 0 else "Workflow"),
                "steps": workflow,
            },
            {
                "id": "notes",
                "title": ("注意事项" if li == 0 else "Notes"),
                "steps": notes,
            },
        ],
    }


def list_supported_configs() -> list[str]:
    return sorted(REGISTRY.keys())
