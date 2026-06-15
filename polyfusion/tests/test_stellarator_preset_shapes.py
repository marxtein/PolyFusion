"""Every stellarator preset must render a sane, non-degenerate cross-section.

Regression guard for the "几何很怪" bug: measured machines (W7-X/LHD/HSX/CFQS)
have extreme single-harmonic near-axis elongation, which (a) before the fix made
the r2 display radius collapse so the plasma drew as a microscopic speck, and
(b) self-intersected.  The shape view must draw the first-order body at the real
minor radius a (correct SIZE) with only a BOUNDED second-order wobble, so every
preset shows a recognizable, simple (non-self-intersecting) cross-section.

Run: python polyfusion/tests/test_stellarator_preset_shapes.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets  # noqa: E402
from polyfusion.configs.stellarator import section_outlines  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _self_intersections(R, Z):
    R = np.asarray(R[:-1], float)
    Z = np.asarray(Z[:-1], float)
    n = R.size
    P = list(zip(R, Z))

    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) > (q[1] - p[1]) * (r[0] - p[0])

    c = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            a, b, cc, d = P[i], P[(i + 1) % n], P[j], P[(j + 1) % n]
            if ccw(a, cc, d) != ccw(b, cc, d) and ccw(a, b, cc) != ccw(a, b, d):
                c += 1
    return c


def main():
    presets, _ = load_presets("stellarator")
    for name, p in presets.items():
        if name.startswith("_"):
            continue
        sh = section_outlines(**p)
        a = sh["a"]
        for s in sh["sections"]:
            cR = float(np.mean(s["R"][:-1]))
            cZ = float(np.mean(s["Z"][:-1]))
            extent = float(np.max(np.hypot(np.array(s["R"]) - cR,
                                           np.array(s["Z"]) - cZ)))
            # plasma drawn at the real minor radius, NOT a microscopic speck
            ok(extent >= 0.4 * a,
               f"{name}/{s['label']}: cross-section sized to a "
               f"(extent {extent:.3f} >= 0.4*a={0.4*a:.3f})")
            # simple closed curve, no self-intersection
            si = _self_intersections(s["R"], s["Z"])
            ok(si == 0,
               f"{name}/{s['label']}: boundary is a simple curve (self-int {si})")

    print("\nRESULT:", "PRESET SHAPE CHECKS PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
