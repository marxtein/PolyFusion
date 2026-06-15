"""New near-axis CONCEPT presets from the published Landreman/pyQSC library.

precise-QA / precise-QH are the Landreman-Paul (2022) precise-quasisymmetry
near-axis configurations; QH-nfp3 is the pyQSC '2022 QH nfp3' vacuum config.
They are added as concept presets (explicit rc/zs + etabar, no Fourier shape)
scaled to a reactor R0 by the same rule the existing NAE-QA preset uses
(rc=R0*rc_pub, etabar=|etabar_pub|/R0).  The near-axis solver reproduces their
PUBLISHED on-axis rotational transform, which this test pins.

Run: python polyfusion/tests/test_stellarator_new_presets.py
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets  # noqa: E402
from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import section_outlines  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


SOLVE_KEYS = ["R0", "A", "N_fp", "Sn", "ST", "ni0", "Ti0", "fT", "fsig", "f1",
              "B0", "tauE", "fHe", "fimp", "Zimp", "Rw", "g", "icase", "delta_h",
              "iota", "f_ren", "etabar", "f_aux_e", "H_fac", "use_tauE",
              "rc", "zs", "Vp_override", "Sw_override"]

# published on-axis iota for the underlying near-axis configs (nfp-independent of
# the reactor scaling): precise QA ~0.42, precise QH ~1.24, 2022 QH nfp3 ~1.25.
EXPECT = {"precise-QA": (2, 0.42), "precise-QH": (4, 1.24), "QH-nfp3": (3, 1.25)}


def main():
    presets, groups = load_presets("stellarator")
    for name, (nfp, iota_pub) in EXPECT.items():
        ok(name in presets, f"{name}: preset present")
        if name not in presets:
            continue
        p = presets[name]
        ok(int(p["N_fp"]) == nfp, f"{name}: N_fp == {nfp}")
        ok("shape" not in p, f"{name}: concept preset (no Fourier shape)")
        ok(isinstance(p.get("rc"), list) and isinstance(p.get("zs"), list),
           f"{name}: carries explicit rc/zs near-axis axis")

        r = solve_stellarator(**{k: p[k] for k in SOLVE_KEYS if k in p})
        ok(abs(r.iota_geom - iota_pub) < 0.05,
           f"{name}: iota_geom {r.iota_geom:.3f} ~ published {iota_pub}")
        ok(math.isfinite(r.Pfus) and r.Pfus > 0 and math.isfinite(r.betaT),
           f"{name}: finite positive power point (Pfus={r.Pfus:.0f} MW)")

        sh = section_outlines(**p)
        ok(sh["metric_mode"] == "near-axis-r2",
           f"{name}: renders as second-order near-axis bean")
        ok(len(sh.get("frames", [])) >= 12,
           f"{name}: has phase-slider frames ({len(sh.get('frames', []))})")
        # strictly nested at phi=0
        from matplotlib.path import Path
        s = sh["sections"][0]["surfaces"]
        bad = 0
        for i in range(len(s) - 1):
            poly = Path(np.column_stack([s[i+1]["R"], s[i+1]["Z"]]))
            bad += int((~poly.contains_points(
                np.column_stack([s[i]["R"], s[i]["Z"]]))).sum())
        ok(bad == 0, f"{name}: phi=0 surfaces strictly nested")

    # listed in a preset group so the UI shows them
    allgrouped = sum(groups.values(), []) if groups else []
    for name in EXPECT:
        ok(name in allgrouped, f"{name}: appears in a preset group")

    print("\nRESULT:", "NEW PRESETS PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
