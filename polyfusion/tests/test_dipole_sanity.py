"""Physical-limit sanity checks for the 0-D dipole model (no golden baseline yet).

Run: python polyfusion/tests/test_dipole_sanity.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_dipole  # noqa: E402

BASE = dict(
    r_ring=1.0, R_p=10.0, B_ring=10.0, n0=1e21, Ti0=30.0, Te0=20.0, tauE=5.0, icase=2
)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    r = solve_dipole(**BASE)
    print(
        f"base: Pfus={r.Pfus:.3f}MW Q={r.Qfus:.3f} beta_in={r.beta_in:.3f} "
        f"Vp={r.Vp:.1f} ne0={r.ne0:.2e} Eth={r.Eth:.2f} ntau={r.ntau:.2e}"
    )

    allok &= _ok(
        all(
            math.isfinite(v) and v > 0 for v in [r.Pfus, r.Vp, r.ne0, r.Eth, r.beta_in]
        ),
        "outputs finite & positive",
    )
    # 1. beta_in = 2mu0 p0 / B^2 ; raising B lowers it
    hb = solve_dipole(**{**BASE, "B_ring": 20.0})
    allok &= _ok(
        hb.beta_in < r.beta_in,
        f"B_ring up -> beta down ({r.beta_in:.3f}->{hb.beta_in:.3f})",
    )
    # 2. peak density up -> more fusion power
    dn = solve_dipole(**{**BASE, "n0": 2e21})
    allok &= _ok(dn.Pfus > r.Pfus, f"n0 up -> Pfus up ({r.Pfus:.1f}->{dn.Pfus:.1f})")
    # 3. longer (input) confinement -> higher Q
    lt = solve_dipole(**{**BASE, "tauE": 1.0})
    ht = solve_dipole(**{**BASE, "tauE": 20.0})
    allok &= _ok(ht.Qfus > lt.Qfus, f"tauE up -> Q up ({lt.Qfus:.3f}->{ht.Qfus:.3f})")
    # 4. marginal profile peaks at ring: shrinking R_p (more outer-only cut) barely changes Pfus
    #    (power concentrated near ring) -> Pfus with R_p=6 close to R_p=10
    small = solve_dipole(**{**BASE, "R_p": 6.0})
    allok &= _ok(
        abs(small.Pfus - r.Pfus) / r.Pfus < 0.05,
        f"power concentrated near ring (Pfus {r.Pfus:.1f} vs {small.Pfus:.1f})",
    )
    # 5. D-3He preset runs
    dhe = solve_dipole(
        r_ring=1.0,
        R_p=8.0,
        B_ring=12.0,
        n0=5e20,
        Ti0=80.0,
        Te0=60.0,
        tauE=10.0,
        icase=3,
    )
    allok &= _ok(
        math.isfinite(dhe.Pfus) and dhe.Pfus > 0, f"D-3He runs (Pfus={dhe.Pfus:.3f}MW)"
    )

    print("\nRESULT:", "ALL SANITY CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
