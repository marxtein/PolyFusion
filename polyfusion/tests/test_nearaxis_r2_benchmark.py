"""Second-order (O(r^2)) near-axis geometry verification against pyQSC.

Run: python polyfusion/tests/test_nearaxis_r2_benchmark.py

The golden file ``nearaxis_r2_golden.json`` holds the second-order Frenet-frame
coefficients X20/X2c/X2s, Y20/Y2c/Y2s, Z20/Z2c/Z2s for the published vacuum
stellarator-symmetric examples of Landreman & Sengupta, J. Plasma Phys. 85
(2019) 905850006 ("Direct construction of optimized stellarator shapes, Part
2"), sections 5.1, 5.2 and 5.4.  It was generated from pyQSC (Qsc order='r2')
through a numpy-only scipy shim whose O(r^1) output reproduces this repo's
validated near-axis solver (test_nearaxis_benchmark.py) to < 1e-13 — so the
O(r^2) reference is trustworthy.  See docs/39 for the provenance trail.

These O(r^2) coefficients are what give real stellarators their bean / crescent
flux-surface cross-sections (pure ellipses only appear at O(r^1)).
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.nearaxis import solve_near_axis  # noqa: E402

PASS = True
GOLDEN = os.path.join(os.path.dirname(__file__), "nearaxis_r2_golden.json")


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    ref = json.load(open(GOLDEN))
    fields = ["X20", "X2c", "X2s", "Y20", "Y2c", "Y2s", "Z20", "Z2c", "Z2s"]

    for name, d in ref.items():
        if name.startswith("_"):
            continue
        na = solve_near_axis(d["rc"], d["zs"], d["nfp"], d["etabar"],
                             nphi=d["nphi"], order="r2", B2c=d["B2c"])
        ok(na.second_order is not None, f"{name}: second_order payload present")
        so = na.second_order
        ok(abs(so.B2c - d["B2c"]) < 1e-15, f"{name}: B2c echoed ({so.B2c})")

        worst = 0.0
        for fld in fields:
            got = np.asarray(getattr(so, fld))
            want = np.asarray(d[fld])
            dev = float(np.max(np.abs(got - want)))
            worst = max(worst, dev)
            ok(dev < 1e-9, f"{name}: {fld} matches pyQSC (max dev {dev:.2e})")
        ok(worst < 1e-9, f"{name}: all r2 coeffs within 1e-9 (worst {worst:.2e})")

    # ---- first-order behaviour is the DEFAULT and unchanged ----
    na1 = solve_near_axis([1, 0.045], [0, -0.045], 3, -0.9, nphi=63)
    ok(na1.second_order is None,
       "order defaults to r1: no second_order payload")

    # ---- second-order area-preserving sanity: at small r the r2 surface
    #      reduces to the r1 ellipse to O(r) ----
    na = solve_near_axis([1, 0.155, 0.0102], [0, 0.154, 0.0111], 2, 0.64,
                         nphi=61, order="r2", B2c=-0.00322)
    th = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    j = 0
    r_small = 1e-4
    so = na.second_order
    X_r2 = (r_small * na.X1c[j] * np.cos(th)
            + r_small**2 * (so.X20[j] + so.X2c[j] * np.cos(2 * th)
                            + so.X2s[j] * np.sin(2 * th)))
    X_r1 = r_small * na.X1c[j] * np.cos(th)
    ok(np.max(np.abs(X_r2 - X_r1)) < 1e-6,
       "r2 X-shape -> r1 ellipse as r->0 (second order is a correction)")

    print("\nRESULT:", "NEAR-AXIS R2 BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
