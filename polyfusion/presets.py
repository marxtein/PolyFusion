"""Tokamak machine presets.

ENN concept designs come from ``scan2d_sc.m`` / ``etsc.html``; real-device
entries use published headline parameters (R0, a=R0/A, B0, Ip, kappa, delta)
with representative 0-D density / temperature / confinement starting points
(``ni0`` in m^-3; profiles default to Sn=0.5, ST=1.0).  These are illustrative
operating points for POPCON scoping, not validated equilibria.

The preset data itself now lives in ``presets/tokamak.json`` (with any
``~/.polyfusion/presets/tokamak.json`` merged on top) so non-developers can add
presets by editing JSON; :func:`polyfusion.presets_io.load_presets` loads it.
"""

from .presets_io import load_presets

# (presets dict, display-grouping dict) loaded from JSON data files.
PRESETS, PRESET_GROUPS = load_presets("tokamak")

# Canonical parameter order accepted positionally by funsc().
PARAM_ORDER = [
    "R0",
    "A",
    "kappa",
    "delta",
    "Sn",
    "ST",
    "ni0",
    "Ti0",
    "fT",
    "fsig",
    "f1",
    "BT0",
    "Ip",
    "tauE",
    "fHe",
    "fimp",
    "Zimp",
    "Rw",
    "g",
    "icase",
]
