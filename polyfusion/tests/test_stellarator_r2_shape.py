"""section_outlines second-order (bean/crescent) shape rendering.

The first-order near-axis cross-section is a pure ellipse, which is centrally
symmetric about the axis: P(theta+pi) - c = -(P(theta) - c).  The second-order
(r^2) terms break that symmetry, producing the bean / crescent shapes of real
stellarators.  This test checks that section_outlines renders the second-order
shape (non-central-symmetry) while preserving its dict contract, and that the
power-account geometry (stellarator_geometry_metrics) is untouched.

Run: python polyfusion/tests/test_stellarator_r2_shape.py
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.stellarator import (  # noqa: E402
    section_outlines,
    stellarator_geometry_metrics,
)

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _central_asymmetry(R, Z):
    """Max |(P(i)-c) + (P(i+n/2)-c)| over the unique boundary vertices."""
    R = np.asarray(R[:-1], dtype=float)
    Z = np.asarray(Z[:-1], dtype=float)
    n = R.size
    cR, cZ = R.mean(), Z.mean()
    h = n // 2
    dR = (R - cR) + (np.roll(R, -h) - cR)
    dZ = (Z - cZ) + (np.roll(Z, -h) - cZ)
    scale = np.max(np.hypot(R - cR, Z - cZ))
    return float(np.max(np.hypot(dR, dZ)) / scale)


def main():
    sh = section_outlines(R0=18.0, A=10.0, N_fp=3, delta_h=0.81, etabar=0.08, B2c=0.0)
    # contract preserved
    for k in ("mode", "metric_mode", "a", "g", "sections", "axis"):
        ok(k in sh, f"section dict has key '{k}'")
    for sec in sh["sections"]:
        for k in ("label", "elong", "R", "Z", "surfaces", "wall"):
            ok(k in sec, f"section '{sec.get('label')}' has key '{k}'")
        ok(len(sec["surfaces"]) >= 2, "nested surfaces present")
        ok(
            abs(sec["surfaces"][-1]["rho"] - 1.0) < 1e-12,
            "outermost nested surface is the boundary (rho=1)",
        )

    # at least one cut must show a genuinely non-elliptic (bean) boundary
    asym = max(_central_asymmetry(s["R"], s["Z"]) for s in sh["sections"])
    ok(asym > 1e-3, f"r2 boundary is non-elliptic (central asymmetry {asym:.2e})")
    ok(
        sh["metric_mode"] == "near-axis-r2",
        f"metric_mode flags second order ({sh['metric_mode']})",
    )

    # the display cap bounds the second-order distortion (no runaway / self-
    # intersecting cartoon): a_disp <= a and asymmetry stays O(cap)
    ok(
        sh["a_disp"] <= sh["a"] + 1e-12,
        f"display radius bounded (a_disp={sh['a_disp']:.3f} <= a={sh['a']:.3f})",
    )
    ok(asym < 1.0, f"bean distortion bounded by display cap ({asym:.2e} < 1)")

    # B2c (second-order field shaping) genuinely changes the cross-section
    sh2 = section_outlines(R0=18.0, A=10.0, N_fp=3, delta_h=0.81, etabar=0.08, B2c=0.5)
    d = max(
        np.max(np.abs(np.array(s1["R"]) - np.array(s2["R"])))
        for s1, s2 in zip(sh["sections"], sh2["sections"])
    )
    ok(d > 1e-4, f"B2c alters the boundary shape (max dR {d:.2e})")

    # POWER ACCOUNT UNTOUCHED: geometry metrics stay first-order area-preserving
    g = stellarator_geometry_metrics(
        R0=18.0, a=1.8, N_fp=3, rc=[18.0, 0.81], zs=[0.0, -0.81], etabar=0.08
    )
    a = 18.0 / 10.0
    ok(
        abs(g["A_flux"] - math.pi * a**2) < 1e-9,
        "A_flux still first-order pi a^2 (0-D power account unchanged)",
    )

    print("\nRESULT:", "STELLARATOR R2 SHAPE PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
