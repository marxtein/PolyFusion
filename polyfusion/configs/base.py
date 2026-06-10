"""Configuration-agnostic interface + registry (SP4.3).

Each magnetic configuration (tokamak, mirror, …) is described by a
:class:`ConfigSpec`: its input parameters, presets, a ``solve`` adapter that
returns an outputs dict, and POPCON/scan metadata.  Front-ends (CLI, web app)
and the 2-D scanner drive every configuration through this single interface,
so adding a configuration never touches the UI or scan code.

The abstraction was extracted only after two concrete samples existed
(tokamak ``funsc`` + mirror ``solve_mirror``) to avoid premature generality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..tokamak import funsc
from ..presets import (PRESETS as TOKAMAK_PRESETS, PARAM_ORDER as TOKAMAK_PARAMS,
                       PRESET_GROUPS as TOKAMAK_GROUPS)
from .mirror import solve_mirror
from .frc import solve_frc
from .dipole import solve_dipole
from .stellarator import solve_stellarator

# Inputs each solver accepts (positional/keyword names).
_MIRROR_PARAMS = ["a_c", "L_c", "B_vac", "R_mirror", "ni0", "Ti0", "Te0",
                  "Sn", "ST", "g", "fsig", "f_throat", "Rw",
                  "icase", "f1", "fHe", "fimp", "Zimp", "phi_i_over_Te", "lnLambda"]
_FRC_PARAMS = ["r_s", "l_s", "r_w", "B_e", "Ti", "Te", "f_shape", "fsig", "Rw",
               "icase", "f1", "fHe", "fimp", "Zimp"]
_DIPOLE_PARAMS = ["r_ring", "R_p", "B_ring", "n0", "Ti0", "Te0", "tauE",
                  "icase", "f1", "fHe", "fimp", "Zimp", "Rw", "f_belt"]
_STELL_PARAMS = ["R0", "A", "kappa", "delta", "Sn", "ST", "ni0", "Ti0", "fT",
                 "fsig", "f1", "B0", "iota", "tauE", "fHe", "fimp", "Zimp",
                 "Rw", "g", "icase", "f_ren"]

# Mirror machine presets (open-field, Realta/Budker class).  v2: radial
# peaking Sn/ST, wall gap g, throat fraction f_throat (docs/24).
MIRROR_PRESETS = {
    "BEAM": dict(  # Realta-class HTS break-even mirror, D-T
        a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, ni0=3e20, Ti0=15.0, Te0=10.0,
        Sn=0.5, ST=1.0, g=0.05, fsig=1.0, f_throat=0.1,
        Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10),
    "GDT": dict(  # Budker gas-dynamic trap: warm collisional bulk plasma
        # (bulk T ~ 0.25 keV keeps lambda_ii < R*L -> genuinely gas-dynamic
        #  regime; the famous Te=0.9 keV record is an ECRH-heated state)
        a_c=0.15, L_c=7.0, B_vac=0.35, R_mirror=35.0, ni0=5e19, Ti0=0.25, Te0=0.25,
        Sn=0.5, ST=1.0, g=0.03, fsig=1.0, f_throat=0.15,
        Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10),
    "pB-mirror": dict(  # aneutronic high-field mirror concept
        a_c=0.5, L_c=15.0, B_vac=10.0, R_mirror=15.0, ni0=3e20, Ti0=150.0, Te0=100.0,
        Sn=0.5, ST=1.0, g=0.05, fsig=1.0, f_throat=0.1,
        Rw=0.9, icase=5, f1=0.9, fHe=0.0, fimp=0.0, Zimp=10),
    "GAMMA-10": dict(  # Tsukuba tandem mirror (experiment)
        a_c=0.18, L_c=6.0, B_vac=0.5, R_mirror=6.4, ni0=0.2e20, Ti0=5.0, Te0=0.1,
        Sn=0.5, ST=1.0, g=0.03, fsig=1.0, f_throat=0.15,
        Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10),
}
MIRROR_GROUPS = {
    "实验装置 Experiments": ["GDT", "GAMMA-10"],
    "概念·反应堆 Concepts": ["BEAM", "pB-mirror"],
}

# FRC machine presets (TAE / Helion class).
FRC_PRESETS = {
    "FRC-DT": dict(  # D-T compact FRC reactor point (illustrative, uncalibrated)
        r_s=0.5, l_s=5.0, r_w=0.7, B_e=3.5, Ti=15.0, Te=12.0,
        f_shape=0.85, fsig=1.0, Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10),
    "Helion-DHe3": dict(  # Helion-class D-3He pulsed high-field FRC
        r_s=0.3, l_s=2.0, r_w=0.4, B_e=8.0, Ti=70.0, Te=50.0,
        f_shape=0.75, fsig=1.0, Rw=0.9, icase=3, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10),
    "C-2W": dict(  # TAE Norman-class beam-driven FRC (experiment-scale)
        r_s=0.4, l_s=3.0, r_w=0.6, B_e=1.0, Ti=2.0, Te=1.0,
        f_shape=0.85, fsig=1.0, Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10),
}

# Levitated-dipole presets (Hasegawa/Kesner class; D-D signature fuel).
DIPOLE_PRESETS = {
    "Dipole-DD": dict(  # Kesner-class D-D dipole reactor point (illustrative)
        r_ring=1.0, R_p=10.0, B_ring=10.0, n0=1e21, Ti0=30.0, Te0=20.0, tauE=5.0,
        icase=2, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10, Rw=0.9, f_belt=0.5),
    "Dipole-DHe3": dict(  # advanced-fuel D-3He dipole
        r_ring=1.0, R_p=8.0, B_ring=12.0, n0=5e20, Ti0=80.0, Te0=60.0, tauE=10.0,
        icase=3, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10, Rw=0.9, f_belt=0.5),
    "LDX": dict(  # experiment-scale levitated dipole
        r_ring=0.3, R_p=2.0, B_ring=2.0, n0=1e18, Ti0=0.5, Te0=0.5, tauE=0.1,
        icase=2, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10, Rw=0.9, f_belt=0.5),
}

# Stellarator presets (HELIAS reactor / W7-X / LHD class).
STELL_PRESETS = {
    "HELIAS": dict(  # HELIAS-class D-T stellarator reactor (illustrative)
        R0=18.0, A=10.0, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0,
        fT=1.0, fsig=1.0, f1=0.5, B0=5.0, iota=1.0, tauE=1.0, fHe=0.04, fimp=0.01,
        Zimp=10, Rw=0.7, g=0.1, icase=1, f_ren=1.0),
    "W7-X": dict(  # Wendelstein 7-X experiment scale (D-T equivalent)
        R0=5.5, A=10.0, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0, ni0=2e19, Ti0=2.0,
        fT=1.0, fsig=1.0, f1=0.5, B0=2.5, iota=0.9, tauE=0.2, fHe=0.0, fimp=0.0,
        Zimp=10, Rw=0.7, g=0.05, icase=1, f_ren=1.2),
    "LHD": dict(  # Large Helical Device experiment scale
        R0=3.9, A=6.0, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0, ni0=5e19, Ti0=2.0,
        fT=1.0, fsig=1.0, f1=0.5, B0=2.85, iota=1.0, tauE=0.3, fHe=0.0, fimp=0.0,
        Zimp=10, Rw=0.7, g=0.05, icase=1, f_ren=1.0),
    "HSX": dict(  # Helically Symmetric eXperiment (quasi-helical)
        R0=1.2, A=8.0, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0, ni0=5e18, Ti0=0.5,
        fT=1.0, fsig=1.0, f1=0.5, B0=1.0, iota=1.05, tauE=0.01, fHe=0.0, fimp=0.0,
        Zimp=10, Rw=0.7, g=0.03, icase=1, f_ren=1.0),
    "CFQS": dict(  # China-Japan quasi-axisymmetric stellarator
        R0=1.0, A=4.0, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0, ni0=1e19, Ti0=1.0,
        fT=1.0, fsig=1.0, f1=0.5, B0=1.0, iota=1.0, tauE=0.02, fHe=0.0, fimp=0.0,
        Zimp=10, Rw=0.7, g=0.03, icase=1, f_ren=1.0),
}
STELL_GROUPS = {
    "实验装置 Experiments": ["W7-X", "LHD", "HSX", "CFQS"],
    "反应堆 Reactor": ["HELIAS"],
}
FRC_GROUPS = {
    "实验装置 Experiments": ["C-2W"],
    "概念·反应堆 Concepts": ["FRC-DT", "Helion-DHe3"],
}
DIPOLE_GROUPS = {
    "实验装置 Experiments": ["LDX"],
    "概念·反应堆 Concepts": ["Dipole-DD", "Dipole-DHe3"],
}


# POPCON contour specs: per quantity -> fixed levels + colour, faithfully
# reproducing scan2d_sc.m / etsc.html (one contour line per named level).
# fields: f=output key, c=colour, lv=levels, dash, w=width, scale (display *),
#         label (legend/option text), on (shown by default).
TOKAMAK_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500, 1000], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.01, 0.1, 1, 10, 100], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "nbar_o_nGw", "c": "#e9eef7", "lv": [0.5, 1.0], "label": "n/nGw", "on": True},
    {"f": "Pheat", "c": "#ff6b6b", "lv": [5, 10, 50, 100], "label": "Pheat [MW]", "on": True},
    {"f": "betaN", "c": "#ffd166", "lv": [1, 3, 10], "label": "βN", "on": True},
    {"f": "H98", "c": "#c792ff", "lv": [0.5, 1, 2, 5, 10], "label": "H98", "on": True},
    {"f": "HST", "c": "#c792ff", "lv": [0.5, 1, 2, 5, 10], "dash": "dash", "label": "HST", "on": False},
    {"f": "betaT", "c": "#36e2c4", "lv": [0.01, 0.1, 0.5, 1], "label": "βt", "on": False},
    {"f": "Pbrem", "c": "#ff9e3d", "lv": [0.1, 0.5, 1, 5, 10], "label": "Pbrem [MW]", "on": False},
    {"f": "Eth", "c": "#b388ff", "lv": [10, 50, 100, 500, 1000], "label": "Eth [MJ]", "on": False},
    {"f": "ne0", "c": "#d4a373", "lv": [0.5, 1, 2, 5, 10], "scale": 1e-20, "label": "ne0 [1e20]", "on": False},
    {"f": "Vp", "c": "#7ddc6b", "lv": [50, 100, 500, 1000, 5000], "label": "Vp [m³]", "on": False},
]
MIRROR_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.1, 1, 10, 100], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "beta", "c": "#36e2c4", "lv": [0.1, 0.3, 0.6], "label": "β", "on": True},
    {"f": "Ptrans", "c": "#ff6b6b", "lv": [1, 10, 100, 1000], "label": "Ptrans [MW]", "on": True},
    {"f": "tau_c", "c": "#c792ff", "lv": [0.01, 0.1, 1], "label": "τ_c [s]", "on": False},
    {"f": "ntau", "c": "#e9eef7", "lv": [1e18, 1e19, 1e20, 1e21], "label": "nτ", "on": False},
]
FRC_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500, 1000], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.1, 1, 10, 100], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "beta", "c": "#36e2c4", "lv": [0.6, 0.8, 0.95], "label": "β", "on": True},
    {"f": "Ptrans", "c": "#ff6b6b", "lv": [1, 10, 100, 1000], "label": "Ptrans [MW]", "on": True},
    {"f": "tau_E", "c": "#c792ff", "lv": [1e-4, 1e-3, 1e-2], "label": "τ_E [s]", "on": False},
    {"f": "ntau", "c": "#e9eef7", "lv": [1e18, 1e19, 1e20], "label": "nτ", "on": False},
]
DIPOLE_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [0.1, 1, 10, 100, 1000], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.1, 1, 10], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "beta_ring", "c": "#36e2c4", "lv": [0.1, 0.5, 1], "label": "β_ring", "on": True},
    {"f": "Ptrans", "c": "#ff6b6b", "lv": [1, 10, 100], "label": "Ptrans [MW]", "on": True},
    {"f": "Eth", "c": "#b388ff", "lv": [1, 10, 100, 1000], "label": "Eth [MJ]", "on": False},
    {"f": "ntau", "c": "#e9eef7", "lv": [1e19, 1e20, 1e21], "label": "nτ", "on": False},
]
STELL_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500, 1000], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.01, 0.1, 1, 10, 100], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "nbar_o_Sudo", "c": "#e9eef7", "lv": [0.5, 1.0], "label": "n/Sudo", "on": True},
    {"f": "Pheat", "c": "#ff6b6b", "lv": [5, 10, 50, 100], "label": "Pheat [MW]", "on": True},
    {"f": "betaT", "c": "#36e2c4", "lv": [0.01, 0.05, 0.1], "label": "βt", "on": True},
    {"f": "H_ISS04", "c": "#c792ff", "lv": [0.5, 1, 2, 5], "label": "H_ISS04", "on": False},
]


@dataclass
class ConfigSpec:
    name: str
    label: str
    params: list[str]            # input names accepted by the solver
    required: list[str]          # must be present to run
    positive: list[str]          # must be > 0
    presets: dict                # name -> full parameter dict
    contour_fields: list[str]    # default POPCON contour outputs
    scan_defaults: dict          # {xkey, ykey, xmin, xmax, ymin, ymax}
    best_window: dict            # {"ge": {...}, "le": {...}} operating window
    contour_spec: list           # [{f,c,lv,...}] POPCON quantities + fixed levels
    _solve: Callable
    preset_groups: dict | None = None   # optional <optgroup> grouping for presets

    def solve(self, params: dict) -> dict:
        """Run the solver with the subset of params it accepts.

        Numerics are coerced to float (icase stays int): callers may pass
        JSON-parsed ints exceeding int64, which would break numpy float ops.
        """
        kw = {}
        for k in self.params:
            if k not in params:
                continue
            v = params[k]
            if k == "icase":
                kw[k] = int(v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                kw[k] = float(v)
            else:
                kw[k] = v
        return self._solve(**kw).as_dict()

    def validate(self, params: dict) -> list[str]:
        errors = []
        missing = [k for k in self.required if k not in params]
        if missing:
            errors.append(f"missing parameters: {', '.join(missing)}")
        for k in self.positive:
            v = params.get(k)
            if v is not None and not (isinstance(v, (int, float)) and v > 0):
                errors.append(f"{k} must be > 0 (got {v!r})")
        ic = params.get("icase")
        if ic is not None and ic not in (1, 2, 3, 4, 5, 6):
            errors.append(f"icase must be 1..6 (got {ic!r})")
        return errors


TOKAMAK = ConfigSpec(
    name="tokamak", label="托卡马克 Tokamak",
    params=TOKAMAK_PARAMS, required=TOKAMAK_PARAMS,
    positive=["R0", "A", "kappa", "ni0", "Ti0", "BT0", "Ip", "tauE"],
    presets=TOKAMAK_PRESETS,
    contour_fields=["Pfus", "Qfus", "Pheat", "betaN", "nbar_o_nGw", "H98"],
    scan_defaults=dict(xkey="Ti0", ykey="ni0", xmin=20, xmax=200, ymin=0.5e20, ymax=4e20),
    best_window={"ge": {"Pfus": 10, "Qfus": 1}, "le": {"nbar_o_nGw": 1, "Pheat": 100}},
    contour_spec=TOKAMAK_CONTOURS,
    preset_groups=TOKAMAK_GROUPS,
    _solve=funsc,
)

MIRROR = ConfigSpec(
    name="mirror", label="磁镜 Magnetic Mirror",
    params=_MIRROR_PARAMS,
    required=["a_c", "L_c", "B_vac", "R_mirror", "ni0", "Ti0", "Te0", "icase"],
    positive=["a_c", "L_c", "B_vac", "R_mirror", "ni0", "Ti0", "Te0"],
    presets=MIRROR_PRESETS,
    contour_fields=["Pfus", "Qfus", "Ptrans", "beta", "tau_c", "ntau"],
    scan_defaults=dict(xkey="Ti0", ykey="ni0", xmin=5, xmax=200, ymin=0.5e20, ymax=6e20),
    best_window={"ge": {"Pfus": 1, "Qfus": 1}, "le": {"beta": 0.6}},
    contour_spec=MIRROR_CONTOURS,
    preset_groups=MIRROR_GROUPS,
    _solve=solve_mirror,
)

FRC = ConfigSpec(
    name="frc", label="场反位形 FRC",
    params=_FRC_PARAMS,
    required=["r_s", "l_s", "r_w", "B_e", "Ti", "Te", "icase"],
    positive=["r_s", "l_s", "r_w", "B_e", "Ti", "Te"],
    presets=FRC_PRESETS,
    contour_fields=["Pfus", "Qfus", "Ptrans", "beta", "tau_E", "ntau"],
    scan_defaults=dict(xkey="Ti", ykey="B_e", xmin=5, xmax=150, ymin=1, ymax=12),
    best_window={"ge": {"Pfus": 1, "Qfus": 1}, "le": {}},
    contour_spec=FRC_CONTOURS,
    preset_groups=FRC_GROUPS,
    _solve=solve_frc,
)

DIPOLE = ConfigSpec(
    name="dipole", label="偶极场 Dipole",
    params=_DIPOLE_PARAMS,
    required=["r_ring", "R_p", "B_ring", "n0", "Ti0", "Te0", "tauE", "icase"],
    positive=["r_ring", "R_p", "B_ring", "n0", "Ti0", "Te0", "tauE"],
    presets=DIPOLE_PRESETS,
    contour_fields=["Pfus", "Qfus", "Ptrans", "beta_ring", "Eth", "ntau"],
    scan_defaults=dict(xkey="Ti0", ykey="n0", xmin=5, xmax=100, ymin=1e20, ymax=2e21),
    best_window={"ge": {"Pfus": 1, "Qfus": 1}, "le": {}},
    contour_spec=DIPOLE_CONTOURS,
    preset_groups=DIPOLE_GROUPS,
    _solve=solve_dipole,
)

STELLARATOR = ConfigSpec(
    name="stellarator", label="仿星器 Stellarator",
    params=_STELL_PARAMS,
    required=[p for p in _STELL_PARAMS if p != "f_ren"],
    positive=["R0", "A", "kappa", "ni0", "Ti0", "B0", "iota", "tauE"],
    presets=STELL_PRESETS,
    contour_fields=["Pfus", "Qfus", "Pheat", "betaT", "nbar_o_Sudo", "H_ISS04"],
    scan_defaults=dict(xkey="Ti0", ykey="ni0", xmin=5, xmax=40, ymin=0.5e20, ymax=3e20),
    best_window={"ge": {"Pfus": 10, "Qfus": 1}, "le": {"nbar_o_Sudo": 1, "Pheat": 100}},
    contour_spec=STELL_CONTOURS,
    preset_groups=STELL_GROUPS,
    _solve=solve_stellarator,
)

REGISTRY = {c.name: c for c in (TOKAMAK, MIRROR, FRC, DIPOLE, STELLARATOR)}


def get(config: str) -> ConfigSpec:
    if config not in REGISTRY:
        raise KeyError(f"unknown configuration {config!r}; have {list(REGISTRY)}")
    return REGISTRY[config]
