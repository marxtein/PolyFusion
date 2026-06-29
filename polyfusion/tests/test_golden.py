"""Validate the Python core against golden values from the JS reference.

Golden values in ``golden.json`` are produced by running the authors' own
JS ``funsc`` (extracted from ``etsc.html``) over representative cases
covering reactions icase = 1..5.  Geometry/density quantities must match to
machine precision; reactivity-coupled quantities are allowed a small grid
tolerance (linspace vs JS accumulation differ in the energy grid).
"""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion import funsc  # noqa: E402

HERE = os.path.dirname(__file__)
GOLDEN = json.load(open(os.path.join(HERE, "golden.json"), encoding="utf-8"))

# Tolerances (relative) per quantity class.
TIGHT = 1e-9  # grid-independent (pure algebra)
LOOSE = 2e-2  # reactivity-coupled (depend on the energy-grid quadrature)

_LOOSE_KEYS = {"Pfus", "Pn", "Qfus", "Pheat", "Pwall", "H98", "HST"}
# keys present in golden JSON that map directly to Result fields
_SKIP = {"strcase"}


@pytest.mark.parametrize("name", list(GOLDEN.keys()))
def test_matches_js_reference(name):
    case = GOLDEN[name]
    res = funsc(*case["params"]).as_dict()
    ref = case["result"]
    for key, gold in ref.items():
        if key in _SKIP or key not in res:
            continue
        got = res[key]
        if gold is None or (isinstance(gold, float) and math.isnan(gold)):
            continue
        rtol = LOOSE if key in _LOOSE_KEYS else TIGHT
        assert got == pytest.approx(gold, rel=rtol, abs=1e-12), (
            f"{name}.{key}: python={got!r} js={gold!r} (rtol={rtol})"
        )
