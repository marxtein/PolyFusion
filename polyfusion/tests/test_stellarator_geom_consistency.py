"""Backend geometry diagnostics must be consistent with the values actually used.

For measured machines (Vp_override AND Sw_override set) the single-harmonic
near-axis geometry is discarded, so reporting its near-axis Vp_geom/Sw_geom
(e.g. W7-X Sw_geom=268 vs Sw used=128) is misleading.  The reported geometric
volume/wall are set to the values actually used, and a ``geom_is_measured`` flag
lets the UI label the remaining near-axis estimates (iota_geom/kappa_eff/
elong_max) as estimates rather than the machine's real geometry.

Run: python polyfusion/tests/test_stellarator_geom_consistency.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.io import run_preset  # noqa: E402

PASS = True
MACHINES = ["W7-X", "LHD", "HSX", "CFQS"]
CONCEPTS = ["HELIAS", "NAE-QA"]


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    for name in MACHINES:
        o = run_preset(name, "stellarator")["outputs"]
        ok(o["geom_is_measured"] == 1.0, f"{name}: geom_is_measured == 1")
        ok(abs(o["Vp_geom"] - o["Vp"]) < 1e-9 * max(o["Vp"], 1),
           f"{name}: Vp_geom == Vp used ({o['Vp_geom']:.3f} == {o['Vp']:.3f})")
        ok(abs(o["Sw_geom"] - o["Sw"]) < 1e-9 * max(o["Sw"], 1),
           f"{name}: Sw_geom == Sw used ({o['Sw_geom']:.3f} == {o['Sw']:.3f})")

    for name in CONCEPTS:
        o = run_preset(name, "stellarator")["outputs"]
        ok(o["geom_is_measured"] == 0.0, f"{name}: geom_is_measured == 0 (near-axis)")
        # concept reactors: geometric volume IS what is used
        ok(abs(o["Vp_geom"] - o["Vp"]) < 1e-9 * max(o["Vp"], 1),
           f"{name}: Vp_geom == Vp ({o['Vp_geom']:.3f})")

    print("\nRESULT:", "GEOM CONSISTENCY PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
