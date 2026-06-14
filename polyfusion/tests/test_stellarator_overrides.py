"""Scheme-D override + custom-axis checks for the 0-D stellarator model.

Verifies the measured-machine overrides added in Scheme D:
  * ``Vp_override`` replaces the geometric plasma volume and rescales Pfus,
  * ``Sw_override`` replaces the geometric wall surface and sets Pwall,
  * an explicit measured ``iota`` lets a planar (delta_h=0) device run,
  * a custom Fourier axis (``rc``/``zs``) changes the geometric transform.

Run: python polyfusion/tests/test_stellarator_overrides.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_stellarator  # noqa: E402

# same near-axis base as the sanity / param-activity suites
BASE = dict(R0=18.0, A=10.0, N_fp=5, delta_h=0.9, etabar=0.05, Sn=0.5, ST=1.0,
            ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5, B0=5.0, tauE=1.0,
            fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    b = solve_stellarator(**BASE)
    print(f"base: Vp={b.Vp:.2f} Sw={b.Sw:.2f} Pfus={b.Pfus:.2f} Pheat={b.Pheat:.2f} "
          f"iota_geom={b.iota_geom:.3f}")

    # 1. Vp_override sets Vp exactly AND rescales Pfus ~linearly (Pfus is a
    #    volume integral: Pfus_ov/Pfus_base must track Vp_override/Vp_base).
    vo = solve_stellarator(**{**BASE, "Vp_override": 50.0})
    ratio = vo.Pfus / b.Pfus
    expect = 50.0 / b.Vp
    allok &= _ok(vo.Vp == 50.0, f"Vp_override=50 -> Vp == 50.0 (got {vo.Vp})")
    allok &= _ok(abs(ratio / expect - 1.0) < 0.01,
                 f"Vp_override scales Pfus ~linearly (Pfus_ov/Pfus_base={ratio:.5f}, "
                 f"50/Vp_base={expect:.5f})")

    # 2. Sw_override sets Sw exactly AND Pwall == (Pfus+Pheat)/Sw.
    so = solve_stellarator(**{**BASE, "Sw_override": 200.0})
    pwall_expect = (so.Pfus + so.Pheat) / 200.0
    allok &= _ok(so.Sw == 200.0, f"Sw_override=200 -> Sw == 200.0 (got {so.Sw})")
    allok &= _ok(abs(so.Pwall - pwall_expect) < 1e-9 * max(abs(pwall_expect), 1.0),
                 f"Sw_override sets Pwall = (Pfus+Pheat)/200 ({so.Pwall:.6f} == {pwall_expect:.6f})")

    # 3. Planar measured machine (delta_h=0 -> iota_geom=0) runs WITHOUT error
    #    because the explicit measured iota satisfies the zero-transform guard.
    pm = solve_stellarator(**{**BASE, "delta_h": 0.0, "etabar": 0.04, "iota": 0.40})
    allok &= _ok(pm.iota == 0.40 and math.isfinite(pm.Pfus) and pm.Pfus > 0,
                 f"planar measured (delta_h=0, iota=0.40) runs: iota={pm.iota}, "
                 f"Pfus={pm.Pfus:.2f}MW")

    # 4. Custom Fourier axis changes the geometric transform vs the single-
    #    harmonic default with the same delta_h.
    ca = solve_stellarator(**{**BASE, "rc": [18.0, 0.9, 0.1], "zs": [0.0, -0.9, -0.1]})
    allok &= _ok(abs(ca.iota_geom - b.iota_geom) > 1e-3,
                 f"custom axis changes iota_geom ({b.iota_geom:.4f} -> {ca.iota_geom:.4f})")

    print("\nRESULT:", "ALL OVERRIDE CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
