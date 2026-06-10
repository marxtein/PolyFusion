"""Physical-limit sanity checks for the 0-D stellarator model.

Run: python etsc_core/tests/test_stellarator_sanity.py
Also checks that, with current physics reused from funsc, the stellarator and
tokamak give identical fusion power for the same geometry/profile inputs
(confinement closure differs, fusion physics does not).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from etsc_core.configs import solve_stellarator  # noqa: E402
from etsc_core import funsc  # noqa: E402

BASE = dict(R0=18.0, A=10.0, kappa=1.0, delta=0.0, Sn=0.5, ST=1.0, ni0=2e20,
            Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5, B0=5.0, iota=1.0, tauE=1.0,
            fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    r = solve_stellarator(**BASE)
    print(f"base: Pfus={r.Pfus:.2f}MW Q={r.Qfus:.3f} H_ISS04={r.H_ISS04:.3f} "
          f"betaT={r.betaT*100:.2f}% nbar/nSudo={r.nbar_o_Sudo:.3f} tau_ISS04={r.tau_ISS04:.3f}s")

    allok &= _ok(all(math.isfinite(v) and v > 0 for v in
                     [r.Pfus, r.Vp, r.ne0, r.betaT, r.H_ISS04, r.tau_ISS04]),
                 "outputs finite & positive")
    # 1. fusion physics identical to tokamak for same inputs (only confinement differs)
    tok = funsc(BASE["R0"], BASE["A"], BASE["kappa"], BASE["delta"], BASE["Sn"],
                BASE["ST"], BASE["ni0"], BASE["Ti0"], BASE["fT"], BASE["fsig"],
                BASE["f1"], BASE["B0"], 10.0, BASE["tauE"], BASE["fHe"],
                BASE["fimp"], BASE["Zimp"], BASE["Rw"], BASE["g"], BASE["icase"])
    allok &= _ok(abs(r.Pfus - tok.Pfus) / tok.Pfus < 1e-12,
                 "Pfus identical to tokamak (shared fusion physics)")
    # 2. ISS04: stronger field -> longer predicted tau -> lower H at fixed tauE
    hb = solve_stellarator(**{**BASE, "B0": 8.0})
    allok &= _ok(hb.tau_ISS04 > r.tau_ISS04 and hb.H_ISS04 < r.H_ISS04,
                 f"B up -> tau_ISS04 up, H down ({r.H_ISS04:.2f}->{hb.H_ISS04:.2f})")
    # 3. higher iota -> longer ISS04 confinement
    hi = solve_stellarator(**{**BASE, "iota": 1.5})
    allok &= _ok(hi.tau_ISS04 > r.tau_ISS04, "iota up -> tau_ISS04 up")
    # 4. f_ren scales ISS04 confinement linearly
    fr = solve_stellarator(**{**BASE, "f_ren": 1.4})
    allok &= _ok(abs(fr.tau_ISS04 / r.tau_ISS04 - 1.4) < 1e-9, "f_ren scales tau_ISS04 linearly")
    # 5. Sudo limit present & positive
    allok &= _ok(r.nbar_o_Sudo > 0, "Sudo density margin computed")
    # 6. p-B11 aneutronic case runs
    pb = solve_stellarator(**{**BASE, "icase": 5, "Ti0": 100.0, "f1": 0.9, "fHe": 0, "fimp": 0})
    allok &= _ok(math.isfinite(pb.Pfus) and pb.Pfus > 0, f"p-B11 runs (Pfus={pb.Pfus:.2f}MW)")

    print("\nRESULT:", "ALL SANITY CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
