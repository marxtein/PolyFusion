"""Physical-limit sanity checks for the 0-D stellarator model v2.

Run: python polyfusion/tests/test_stellarator_sanity.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_stellarator  # noqa: E402

BASE = dict(R0=18.0, A=10.0, kappa_s=2.7, N_fp=5, delta_h=0.9, Sn=0.5, ST=1.0,
            ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5, B0=5.0, tauE=1.0,
            fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    r = solve_stellarator(**BASE)
    print(f"base: Pfus={r.Pfus:.1f}MW Q={r.Qfus:.3f} iota_geom={r.iota_geom:.3f} "
          f"H_ISS04={r.H_ISS04:.3f} V={r.Vp:.1f} betaT={r.betaT*100:.2f}%")

    allok &= _ok(all(math.isfinite(v) and v > 0 for v in
                     [r.Pfus, r.Vp, r.ne0, r.betaT, r.H_ISS04, r.tau_ISS04, r.iota_geom]),
                 "outputs finite & positive")
    # 1. more field periods -> more transform (same shaping)
    lo = solve_stellarator(**{**BASE, "N_fp": 4})
    hi = solve_stellarator(**{**BASE, "N_fp": 6})
    allok &= _ok(hi.iota_geom > lo.iota_geom, f"N_fp up -> iota up ({lo.iota_geom:.3f}->{hi.iota_geom:.3f})")
    # 2. stronger shaping -> more transform
    sh = solve_stellarator(**{**BASE, "kappa_s": 3.5})
    allok &= _ok(sh.iota_geom > r.iota_geom, "kappa_s up -> iota up")
    # 3. explicit iota overrides geometry
    ov = solve_stellarator(**{**BASE, "iota": 0.5})
    allok &= _ok(ov.iota == 0.5 and ov.iota_geom == r.iota_geom, "explicit iota overrides; geom still reported")
    # 4. helical axis lengthens L_ax and volume
    st0 = solve_stellarator(**{**BASE, "delta_h": 0.0})
    allok &= _ok(r.L_ax > st0.L_ax and r.Vp > st0.Vp, f"helical axis: L_ax {st0.L_ax:.1f}->{r.L_ax:.1f} m")
    # 5. ISS04: B up -> tau up -> H down at fixed tauE
    hb = solve_stellarator(**{**BASE, "B0": 8.0})
    allok &= _ok(hb.tau_ISS04 > r.tau_ISS04 and hb.H_ISS04 < r.H_ISS04, "B up -> tau_ISS04 up, H down")
    # 6. f_ren scales tau linearly
    fr = solve_stellarator(**{**BASE, "f_ren": 1.4})
    allok &= _ok(abs(fr.tau_ISS04 / r.tau_ISS04 - 1.4) < 1e-9, "f_ren scales tau_ISS04 linearly")
    # 7. Sudo margin computed; p-B11 runs
    allok &= _ok(r.nbar_o_Sudo > 0, "Sudo margin computed")
    pb = solve_stellarator(**{**BASE, "icase": 5, "Ti0": 100.0, "f1": 0.9, "fHe": 0.0, "fimp": 0.0})
    allok &= _ok(math.isfinite(pb.Pfus) and pb.Pfus > 0, f"p-B11 runs (Pfus={pb.Pfus:.2f}MW)")

    print("\nRESULT:", "ALL SANITY CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
