"""Real-machine stellarator presets must anchor wall area with Sw_override.

W7-X / LHD / HSX / CFQS are small/heliotron devices the single-harmonic
near-axis model cannot represent: its elongation profile is extreme (HSX
elongation ~384), so the geometric wall area Sw_geom is unphysical.  These
presets supply a published/estimated Sw_override [m^2] so Pwall = (Pfus+Pheat)/Sw
is anchored to the real plasma geometry.  (Concept reactors HELIAS / NAE-QA are
pure near-axis and keep Sw_override = 0 by design.)

Run: python polyfusion/tests/test_stellarator_presets_pwall.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.io import run_preset  # noqa: E402

PASS = True

# rough sanity envelopes for the measured wall area [m^2]
MEASURED = {"W7-X": (80, 200), "LHD": (60, 200), "HSX": (3, 30), "CFQS": (4, 40)}
CONCEPTS = ["HELIAS", "NAE-QA"]


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    for name in list(MEASURED) + CONCEPTS:
        o = run_preset(name, "stellarator")["outputs"]
        ok(o.get("valid") == 1.0, f"{name}: valid == 1")
        ok(
            math.isfinite(o["Pwall"]) and o["Pwall"] >= 0,
            f"{name}: finite sane Pwall ({o['Pwall']:.4g} MW/m^2)",
        )

    for name, (lo, hi) in MEASURED.items():
        o = run_preset(name, "stellarator")["outputs"]
        Sw = o["Sw"]
        ok(
            lo <= Sw <= hi,
            f"{name}: wall area anchored to measured value ({Sw:.1f} m^2 in [{lo},{hi}])",
        )
        # Pwall consistent with the anchored area
        expect = (o["Pfus"] + o["Pheat"]) / Sw
        ok(
            abs(o["Pwall"] - expect) < 1e-9 * max(abs(expect), 1.0),
            f"{name}: Pwall == (Pfus+Pheat)/Sw",
        )

    print("\nRESULT:", "PRESET PWALL CHECKS PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
