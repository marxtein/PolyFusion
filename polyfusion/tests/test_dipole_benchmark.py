"""Dipole module verification (docs/26): exact dipole-geometry analytics.

Run: python polyfusion/tests/test_dipole_benchmark.py

1. GEOMETRY identity: the point-dipole shell volume V(L)=64*pi*L^3/105 is
   checked against an INDEPENDENT numerical triple integral of the region
   {r < L cos^2(lambda)} in spherical coordinates.
2. PROFILE theorem: the implemented profiles must satisfy the marginal-
   stability slope d ln p/d ln L = -20/3 (delta(pU^5/3)=0 with U~L^4) and
   the local beta must decay as beta ~ L^(-2/3) (p~L^-20/3 over B^2~L^-6).
3. LDX-scale anchor: at LDX parameters (r_ring=0.3 m, R_p=2 m) the plasma
   volume must be O(10) m^3 (5-m vacuum vessel) — order check.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_dipole  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---- 1. shell volume: analytic vs independent triple integral ----
    Lval = 1.7
    lam = np.linspace(-math.pi / 2, math.pi / 2, 4001)
    # V = Int 2*pi * Int_0^{L cos^2 lam} r^2 dr * cos(lam) dlam
    integrand = 2 * math.pi * (Lval * np.cos(lam) ** 2) ** 3 / 3 * np.cos(lam)
    V_num = float(np.trapezoid(integrand, lam))
    V_ana = 64 * math.pi * Lval**3 / 105
    ok(
        abs(V_num - V_ana) / V_ana < 1e-6,
        f"shell volume analytic={V_ana:.5f} vs numeric={V_num:.5f} m^3",
    )

    # ---- 2. profile theorem identities through the module ----
    r = solve_dipole(
        r_ring=1.0,
        R_p=10.0,
        B_ring=10.0,
        n0=3e20,
        Ti0=30.0,
        Te0=20.0,
        tauE=5.0,
        icase=2,
    )
    ok(abs(r.p_slope + 20.0 / 3.0) < 1e-12, "p-slope = -20/3 (pU^{5/3} marginal)")
    # beta_out/beta_in must equal (L_out/L_in)^(-2/3) exactly
    ratio = r.beta_out / r.beta_in
    expect = (10.0 / r.L_in) ** (-2.0 / 3.0)
    ok(
        abs(ratio - expect) / expect < 1e-9,
        f"beta decay L^(-2/3): ratio={ratio:.6f} vs (L_out/L_in)^(-2/3)={expect:.6f}",
    )
    # flux-tube volume ratio U ~ L^4
    ok(
        abs(r.U_ratio - (10.0 / r.L_in) ** 4) / r.U_ratio < 1e-12,
        "U_ratio = (L_out/L_in)^4",
    )
    # field decay B ~ L^-3
    ok(
        abs(r.B_in / r.B_out - (10.0 / r.L_in) ** 3) < 1e-6,
        "B_in/B_out = (L_out/L_in)^3",
    )

    # ---- 3. LDX-scale anchor ----
    ldx = solve_dipole(
        r_ring=0.3, R_p=2.0, B_ring=2.0, n0=1e18, Ti0=0.5, Te0=0.5, tauE=0.1, icase=2
    )
    ok(
        5.0 < ldx.Vp < 30.0,
        f"LDX-scale plasma volume {ldx.Vp:.1f} m^3 (5-m vessel order)",
    )
    ok(
        ldx.beta_in < 0.05,
        f"LDX-scale low beta ({ldx.beta_in:.4f}) — experiment regime",
    )

    print("\nRESULT:", "DIPOLE BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
