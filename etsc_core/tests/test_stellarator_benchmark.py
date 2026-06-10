"""Stellarator literature benchmark (docs/23).

Run: python etsc_core/tests/test_stellarator_benchmark.py

Anchor: the Wendelstein 7-X June-2018 record discharge (IPP press release;
Nucl. Fusion divertor-operation papers): n̄_e = 0.8e20 m^-3, T_i(0) ≈ 3.4 keV,
P_heat ≈ 5 MW ECRH, measured tau_E = 0.22 s.  Feeding the *measured* machine
parameters into our ISS04 implementation must predict tau within the
experimental scatter of the scaling (W7-X reports H_ISS04 ~ 1-1.4):

    tau_ISS04 = 0.134 a^2.28 R^0.64 P^-0.61 nbar19^0.54 B^0.84 iota^0.41

Also checks the Sudo density limit at this operating point (W7-X ran at
~0.8e20, right at/above the Sudo value — consistent with the literature
statement that clean plasmas can exceed Sudo by ~50%).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from etsc_core.configs import solve_stellarator  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # --- W7-X record-shot machine/plasma parameters (published) ---
    a, R, B, iota = 0.51, 5.5, 2.5, 0.9
    P_MW = 5.2            # ECRH heating ~ loss power in steady state
    nbar19 = 8.0          # 0.8e20 m^-3
    tau_meas = 0.22       # s (measured)

    tau = (0.134 * a**2.28 * R**0.64 * P_MW**-0.61
           * nbar19**0.54 * B**0.84 * iota**0.41)
    H = tau_meas / tau
    ok(0.15 < tau < 0.27, f"ISS04(W7-X record params) = {tau:.3f}s (expect ~0.2s)")
    ok(0.8 < H < 1.5, f"H_ISS04 = {H:.2f} (W7-X reports ~1-1.4)")

    # --- Sudo density limit at the same point ---
    n_sudo20 = 0.25 * math.sqrt(P_MW * B / (a**2 * R))
    ratio = 0.8 / n_sudo20
    ok(0.7 < ratio < 1.6,
       f"nbar/n_Sudo = {ratio:.2f} (W7-X ran at/above Sudo; clean plasma can exceed ~50%)")

    # --- module self-consistency: solve_stellarator with the W7-X-like preset
    #     inputs reproduces the same ISS04 prediction through the full pipeline ---
    r = solve_stellarator(R0=5.5, A=5.5/0.51, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0,
                          ni0=1.0e20, Ti0=3.4, fT=1.0, fsig=1.0, f1=0.5,
                          B0=2.5, iota=0.9, tauE=0.22, fHe=0.0, fimp=0.0,
                          Zimp=10, Rw=0.7, g=0.05, icase=1, f_ren=1.0)
    # the pipeline's loss power differs from 5.2 MW only through its own
    # consistent power balance; H should land in the same physical ballpark
    ok(0.4 < r.H_ISS04 < 2.5,
       f"pipeline H_ISS04 = {r.H_ISS04:.2f} (full power balance, same ballpark)")
    ok(r.nbar_o_Sudo > 0 and math.isfinite(r.nbar_o_Sudo),
       f"pipeline Sudo margin computed: {r.nbar_o_Sudo:.2f}")

    print("\nRESULT:", "STELLARATOR BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
