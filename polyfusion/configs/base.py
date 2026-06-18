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

import math
from dataclasses import dataclass, field
from typing import Callable

from ..tokamak import funsc
from ..presets import (PRESETS as TOKAMAK_PRESETS, PARAM_ORDER as TOKAMAK_PARAMS,
                       PRESET_GROUPS as TOKAMAK_GROUPS)
from ..presets_io import load_presets
from .mirror import solve_mirror
from .frc import solve_frc, frc_shape_outlines
from .dipole import solve_dipole
from .stellarator import solve_stellarator, section_outlines

# Inputs each solver accepts (positional/keyword names).
_MIRROR_PARAMS = ["use_tauE", "geometry", "a_c", "L_c", "B_vac", "R_mirror", "ni0", "Ti0", "Te0", "tauE",
                  "Sn", "ST", "g", "fsig", "f_throat", "f_alpha", "B_expand", "Rw",
                  "icase", "f1", "fHe", "fimp", "Zimp", "phi_i_over_Te", "lnLambda",
                  "imp_name", "L_th", "profile", "f_axial", "L_expand"]
_FRC_PARAMS = ["use_tauE", "geom_weighted", "sep_model", "m", "r_s", "l_s", "r_w", "B_e", "Ti", "Te", "tauE", "f_shape", "fsig", "Rw",
               "icase", "f1", "fHe", "fimp", "Zimp", "imp_name"]
_DIPOLE_PARAMS = ["use_tauE", "r_ring", "R_p", "B_ring", "n0", "Ti0", "Te0", "tauE",
                  "L_in_fac", "fsig", "icase", "f1", "fHe", "fimp", "Zimp", "Rw",
                  "ring_model", "imp_name"]
_STELL_PARAMS = ["use_tauE", "R0", "a", "N_fp", "delta_h", "etabar", "Sn", "ST",
                 "ni0", "Ti0", "fT", "fsig", "f1", "B0", "iota", "tauE", "fHe",
                 "fimp", "Zimp", "Rw", "g", "icase", "f_ren", "imp_name",
                 "H_fac", "rc", "zs", "Vp_override", "Sw_override", "shape",
                 "geometry_variants"]

