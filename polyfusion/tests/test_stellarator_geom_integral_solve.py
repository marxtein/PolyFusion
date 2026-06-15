"""solve_stellarator computes Vp/Sw from the boundary integral (override optional).

For a config with an explicit Fourier ``shape`` and NO override, the plasma
volume and wall area used in the power account equal the exact integral of that
same boundary (frontend shape == backend power geometry).  A measured machine
keeps its Vp/Sw overrides; the integral is still reported as Vp_geom/Sw_geom.

Run: python polyfusion/tests/test_stellarator_geom_integral_solve.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets  # noqa: E402
from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import (  # noqa: E402
    boundary_metrics, _shape_boundary_fn)

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _base(p):
    keys = ["R0", "A", "N_fp", "Sn", "ST", "ni0", "Ti0", "fT", "fsig", "f1",
            "B0", "tauE", "fHe", "fimp", "Zimp", "Rw", "g", "icase"]
    kw = {k: p[k] for k in keys if k in p}
    for o in ["delta_h", "iota", "f_ren", "etabar", "f_aux_e", "H_fac",
              "use_tauE"]:
        if o in p:
            kw[o] = p[o]
    return kw


def main():
    presets, _ = load_presets("stellarator")
    p = presets["W7-X"]
    shape = p["shape"]
    a = p["R0"] / p["A"]
    bfn, nfp = _shape_boundary_fn(p["R0"], a, shape)
    V_int, S_int = boundary_metrics(bfn, nfp, g=p["g"])

    # shape + NO override -> Vp/Sw come from the boundary integral (consistent)
    r = solve_stellarator(**_base(p), shape=shape, Vp_override=0.0, Sw_override=0.0)
    ok(abs(r.Vp - V_int) < 1e-6 * V_int,
       f"no-override: Vp == boundary integral ({r.Vp:.3f} == {V_int:.3f})")
    ok(abs(r.Sw - S_int) < 1e-6 * S_int,
       f"no-override: Sw == boundary integral ({r.Sw:.3f} == {S_int:.3f})")
    ok(r.geom_is_measured == 0.0, "no-override: geom_is_measured == 0")

    # measured machine: overrides win, integral is the reported estimate
    r2 = solve_stellarator(**_base(p), shape=shape,
                           Vp_override=p["Vp_override"], Sw_override=p["Sw_override"])
    ok(r2.Vp == p["Vp_override"], f"override: Vp == measured ({r2.Vp})")
    ok(abs(r2.Vp_geom - V_int) < 1e-6 * V_int,
       f"override: Vp_geom == boundary integral estimate ({r2.Vp_geom:.3f})")
    ok(r2.geom_is_measured == 1.0, "override: geom_is_measured == 1")

    print("\nRESULT:", "GEOM INTEGRAL SOLVE PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
