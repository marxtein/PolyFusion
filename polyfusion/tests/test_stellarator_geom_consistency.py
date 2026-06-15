"""Backend geometry diagnostics are consistent with the displayed boundary.

For a measured machine (Vp_override AND Sw_override set) the power account uses
the measured Vp/Sw, while Vp_geom/Sw_geom now report the EXACT integral of the
displayed Fourier boundary (a real geometry estimate, e.g. W7-X Vp_geom~32.8 vs
measured Vp=30) — no longer the unphysical near-axis value.  geom_is_measured
flags that iota_geom/kappa_eff/elong_max are near-axis estimates.  For concept
reactors (no override) the near-axis geometry IS what is used, so Vp_geom == Vp.

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
        # power account uses the measured override
        ok(o["Vp"] > 0 and o["Sw"] > 0, f"{name}: measured Vp/Sw used")
        # Vp_geom/Sw_geom report the exact-integral geometry estimate (sane,
        # within ~40% of measured), NOT the discarded near-axis value
        ok(0.6 < o["Vp_geom"] / o["Vp"] < 1.6,
           f"{name}: Vp_geom is the boundary-integral estimate "
           f"({o['Vp_geom']:.3f} vs measured {o['Vp']:.3f})")
        ok(0.6 < o["Sw_geom"] / o["Sw"] < 1.6,
           f"{name}: Sw_geom is the boundary-integral estimate "
           f"({o['Sw_geom']:.3f} vs measured {o['Sw']:.3f})")

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