# Machine presets for every non-tokamak configuration now live in JSON data
# files (``polyfusion/presets/<config>.json``, with any
# ``~/.polyfusion/presets/<config>.json`` merged on top) so non-developers can
# add presets by editing JSON instead of this module.  See presets_io.py.
#   - mirror: open-field, Realta/Budker class (radial peaking Sn/ST, wall gap g,
#     throat fraction f_throat; docs/24)
#   - frc:    TAE / Helion class
#   - dipole: levitated dipole, Hasegawa/Kesner class (D-D signature fuel)
#   - stellarator: single near-axis (Garren-Boozer) geometry (Scheme D) where
#     etabar [1/m] is the sole shaping knob (!= 0) and elongation is a derived
#     OUTPUT; concept reactors use the near-axis baseline, real machines supply
#     a measured iota>0 and an approximate Vp_override [m^3] (docs/28).
MIRROR_PRESETS, MIRROR_GROUPS = load_presets("mirror")
FRC_PRESETS, FRC_GROUPS = load_presets("frc")
DIPOLE_PRESETS, DIPOLE_GROUPS = load_presets("dipole")
STELL_PRESETS, STELL_GROUPS = load_presets("stellarator")


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
    {"f": "q", "c": "#5ad1ff", "lv": [2, 3, 5, 8], "dash": "dot", "label": "q", "on": False},
    {"f": "betaT", "c": "#36e2c4", "lv": [0.01, 0.1, 0.5, 1], "label": "βt", "on": False},
    {"f": "Pbrem", "c": "#ff9e3d", "lv": [0.1, 0.5, 1, 5, 10], "label": "Pbrem [MW]", "on": False},
    {"f": "Eth", "c": "#b388ff", "lv": [10, 50, 100, 500, 1000], "label": "Eth [MJ]", "on": False},
    {"f": "ne0", "c": "#d4a373", "lv": [0.5, 1, 2, 5, 10], "scale": 1e-20, "label": "ne0 [1e20]", "on": False},
    {"f": "Vp", "c": "#7ddc6b", "lv": [50, 100, 500, 1000, 5000], "label": "Vp [m³]", "on": False},
]
MIRROR_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.01, 0.1, 1, 10], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "Pheat", "c": "#ff6b6b", "lv": [1, 10, 50, 100], "label": "Pheat [MW]", "on": True},
    {"f": "beta", "c": "#36e2c4", "lv": [0.1, 0.3, 0.6], "label": "beta", "on": True},
    {"f": "tau_E", "c": "#c792ff", "lv": [0.01, 0.1, 1], "label": "tauE [s]", "on": True},
    {"f": "Ptrans", "c": "#5ad1ff", "lv": [1, 10, 100], "label": "Ptrans [MW]", "on": True},
    {"f": "ntau", "c": "#e9eef7", "lv": [1e18, 1e19, 1e20], "label": "n*tau", "on": False},
    {"f": "Pbrem", "c": "#b388ff", "lv": [0.1, 1, 10], "label": "Pbrem [MW]", "on": False},
    {"f": "Pcycl", "c": "#ff9e3d", "lv": [0.1, 1, 10], "label": "Pcycl [MW]", "on": False},
    {"f": "P_line", "c": "#ffd166", "lv": [0.1, 1, 10], "label": "Pline [MW]", "on": False},
    {"f": "Eth", "c": "#9be564", "lv": [1, 10, 100], "label": "Eth [MJ]", "on": False},
    {"f": "Pwall", "c": "#d4a373", "lv": [0.1, 0.5, 1, 5], "label": "Pwall [MW/m2]", "on": False},
]
FRC_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500, 1000], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.01, 0.1, 1, 10], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "Pheat", "c": "#ff6b6b", "lv": [1, 10, 100, 1000], "label": "Pheat [MW]", "on": True},
    # FRC-defining: LSX confinement, Lawson product, kinetic parameter
    {"f": "tau_E", "c": "#c792ff", "lv": [1e-4, 1e-3, 1e-2], "label": "tau_E [s]", "on": True},
    {"f": "ntau", "c": "#e9eef7", "lv": [1e18, 1e19, 1e20], "label": "n*tau", "on": True},
    {"f": "s_param", "c": "#36e2c4", "lv": [2, 4, 10, 20], "label": "s-bar", "on": True},
    # pressure-locked density and trapped flux
    {"f": "ni0", "c": "#d4a373", "lv": [1, 5, 10, 50], "scale": 1e-20, "label": "n_i0 [1e20]", "on": False},
    {"f": "flux_p", "c": "#ffd166", "lv": [0.01, 0.1, 1], "label": "flux_p [Wb]", "on": False},
    {"f": "Ptrans", "c": "#5ad1ff", "lv": [10, 100, 1000], "label": "Ptrans [MW]", "on": False},
    {"f": "Pbrem", "c": "#b388ff", "lv": [1, 10, 100], "label": "Pbrem [MW]", "on": False},
    {"f": "Pwall", "c": "#ff9e3d", "lv": [0.1, 1, 5, 10], "label": "Pwall [MW/m2]", "on": False},
    {"f": "Eth", "c": "#9be564", "lv": [0.1, 1, 10], "label": "Eth [MJ]", "on": False},
    {"f": "beta", "c": "#7ddc6b", "lv": [0.6, 0.75, 0.9], "label": "<beta>", "on": False},
]
DIPOLE_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [0.01, 0.1, 1, 10, 100], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.01, 0.1, 1, 10], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "Pheat", "c": "#ff6b6b", "lv": [0.1, 1, 10, 100], "label": "Pheat [MW]", "on": True},
    # dipole-defining: local pressure-balance limit + radiation dominance (D-D)
    {"f": "beta_in", "c": "#36e2c4", "lv": [0.1, 0.5, 1.0], "label": "beta_in", "on": True},
    {"f": "Pbrem", "c": "#b388ff", "lv": [0.01, 0.1, 1, 10], "label": "Pbrem [MW]", "on": True},
    {"f": "ntau", "c": "#e9eef7", "lv": [1e18, 1e19, 1e20, 1e21], "label": "n*tau", "on": True},
    {"f": "Ptrans", "c": "#5ad1ff", "lv": [0.1, 1, 10], "label": "Ptrans [MW]", "on": False},
    {"f": "Pn", "c": "#ffd166", "lv": [0.01, 0.1, 1], "label": "Pn [MW]", "on": False},
    {"f": "Pcycl", "c": "#ff9e3d", "lv": [1e-3, 0.01, 0.1], "label": "Pcycl [MW]", "on": False},
    {"f": "Eth", "c": "#9be564", "lv": [1, 10, 100], "label": "Eth [MJ]", "on": False},
    {"f": "Pwall", "c": "#d4a373", "lv": [0.01, 0.1, 1], "label": "Pwall [MW/m2]", "on": False},
    {"f": "nbar", "c": "#7ddc6b", "lv": [0.1, 1, 10], "scale": 1e-20, "label": "nbar [1e20]", "on": False},
]
STELL_CONTOURS = [
    {"f": "Pfus", "c": "#4ea1ff", "lv": [1, 10, 50, 100, 500, 1000], "label": "Pfus [MW]", "on": True},
    {"f": "Qfus", "c": "#3ddc84", "lv": [0.01, 0.1, 1, 10, 100], "w": 2.4, "label": "Qfus", "on": True},
    {"f": "Pheat", "c": "#ff6b6b", "lv": [5, 10, 50, 100], "label": "Pheat [MW]", "on": True},
    # stellarator-defining: Sudo margin, ISS04 quality, beta soft limit
    {"f": "nbar_o_Sudo", "c": "#e9eef7", "lv": [0.5, 1.0, 1.5], "label": "n/Sudo", "on": True},
    {"f": "H_ISS04", "c": "#c792ff", "lv": [0.5, 1, 1.5, 2], "label": "H_ISS04", "on": True},
    {"f": "betaT", "c": "#36e2c4", "lv": [0.01, 0.05, 0.1], "label": "beta_t", "on": True},
    {"f": "tau_ISS04", "c": "#ffd166", "lv": [0.1, 0.5, 1, 2], "label": "tau_ISS04 [s]", "on": False},
    {"f": "iota_geom", "c": "#ff5d8f", "lv": [0.4, 0.6, 0.9, 1.2], "label": "iota_geom", "on": False},
    {"f": "beta_o_limit", "c": "#36e2c4", "lv": [0.5, 1.0, 2.0], "dash": "dash", "label": "beta/limit", "on": False},
    {"f": "aspect_vol", "c": "#7ddc6b", "lv": [5, 10, 20, 40], "label": "R/a_vol", "on": False},
    {"f": "nbar_geom_o_nbar", "c": "#e9eef7", "lv": [0.98, 1.0, 1.02], "dash": "dot", "label": "ngeom/n", "on": False},
    {"f": "geom_volume_ratio", "c": "#9be564", "lv": [0.8, 1.0, 1.2], "dash": "dot", "label": "Vp/Vgeom", "on": False},
    {"f": "geom_wall_ratio", "c": "#d4a373", "lv": [0.8, 1.0, 1.2], "dash": "dot", "label": "Sw/Swgeom", "on": False},
    {"f": "Pbrem", "c": "#b388ff", "lv": [1, 10, 100], "label": "Pbrem [MW]", "on": False},
    {"f": "Pcycl", "c": "#ff9e3d", "lv": [0.1, 1, 10], "label": "Pcycl [MW]", "on": False},
    {"f": "Eth", "c": "#9be564", "lv": [10, 100, 1000], "label": "Eth [MJ]", "on": False},
    {"f": "Pwall", "c": "#d4a373", "lv": [0.1, 0.5, 1, 5], "label": "Pwall [MW/m2]", "on": False},
    {"f": "Pn", "c": "#5ad1ff", "lv": [1, 10, 100, 500], "label": "Pn [MW]", "on": False},
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
    # input-domain protection (audit Phase 1): inclusive [lo, hi] bounds per
    # parameter (None = unbounded on that side) and an optional cross-parameter
    # validator returning a list of error strings.
    bounds: dict = field(default_factory=dict)
    cross: Callable | None = None
    # optional cross-section outline generator for the UI shape view:
    # called with the full input dict, returns a JSON-able dict
    shape_fn: Callable | None = None
    # additional selectable window criteria (audit P1 red lines): same
    # {"ge":{},"le":{}} shape as best_window, but OFF by default in the UI —
    # users opt in via checkboxes instead of having them imposed.
    optional_window: dict | None = None

    def solve(self, params: dict) -> dict:
        """Run the solver with the subset of params it accepts.

        Numerics are coerced to float (icase stays int): callers may pass
        JSON-parsed ints exceeding int64, which would break numpy float ops.

        The returned dict carries a ``valid`` flag (1.0/0.0): a point is
        invalid when any numeric output is non-finite or complex (audit P0 —
        such points must never be displayed as feasible operating points).
        ``invalid_fields`` lists the offending outputs.
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
        out = self._solve(**kw).as_dict()
        bad = [k for k, v in out.items()
               if isinstance(v, complex)
               or (isinstance(v, float) and not math.isfinite(v))]
        out["valid"] = 0.0 if bad else 1.0
        if bad:
            out["invalid_fields"] = ",".join(bad)
        return out

    def validate(self, params: dict) -> list[str]:
        errors = []
        missing = [k for k in self.required if k not in params]
        if missing:
            errors.append(f"missing parameters: {', '.join(missing)}")
        for k in self.positive:
            v = params.get(k)
            if v is not None and not (isinstance(v, (int, float)) and v > 0):
                errors.append(f"{k} must be > 0 (got {v!r})")
        for k, (lo, hi) in self.bounds.items():
            v = params.get(k)
            if v is None or not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            if not math.isfinite(v):
                errors.append(f"{k} must be finite (got {v!r})")
            elif (lo is not None and v < lo) or (hi is not None and v > hi):
                rng = f"[{'-inf' if lo is None else lo}, {'inf' if hi is None else hi}]"
                errors.append(f"{k} must be in {rng} (got {v!r})")
        # composition closure shared by every configuration (audit P0 3.1)
        if "fHe" in self.params:
            fHe, fimp = params.get("fHe", 0.0), params.get("fimp", 0.0)
            if (isinstance(fHe, (int, float)) and isinstance(fimp, (int, float))
                    and fHe >= 0 and fimp >= 0 and fHe + fimp >= 1.0):
                errors.append(
                    f"fHe + fimp must be < 1 (got {fHe} + {fimp}): "
                    "fuel fraction f12 = 1 - fHe - fimp would be <= 0")
        ic = params.get("icase")
        if ic is not None and ic not in (1, 2, 3, 4, 5, 6):
            errors.append(f"icase must be 1..6 (got {ic!r})")
        if self.cross is not None:
            errors.extend(self.cross(params))
        return errors


def _num(params: dict, key: str):
    """Return params[key] if it is a usable number, else None."""
    v = params.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _uses_tauE(p: dict) -> bool:
    return bool(p.get("use_tauE", 1.0))


# inclusive bounds shared by every configuration that takes these inputs
_COMMON_BOUNDS = {
    "Rw": (0.0, 1.0), "f1": (0.0, 1.0), "fHe": (0.0, 1.0), "fimp": (0.0, 1.0),
    "Sn": (0.0, None), "ST": (0.0, None), "g": (0.0, None), "fsig": (0.0, None),
}


def _tokamak_cross(p: dict) -> list[str]:
    errors = []
    if _uses_tauE(p):
        tauE = _num(p, "tauE")
        if tauE is not None and tauE <= 0:
            errors.append(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    else:
        H = _num(p, "H_fac")
        if H is not None and H <= 0:
            errors.append(f"H_fac must be > 0 when use_tauE is disabled (got {H})")
    return errors


def _mirror_cross(p: dict) -> list[str]:
    errors = []
    geom = p.get("geometry", "sin2_simple")
    if geom not in ("sin2_simple", "multi_zone"):
        errors.append(f"geometry must be 'sin2_simple' or 'multi_zone' (got {geom!r})")
    R = _num(p, "R_mirror")
    if R is not None and R <= 1.0:
        errors.append(f"R_mirror must be > 1 (got {R}): no magnetic well otherwise")
    if _uses_tauE(p):
        tauE = _num(p, "tauE")
        Te0 = _num(p, "Te0")
        if tauE is not None and tauE <= 0:
            errors.append(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
        if Te0 is not None and Te0 <= 0:
            errors.append(f"Te0 must be > 0 when use_tauE is enabled (got {Te0})")
    return errors


def _frc_cross(p: dict) -> list[str]:
    errors = []
    r_s, r_w = _num(p, "r_s"), _num(p, "r_w")
    if r_s is not None and r_w is not None and r_s >= r_w:
        errors.append(f"need r_s < r_w (got r_s={r_s}, r_w={r_w}): "
                      "separatrix must sit inside the wall (x_s < 1)")
    sep_model = p.get("sep_model")
    if sep_model is not None and sep_model not in ("superellipse", "mrr"):
        errors.append(f"sep_model must be 'superellipse' or 'mrr' (got {sep_model!r})")
    m, f_shape = _num(p, "m"), _num(p, "f_shape")
    if m is not None and f_shape is not None and abs(m / (m + 1.0) - f_shape) > 1e-6:
        errors.append(f"inconsistent m and f_shape: m={m} implies "
                      f"f_shape={m / (m + 1.0):.6f}, but f_shape={f_shape} given")
    if _uses_tauE(p):
        tauE = _num(p, "tauE")
        if tauE is not None and tauE <= 0:
            errors.append(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    return errors


def _dipole_cross(p: dict) -> list[str]:
    errors = []
    if not _uses_tauE(p):
        errors.append("dipole has no implemented self-consistent loss closure; keep use_tauE enabled")
    fac, r_ring, R_p = _num(p, "L_in_fac"), _num(p, "r_ring"), _num(p, "R_p")
    if fac is not None and r_ring is not None and R_p is not None \
            and fac * r_ring >= R_p:
        errors.append(f"need L_in = L_in_fac*r_ring < R_p "
                      f"(got {fac * r_ring} >= {R_p}): no plasma shell")
    return errors


def _stell_cross(p: dict) -> list[str]:
    errors = []
    iota = _num(p, "iota")
    if iota is not None and iota < 0:
        errors.append(f"iota must be > 0 if given (got {iota})")
    etabar = _num(p, "etabar")
    if etabar is not None and etabar == 0:
        errors.append("etabar must be != 0 (near-axis shaping required; "
                      "legacy mode removed)")
    dh, R0 = _num(p, "delta_h"), _num(p, "R0")
    if dh is not None and R0 is not None and dh >= R0:
        errors.append(f"helical excursion delta_h must be < R0 (got {dh} >= {R0})")
    if _uses_tauE(p):
        tauE = _num(p, "tauE")
        if tauE is not None and tauE <= 0:
            errors.append(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    else:
        H = _num(p, "H_fac")
        if H is not None and H <= 0:
            errors.append(f"H_fac must be > 0 when use_tauE is disabled (got {H})")
    return errors


TOKAMAK = ConfigSpec(
    name="tokamak", label="托卡马克 Tokamak",
    params=["use_tauE"] + TOKAMAK_PARAMS + ["imp_name", "H_fac"],
    required=TOKAMAK_PARAMS,
    positive=["R0", "A", "kappa", "ni0", "Ti0", "BT0", "Ip", "Zimp"],
    bounds={**_COMMON_BOUNDS, "delta": (-0.999, 0.999),
            "fT": (0.0, None), "tauE": (0.0, None), "use_tauE": (0.0, 1.0),
            "H_fac": (0.0, None)},
    cross=_tokamak_cross,
    presets=TOKAMAK_PRESETS,
    contour_fields=["Pfus", "Qfus", "Pheat", "betaN", "nbar_o_nGw", "H98"],
    scan_defaults=dict(xkey="Ti0", ykey="ni0", xmin=20, xmax=200, ymin=0.5e20, ymax=4e20),
    # default window = the classic quartet; audit P1 red lines (q >= 2 kink,
    # betaN <= 3.5 Troyon-ish, H98 <= 1.5 confinement aggressiveness) are
    # offered as OPT-IN criteria so the default POPCON matches the original.
    best_window={"ge": {"Pfus": 10, "Qfus": 1}, "le": {"nbar_o_nGw": 1, "Pheat": 100}},
    optional_window={"ge": {"q": 2}, "le": {"betaN": 3.5, "H98": 1.5}},
    contour_spec=TOKAMAK_CONTOURS,
    preset_groups=TOKAMAK_GROUPS,
    _solve=funsc,
)

MIRROR = ConfigSpec(
    name="mirror", label="磁镜 Magnetic Mirror",
    params=_MIRROR_PARAMS,
    required=["a_c", "L_c", "B_vac", "R_mirror", "ni0", "Ti0", "Te0", "tauE", "icase"],
    positive=["a_c", "L_c", "B_vac", "R_mirror", "ni0", "Ti0", "Zimp"],
    bounds={**_COMMON_BOUNDS, "use_tauE": (0.0, 1.0),
            "f_throat": (0.0, 0.5), "f_alpha": (0.0, 1.0),
            "B_expand": (1.0, None), "lnLambda": (1.0, None),
            "phi_i_over_Te": (0.0, None), "Te0": (0.0, None),
            "tauE": (0.0, None)},
    cross=_mirror_cross,
    presets=MIRROR_PRESETS,
    contour_fields=["Pfus", "Qfus", "Pheat", "beta", "Ptrans", "tau_E"],
    scan_defaults=dict(xkey="Ti0", ykey="ni0", xmin=5, xmax=200, ymin=0.5e20, ymax=6e20),
    best_window={"ge": {"Pfus": 1, "Qfus": 1}, "le": {"beta": 0.6}},
    contour_spec=MIRROR_CONTOURS,
    preset_groups=MIRROR_GROUPS,
    _solve=solve_mirror,
)

FRC = ConfigSpec(
    name="frc", label="场反位形 FRC",
    params=_FRC_PARAMS,
    required=["r_s", "l_s", "r_w", "B_e", "Ti", "Te", "tauE", "icase"],
    positive=["r_s", "l_s", "r_w", "B_e", "Ti", "Te", "Zimp"],
    bounds={**_COMMON_BOUNDS, "use_tauE": (0.0, 1.0),
            "geom_weighted": (0.0, 1.0), "m": (2.0, None),
            "tauE": (0.0, None), "f_shape": (2.0 / 3.0 - 1e-9, 1.0)},
    cross=_frc_cross,
    presets=FRC_PRESETS,
    contour_fields=["Pfus", "Qfus", "Ptrans", "beta", "tau_E", "ntau"],
    scan_defaults=dict(xkey="Ti", ykey="B_e", xmin=5, xmax=150, ymin=1, ymax=12),
    # s_param >= 2 is a SOFT kinetic-validity hint (audit P1), not a hard MHD
    # boundary; le-criteria stay empty deliberately — any Pwall cap empties the
    # compact-FRC Q>=1 region (docs/25 §8).
    best_window={"ge": {"Pfus": 1, "Qfus": 1, "s_param": 2}, "le": {}},
    contour_spec=FRC_CONTOURS,
    preset_groups=FRC_GROUPS,
    _solve=solve_frc,
    shape_fn=lambda params: frc_shape_outlines(**params),
)

DIPOLE = ConfigSpec(
    name="dipole", label="偶极场 Dipole",
    params=_DIPOLE_PARAMS,
    required=["r_ring", "R_p", "B_ring", "n0", "Ti0", "Te0", "tauE", "icase"],
    positive=["r_ring", "R_p", "B_ring", "n0", "Ti0", "Te0", "tauE", "Zimp"],
    bounds={**_COMMON_BOUNDS, "use_tauE": (0.0, 1.0),
            "L_in_fac": (1.0, None), "ring_model": (0, 1)},
    cross=_dipole_cross,
    presets=DIPOLE_PRESETS,
    contour_fields=["Pfus", "Qfus", "Ptrans", "beta_ring", "Eth", "ntau"],
    scan_defaults=dict(xkey="Ti0", ykey="n0", xmin=5, xmax=100, ymin=1e20, ymax=2e21),
    best_window={"ge": {"Pfus": 1, "Qfus": 1}, "le": {"beta_in": 1.0}},
    contour_spec=DIPOLE_CONTOURS,
    preset_groups=DIPOLE_GROUPS,
    _solve=solve_dipole,
)

STELLARATOR = ConfigSpec(
    name="stellarator", label="仿星器 Stellarator",
    params=_STELL_PARAMS,
    # etabar IS required (near-axis shaping); rc/zs/Vp_override/Sw_override/iota
    # are optional overrides.
    required=[p for p in _STELL_PARAMS
              if p not in ("f_ren", "iota", "delta_h", "imp_name", "H_fac",
                            "rc", "zs", "Vp_override", "Sw_override", "shape")],
    positive=["R0", "a", "N_fp", "ni0", "Ti0", "B0",
              "Zimp", "f_ren"],
    bounds={**_COMMON_BOUNDS, "delta_h": (0.0, None), "N_fp": (1.0, None),
            "fT": (0.0, None), "tauE": (0.0, None), "use_tauE": (0.0, 1.0),
            "H_fac": (0.0, None),
            "Vp_override": (0.0, None), "Sw_override": (0.0, None)},
    cross=_stell_cross,
    presets=STELL_PRESETS,
    contour_fields=["Pfus", "Qfus", "Pheat", "betaT", "nbar_o_Sudo", "H_ISS04"],
    scan_defaults=dict(xkey="Ti0", ykey="ni0", xmin=5, xmax=40, ymin=0.5e20, ymax=3e20),
    # H_ISS04 <= 1.5 (audit P1): exposes how aggressive the assumed tauE is
    # relative to the ISS04 database; editable in the UI threshold panel.
    best_window={"ge": {"Pfus": 10, "Qfus": 1},
                 "le": {"nbar_o_Sudo": 1.0, "betaT": 0.05, "H_ISS04": 1.5}},
    contour_spec=STELL_CONTOURS,
    preset_groups=STELL_GROUPS,
    _solve=solve_stellarator,
    shape_fn=lambda params: section_outlines(**params),
)

for _p in TOKAMAK_PRESETS.values():
    _p.setdefault("use_tauE", 1.0)
    _p.setdefault("f_aux_e", 0.5)
    _p.setdefault("H_fac", 1.0)
for _p in MIRROR_PRESETS.values():
    _p.setdefault("use_tauE", 1.0)
    _p.setdefault("geometry", "sin2_simple")
    _p.setdefault("f_aux_e", 0.5)
    _p.setdefault("B_expand", 100.0)
    _p.setdefault("lnLambda", 17.0)
    _p.setdefault("phi_i_over_Te", 0.0)
for _p in FRC_PRESETS.values():
    _p.setdefault("use_tauE", 1.0)
    _p.setdefault("geom_weighted", 0.0)
for _p in STELL_PRESETS.values():
    if "a" not in _p and "A" in _p and "R0" in _p:
        _p["a"] = _p["R0"] / _p["A"]
    _p.pop("A", None)
    _p.setdefault("use_tauE", 1.0)
    _p.setdefault("f_aux_e", 0.5)
    _p.setdefault("H_fac", 1.0)
    _p.setdefault("iota", 0.0)            # 0 = use geometric transform
    _p.setdefault("Vp_override", 0.0)     # 0 = use geometric plasma volume
    _p.setdefault("Sw_override", 0.0)     # 0 = use geometric wall surface
for _p in DIPOLE_PRESETS.values():
    _p.setdefault("use_tauE", 1.0)
    _p.setdefault("ring_model", 0)

REGISTRY = {c.name: c for c in (TOKAMAK, MIRROR, FRC, DIPOLE, STELLARATOR)}


def get(config: str) -> ConfigSpec:
    if config not in REGISTRY:
        raise KeyError(f"unknown configuration {config!r}; have {list(REGISTRY)}")
    return REGISTRY[config]
