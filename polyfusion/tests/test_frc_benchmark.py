"""FRC module verification (docs/25): rigid-rotor analytics + LSX anchor.

Run: python polyfusion/tests/test_frc_benchmark.py

1. ANALYTIC identities of the rigid-rotor profile, checked against
   independent numerical integration:
      <sech^2(Ku)>      = tanh(K)/K
      <sech^4(Ku)>      = (tanh K - tanh^3 K/3)/K
      <|tanh(Ku)|>      = ln(cosh K)/K
      flux_p            = pi r_s^2 B_e ln(cosh K)/(2K)
2. AVERAGE-BETA theorem closure: the solved K satisfies tanh K/K = 1-x_s^2/2.
3. LITERATURE anchor (L3): the LSX device itself — r_s ~ 0.2 m, x_s ~ 0.45,
   elongation ~ 5, n ~ 3e21 m^-3 — must give tau_N of order the measured
   ~0.3-0.5 ms (Hoffman & Slough; scaling quoted verbatim in US9082516).
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_frc  # noqa: E402
from polyfusion.configs.frc import (  # noqa: E402
    _frc_p_from_f_shape,
    _frc_profile_factors,
    _frc_shape_factor_from_p,
    _solve_K,
)
from polyfusion.io import run_case  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---- 1. analytic identities vs independent numerics ----
    for K in (0.3, 1.0, 1.9):
        u = np.linspace(-1.0, 1.0, 20001)
        num_G1 = 0.5 * np.trapezoid(1 / np.cosh(K * u) ** 2, u)
        num_G2 = 0.5 * np.trapezoid(1 / np.cosh(K * u) ** 4, u)
        num_GB = 0.5 * np.trapezoid(np.abs(np.tanh(K * u)), u)
        tK = math.tanh(K)
        ok(abs(num_G1 - tK / K) < 1e-6, f"K={K}: <sech2> analytic vs numeric ({num_G1:.6f})")
        ok(abs(num_G2 - (tK - tK**3 / 3) / K) < 1e-6, f"K={K}: <sech4> analytic vs numeric ({num_G2:.6f})")
        ok(abs(num_GB - math.log(math.cosh(K)) / K) < 1e-6, f"K={K}: <|tanh|> analytic vs numeric ({num_GB:.6f})")
    # trapped flux vs direct 2D integral at K=1.0, r_s=0.5, B_e=2
    K, r_s, B_e = 1.0, 0.5, 2.0
    y = np.linspace(0.0, 0.5, 20001)          # y=(r/r_s)^2 from axis to null
    num_flux = math.pi * r_s**2 * B_e * float(np.trapezoid(np.abs(np.tanh(K * (2 * y - 1))), y))
    ana_flux = math.pi * r_s**2 * B_e * math.log(math.cosh(K)) / (2 * K)
    ok(abs(num_flux - ana_flux) / ana_flux < 1e-5,
       f"trapped flux analytic={ana_flux:.5f} vs numeric={num_flux:.5f} Wb")

    # ---- 2. average-beta theorem closure ----
    for x_s in (0.3, 0.5, 0.7, 0.9):
        K = _solve_K(1 - x_s**2 / 2)
        ok(abs(math.tanh(K) / K - (1 - x_s**2 / 2)) < 1e-6,
           f"x_s={x_s}: tanh(K)/K = 1-x_s^2/2 (K={K:.4f})")

    # ---- 2b. finite-length superellipse geometry closure ----
    ok(abs(_frc_shape_factor_from_p(2.0) - 2.0 / 3.0) < 1e-10,
       "superellipse p=2 gives ellipse volume factor 2/3")
    for f_shape in (0.70, 0.85, 0.97):
        p = _frc_p_from_f_shape(f_shape)
        ok(abs(_frc_shape_factor_from_p(p) - f_shape) < 1e-7,
           f"f_shape={f_shape}: solved p_shape reproduces volume factor (p={p:.3f})")
    p, K, G1, G2, GB = _frc_profile_factors(0.5, 0.85)
    ok(p > 2.0 and K > 0.0 and 0.0 < G2 <= G1 <= 1.0 and 0.0 < GB < 1.0,
       "geometry-weighted FRC factors are bounded and ordered")
    legacy = solve_frc(r_s=0.5, l_s=5.0, r_w=0.7, B_e=3.5, Ti=15.0, Te=12.0,
                       tauE=0.013, f_shape=0.85, geom_weighted=0.0)
    weighted = solve_frc(r_s=0.5, l_s=5.0, r_w=0.7, B_e=3.5, Ti=15.0, Te=12.0,
                         tauE=0.013, f_shape=0.85, geom_weighted=1.0)
    ok(legacy.geom_weighted == 0.0 and weighted.geom_weighted == 1.0,
       "legacy and geometry-weighted FRC modes are both selectable")
    ok(abs(weighted.f_shape_calc - 0.85) < 1e-7 and weighted.p_shape > 2.0,
       "weighted mode exposes the superellipse p_shape used by the power account")
    ok(abs(legacy.Vp - weighted.Vp) / legacy.Vp < 1e-12 and legacy.Pfus != weighted.Pfus,
       "weighted mode keeps Vp fixed but changes profile-averaged power factors")
    c = run_case({"geom_weighted": 1.0}, preset="FRC-DT", config="frc")
    ok(c.get("shape", {}).get("type") == "frc", "FRC run_case returns backend shape data")
    ok(abs(c["shape"]["p_shape"] - c["outputs"]["p_shape"]) < 1e-9,
       "FRC backend shape and power account use the same p_shape")

    # ---- 3. LSX literature anchor ----
    eps, x_s, r_s, n = 5.0, 0.45, 0.2, 3e21
    tau = 3.2e-15 * eps**0.5 * x_s**2 * r_s**2.1 * n**0.6
    ok(1e-4 < tau < 1e-3,
       f"LSX-scale tau_N = {tau*1e3:.2f} ms (measured ~0.3-0.5 ms)")
    # through the full module: an LSX-like machine point
    r = solve_frc(r_s=0.2, l_s=2.0, r_w=0.45, B_e=0.5, Ti=0.2, Te=0.15,
                  icase=1, use_tauE=0.0)
    ok(5e-5 < r.tau_E < 5e-3, f"module LSX-like tau_E = {r.tau_E*1e3:.2f} ms (same order)")
    ok(abs(r.beta - (1 - r.x_s**2 / 2)) < 1e-9, "module beta == 1-x_s^2/2")
    ok(r.beta_null == 1.0, "beta at field null == 1 (pressure balance)")

    print("\nRESULT:", "FRC BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
