"""Every flux surface must lie INSIDE its section's wall polygon.

Bug: machine-boundary cross-sections nested their flux surfaces and built the
wall layer by scaling from (R0, 0), but the n!=0 boundary harmonics shift each
toroidal cut away from R0 — for W7-X (phi=0) and HSX the point (R0, 0) is OUTSIDE
the cut's boundary, so the nested surfaces fanned out and many flux points landed
OUTSIDE the wall ("磁面在壁外面").  Fix: scale from the true section centroid.

Run: python polyfusion/tests/test_stellarator_wall_containment.py
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


def _inside(px, py, R, Z):
    R = np.asarray(R); Z = np.asarray(Z); n = len(R); inside = False; j = n - 1
    for i in range(n):
        if ((Z[i] > py) != (Z[j] > py)) and (
                px < (R[j] - R[i]) * (py - Z[i]) / (Z[j] - Z[i] + 1e-30) + R[i]):
            inside = not inside
        j = i
    return inside


def main():
    presets, _ = load_presets("stellarator")
    for name, p in presets.items():
        if name.startswith("_"):
            continue
        sh = section_outlines(**p)
        for s in sh["sections"]:
            wR, wZ = s["wall"]["R"], s["wall"]["Z"]
            outside = 0
            for su in s["surfaces"]:               # every nested flux surface
                for x, y in zip(su["R"], su["Z"]):
                    if not _inside(x, y, wR, wZ):
                        outside += 1
            ok(outside == 0,
               f"{name}/{s['label']}: all flux-surface points inside wall "
               f"({outside} outside)  [{sh['metric_mode']}]")

    print("\nRESULT:", "WALL CONTAINMENT PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
