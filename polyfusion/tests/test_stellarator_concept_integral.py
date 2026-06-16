"""Concept stack (near-axis, no shape) also gets Vp/Sw from the EXACT boundary
integral — frontend shape == backend power geometry for concepts too.

Before this change the concept power account used the analytic Pappus volume
pi*a^2 * L_ax.  Now ``solve_stellarator`` integrates the SAME near-axis boundary
the UI draws (full-size first-order body + bounded second-order bean wobble, the
displayed capped-r2 surface), via ``boundary_metrics``.  The raw uncapped r2
surface self-intersects at r = a (the near-axis expansion is invalid there — the
display caps it for exactly that reason), so the physics integrates the drawable
capped-r2 bean, which keeps the second-order character while staying a simple,
correctly-sized (~pi*a^2*L_ax) closed surface.

Run: python polyfusion/tests/test_stellarator_concept_integral.py
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import (  # noqa: E402
    boundary_metrics, _nearaxis_boundary_fn, section_outlines)

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _concave_frac(R, Z):
    R = np.asarray(R, float); Z = np.asarray(Z, float)
    if R[0] == R[-1] and Z[0] == Z[-1]:
        R, Z = R[:-1], Z[:-1]
    n = R.size; cr = []
    for i in range(n):
        ax, ay = R[(i+1) % n]-R[i], Z[(i+1) % n]-Z[i]
        bx, by = R[(i+2) % n]-R[(i+1) % n], Z[(i+2) % n]-Z[(i+1) % n]
        cr.append(ax*by - ay*bx)
    cr = np.array(cr); sgn = np.sign(np.sum(cr))
    return float(np.mean(np.sign(cr) != sgn))


def main():
    # a near-axis CONCEPT (no shape): R0=18, A=10 (a=1.8), helical 3-period axis
    cfg = dict(R0=18.0, A=10.0, N_fp=3, delta_h=0.9, etabar=0.05,
               Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5,
               B0=5.0, tauE=1.0, fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.1,
               icase=1)

    bfn, nfp = _nearaxis_boundary_fn(R0=18.0, A=10.0, N_fp=3,
                                     delta_h=0.9, etabar=0.05)
    V_int, S_int, _ = boundary_metrics(bfn, nfp, g=0.1)

    r = solve_stellarator(**cfg)
    # (a) concept Vp/Sw == exact integral of the near-axis boundary (identity)
    ok(abs(r.Vp - V_int) < 1e-6 * V_int,
       f"concept Vp == boundary integral ({r.Vp:.3f} == {V_int:.3f})")
    ok(abs(r.Sw - S_int) < 1e-6 * S_int,
       f"concept Sw == boundary integral ({r.Sw:.3f} == {S_int:.3f})")
    ok(r.geom_is_measured == 0.0, "concept: geom_is_measured == 0")

    # (b) it genuinely moved off the analytic Pappus volume (bean correction),
    #     but stays a sane fraction of it (no blow-up, no collapse)
    pappus = math.pi * 1.8**2 * r.L_ax
    ratio = r.Vp / pappus
    ok(abs(ratio - 1.0) > 1e-3,
       f"concept Vp differs from Pappus pi*a^2*L_ax ({ratio:.4f})")
    ok(0.80 < ratio < 1.0,
       f"concept Vp is a sane fraction of Pappus ({ratio:.4f}) — no r2 blow-up")

    # (c) frontend/backend consistency: the boundary the integral uses is a bean
    #     (second-order character preserved), matching the displayed phi=0 cut
    Rb, Zb = bfn(0.0)
    cf_int = _concave_frac(Rb, Zb)
    disp = section_outlines(**{k: cfg[k] for k in
                               ("R0", "A", "N_fp", "delta_h", "etabar", "g")})
    Rd = disp["sections"][0]["R"]; Zd = disp["sections"][0]["Z"]
    cf_disp = _concave_frac(Rd, Zd)
    ok(cf_int < 0.5, f"integral boundary is simple (concave {cf_int:.2f} < 0.5)")
    ok(abs(cf_int - cf_disp) < 0.1,
       f"integral boundary shape matches display (concave {cf_int:.2f} ~ {cf_disp:.2f})")

    # (d) SHAPE ENTERS POWER: at FIXED axis (-> fixed L_ax) and FIXED a, changing
    #     the shaping etabar changes the drawn boundary, hence Vp (boundary
    #     integral), hence Pfus.  This pins the report's corrected claim "form
    #     enters the power account through Vp" (docs/40, docs/41) — it would FAIL
    #     if Vp ever reverted to the analytic shape-independent pi*a^2*L_ax.
    lo = solve_stellarator(**{**cfg, "etabar": 0.04})
    hi = solve_stellarator(**{**cfg, "etabar": 0.05})
    ok(abs(lo.L_ax - hi.L_ax) < 1e-9,
       f"axis (L_ax) unchanged by etabar ({lo.L_ax:.3f}=={hi.L_ax:.3f})")
    ok(abs(lo.Vp - hi.Vp) / hi.Vp > 0.01,
       f"shape (etabar) moves Vp at fixed axis: {lo.Vp:.1f} vs {hi.Vp:.1f}")
    ok(abs(lo.Pfus - hi.Pfus) / hi.Pfus > 0.01,
       f"=> shape moves Pfus at fixed a/L_ax: {lo.Pfus:.1f} vs {hi.Pfus:.1f} MW")

    print("\nRESULT:", "CONCEPT INTEGRAL PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
