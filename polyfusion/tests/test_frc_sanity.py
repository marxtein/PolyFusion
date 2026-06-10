"""Physical-limit sanity checks for the 0-D FRC model (no golden baseline yet).

Run: python polyfusion/tests/test_frc_sanity.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_frc  # noqa: E402

BASE = dict(r_s=0.6, l_s=6.0, r_w=0.8, B_e=6.0, Ti=20.0, Te=15.0, icase=1)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    r = solve_frc(**BASE)
    print(f"base: Pfus={r.Pfus:.3f}MW Q={r.Qfus:.3f} beta={r.beta:.3f} "
          f"ni0={r.ni0:.3e} tau_E={r.tau_E:.3e}s s={r.s_param:.1f} ntau={r.ntau:.2e}")

    allok &= _ok(all(math.isfinite(v) and v > 0 for v in
                     [r.Pfus, r.tau_E, r.Vp, r.ne0, r.ni0, r.beta]),
                 "outputs finite & positive")
    # 1. high beta defining feature: beta = 1 - x_s^2/2 in (0.5,1) for x_s<1
    allok &= _ok(0.5 < r.beta < 1.0, f"beta high & physical ({r.beta:.3f})")
    # 2. density locked by pressure balance: stronger field -> higher density & Pfus
    hi = solve_frc(**{**BASE, "B_e": 9.0})
    allok &= _ok(hi.ni0 > r.ni0 and hi.Pfus > r.Pfus,
                 f"B_e up -> ni0 & Pfus up (Pfus {r.Pfus:.1f}->{hi.Pfus:.1f})")
    # 3. larger separatrix -> longer LSX confinement -> higher Q
    big = solve_frc(**{**BASE, "r_s": 0.9, "r_w": 1.1})
    allok &= _ok(big.tau_E > r.tau_E and big.Qfus > r.Qfus,
                 f"r_s up -> tau_E & Q up (Q {r.Qfus:.2f}->{big.Qfus:.2f})")
    # 4. smaller x_s (r_s far from wall) -> higher beta
    near = solve_frc(**{**BASE, "r_w": 0.65})  # x_s closer to 1
    allok &= _ok(near.beta < r.beta, f"x_s up -> beta down ({r.beta:.3f}->{near.beta:.3f})")
    # 5. internal field reduced by diamagnetism
    allok &= _ok(r.B_int < BASE["B_e"], "B_int < B_e (field reversal)")
    # 6. D-3He preset runs
    dhe = solve_frc(r_s=0.3, l_s=2.0, r_w=0.4, B_e=8.0, Ti=70.0, Te=50.0, icase=3)
    allok &= _ok(math.isfinite(dhe.Pfus) and dhe.Pfus > 0, f"D-3He runs (Pfus={dhe.Pfus:.3f}MW)")

    print("\nRESULT:", "ALL SANITY CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
