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
from polyfusion.configs.frc import _solve_K  # noqa: E402

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

    # ---- 3. LSX literature anchor ----
    eps, x_s, r_s, n = 5.0, 0.45, 0.2, 3e21
    tau = 3.2e-15 * eps**0.5 * x_s**2 * r_s**2.1 * n**0.6
    ok(1e-4 < tau < 1e-3,
       f"LSX-scale tau_N = {tau*1e3:.2f} ms (measured ~0.3-0.5 ms)")
    # through the full module: an LSX-like machine point
    r = solve_frc(r_s=0.2, l_s=2.0, r_w=0.45, B_e=0.5, Ti=0.2, Te=0.15, icase=1)
    ok(5e-5 < r.tau_E < 5e-3, f"module LSX-like tau_E = {r.tau_E*1e3:.2f} ms (same order)")
    ok(abs(r.beta - (1 - r.x_s**2 / 2)) < 1e-9, "module beta == 1-x_s^2/2")
    ok(r.beta_null == 1.0, "beta at field null == 1 (pressure balance)")

    print("\nRESULT:", "FRC BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
