"""Deterministic engineering analysis for VSC simulation reports."""

from __future__ import annotations

import math
from typing import Any, Iterable

from .configs.base import get


REPORT_ENGINE_VERSION = "deterministic-v1"

_CONFIG_METRICS = {
    "tokamak": (
        "H98",
        "H_ITPA20",
        "betaN",
        "q",
        "q95",
        "nbar_o_nGw",
        "LH_ratio",
    ),
    "mirror": (
        "beta",
        "beta_avg",
        "coll_ratio",
        "tau_Past",
        "tauC_eff",
    ),
    "frc": (
        "beta",
        "s_param",
        "s_over_E",
        "tau_Bohm",
        "tau_classical",
    ),
    "dipole": (
        "beta_in",
        "beta_out",
        "tauC_eff",
        "cyclotron_model",
    ),
    "stellarator": (
        "H_ISS04",
        "betaT",
        "nbar_o_Sudo",
        "iota",
        "aspect_vol",
    ),
}

_CONFIG_SCAN_TASKS = {
    "tokamak": ("Ip、BT0、H_fac", "betaN、q95、nbar_o_nGw、H98"),
    "mirror": ("B_vac、R_mirror、f_throat", "beta、coll_ratio、tau_Past"),
    "frc": ("r_s、l_s、Rw、f_shape", "beta、s_param、s_over_E、Pwall"),
    "dipole": ("r_ring、R_p、B_ring", "beta_in、beta_out、Pwall"),
    "stellarator": ("B0、N_fp、H_fac、iota", "betaT、nbar_o_Sudo、H_ISS04"),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _fmt(value: Any) -> str:
    number = _number(value)
    if number is None:
        return str(value)
    if number == 0:
        return "0"
    magnitude = abs(number)
    if magnitude >= 1e5 or magnitude < 1e-3:
        return f"{number:.4g}"
    return f"{number:.4g}"


def _pairs(keys: Iterable[str], values: dict[str, Any]) -> str:
    return "、".join(f"`{key}={_fmt(values[key])}`" for key in keys if key in values)


def _best_stats(scan: dict[str, Any]) -> tuple[int, int, float | None]:
    matrix = scan.get("best")
    if not isinstance(matrix, list) or not matrix:
        return 0, 0, None
    total = 0
    selected = 0
    for row in matrix:
        if not isinstance(row, list):
            continue
        for value in row:
            total += 1
            selected += int(bool(value))
    if not total:
        return 0, 0, None
    explicit = _number(scan.get("best_fraction"))
    return selected, total, explicit if explicit is not None else selected / total


def _criteria_text(config: str, outputs: dict[str, Any]) -> tuple[str, list[str]]:
    spec = get(config)
    checks: list[str] = []
    failures: list[str] = []
    windows = ((">=", spec.best_window.get("ge", {})), ("<=", spec.best_window.get("le", {})))
    for relation, criteria in windows:
        for key, threshold in criteria.items():
            value = _number(outputs.get(key))
            if value is None:
                checks.append(f"`{key}` 缺失，无法核对 `{relation}{_fmt(threshold)}`")
                continue
            passed = value >= threshold if relation == ">=" else value <= threshold
            checks.append(
                f"`{key}={_fmt(value)}` {'满足' if passed else '不满足'} `{relation}{_fmt(threshold)}`"
            )
            if not passed:
                failures.append(key)
    return "；".join(checks), failures


def _power_interpretation(outputs: dict[str, Any]) -> str:
    qfus = _number(outputs.get("Qfus"))
    ignited = _number(outputs.get("ignited"))
    if ignited is not None and ignited > 0.5:
        return "模型将该点标记为点火态，但仍需通过约束、稳定性与工程模型复核。"
    if qfus is None:
        return "未提供 `Qfus`，不能判断聚变增益水平。"
    if qfus >= 10:
        return "`Qfus` 较高，但 0-D 增益不能单独证明装置方案成立。"
    if qfus >= 1:
        return "`Qfus` 已达到 1 以上，但仍依赖外部加热且不等同于点火。"
    return "`Qfus` 低于 1，当前点表现为外部加热主导。"


def generate_deterministic_report_analysis(data: dict[str, Any]) -> str:
    """Generate a four-part Chinese analysis without network or model calls."""
    config = str(data.get("config") or "tokamak")
    try:
        spec = get(config)
    except KeyError:
        config = "tokamak"
        spec = get(config)
    preset = data.get("preset") or "—"
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    run = data.get("last_run") if isinstance(data.get("last_run"), dict) else {}
    outputs = run.get("outputs") if isinstance(run.get("outputs"), dict) else {}
    scan = data.get("last_scan") if isinstance(data.get("last_scan"), dict) else {}

    valid = _number(outputs.get("valid"))
    ignited = _number(outputs.get("ignited"))
    core_keys = ("Pfus", "Qfus", "Pheat", "Pwall")
    core_values = _pairs(core_keys, outputs) or "核心功率字段缺失"
    selected, total, best_fraction = _best_stats(scan)
    xkey = scan.get("xkey")
    ykey = scan.get("ykey")
    nx = scan.get("nx") or (len(scan.get("x", [])) if isinstance(scan.get("x"), list) else 0)
    ny = scan.get("ny") or (len(scan.get("y", [])) if isinstance(scan.get("y"), list) else 0)
    n_invalid = int(_number(scan.get("n_invalid")) or 0)

    core_lines = [
        "# 1. 核心结论",
        f"- 本次案例为 `config={config}`（{spec.label}），`preset={preset}`。",
        f"- 当前运行点：`valid={_fmt(valid) if valid is not None else '缺失'}`、"
        f"`ignited={_fmt(ignited) if ignited is not None else '缺失'}`；{core_values}。",
    ]
    if valid is None:
        core_lines.append("- 缺少 `valid`，不能确认当前运行点是否通过数值有效性检查。")
    elif valid > 0.5:
        core_lines.append(f"- 当前点是数值有效的 0-D 解。{_power_interpretation(outputs)}")
    else:
        core_lines.append("- 当前点被标记为无效；其功率和边界数值不应作为候选工况解读。")

    if best_fraction is None:
        core_lines.append("- 扫描网格证据不足，不能判断工作窗形状或敏感性趋势。")
    elif selected == 0:
        core_lines.append(
            f"- POPCON 扫描为 `{xkey or '未知'} × {ykey or '未知'}`，"
            f"`n_invalid={n_invalid}`；当前准则下未找到最佳区。"
        )
    else:
        scope = (
            "非常稀疏" if best_fraction <= 0.05 else "较有限" if best_fraction <= 0.25 else "占比较高"
        )
        core_lines.append(
            f"- POPCON 扫描为 `{xkey or '未知'} × {ykey or '未知'}`，"
            f"命中 `{selected}/{total}` 个 best 网格（`best_fraction={_fmt(best_fraction)}`），"
            f"候选区在当前粗网格中{scope}；这不代表当前运行点必然位于 best 区。"
        )
    if params.get("use_tauE") == 1 or params.get("use_tauE") == 1.0:
        core_lines.append("- `use_tauE=1`，结果依赖固定约束时间假设。")
    if params.get("geom_model") == 0 or params.get("geom_model") == 0.0:
        core_lines.append("- `geom_model=0`，几何模型较简化。")

    power_keys = ("Ptrans", "Pbrem", "Pcycl", "P_line", "Pn")
    constraint_keys = ("tauE_used", "tau_E", "Zeff", "fHe", "fimp", "Zimp", "Vp", "Sw")
    config_metrics = _pairs(_CONFIG_METRICS[config], outputs)
    criteria, failed_criteria = _criteria_text(config, outputs)
    metric_lines = [
        "",
        "# 2. 关键指标解读",
        f"- 功率与损失：{_pairs(core_keys + power_keys, outputs) or '未提供可用功率字段'}。",
        f"- 约束、成分与几何：{_pairs(constraint_keys, outputs) or '相关字段不足'}。",
        f"- {spec.label} 专属指标：{config_metrics or '相关字段不足'}。",
        f"- 当前点对默认 best 准则的逐项核对：{criteria or '没有可核对准则'}。",
    ]
    if "LH_ratio" in outputs:
        metric_lines.append("- `LH_ratio` 仅用于阈值模型比较，不能表述为保证进入或维持 H 模。")

    risk_lines = ["", "# 3. 风险与不确定性"]
    risk_lines.append("- `valid` 只描述单点数值有效性，不能替代 POPCON 工作窗证据。")
    missing_coordinates = not isinstance(scan.get("x"), list) or not isinstance(
        scan.get("y"), list
    )
    if best_fraction is None or missing_coordinates:
        risk_lines.append("- 扫描缺少完整 `x/y` 坐标证据，不能给出最佳区实际边界或敏感性方向。")
    if n_invalid:
        risk_lines.append(f"- 扫描含 `{n_invalid}` 个无效点，候选区连通性可能受数值空洞影响。")
    if selected == 0 and best_fraction is not None:
        risk_lines.append("- best 全为 0 只表示当前筛选准则未命中，不等于所有网格点都数值无效。")
    elif best_fraction is not None and best_fraction <= 0.05:
        risk_lines.append("- best 命中不超过 5%，粗网格下可能是孤立单元，需要局部加密确认连续性。")
    if failed_criteria:
        risk_lines.append(f"- 当前点未满足默认 best 准则中的：`{'`、`'.join(failed_criteria)}`。")
    if params.get("use_tauE") == 1 or params.get("use_tauE") == 1.0:
        risk_lines.append("- 固定 `tauE` 会直接影响功率平衡、增益和点火判断，需做约束时间敏感性扫描。")
    if params.get("geom_model") == 0 or params.get("geom_model") == 0.0:
        risk_lines.append("- 简化几何会影响体积、壁面积和 `Pwall`，绝对值仅适合初筛。")
    if _number(outputs.get("P_line")) == 0:
        risk_lines.append("- `P_line=0` 只代表当前成分和模型输出，不能外推为线辐射始终可忽略。")

    scan_params, scan_metrics = _CONFIG_SCAN_TASKS[config]
    task_lines = [
        "",
        "# 4. 下一步建议",
        f"1. 加密 `{xkey or spec.scan_defaults['xkey']} × "
        f"{ykey or spec.scan_defaults['ykey']}` POPCON 网格，"
        "保存完整 `x/y/best/valid`；监控 `best_fraction`、`n_invalid`、`Pfus`、`Qfus`、`Pheat`、`Pwall`。",
        "2. 扫描 `tauE` 或切换约束标度；监控 `tauE_used/tau_E`、`ignited`、`Pfus`、`Qfus`、`Ptrans`。",
        f"3. 扫描 {scan_params}；监控 {scan_metrics}，并逐项复核默认 best 准则。",
        "4. 扫描 `fHe`、`fimp`、`Zimp`；监控 `Zeff`、`Pbrem`、`Pcycl`、`P_line`、`Qfus`。",
    ]
    if nx and ny:
        task_lines.append(f"5. 当前网格为 `{nx}×{ny}`；在 best 命中附近至少加密一档后再判断区域连续性。")

    return "\n".join(core_lines + metric_lines + risk_lines + task_lines)
