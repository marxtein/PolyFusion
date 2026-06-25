"""Physical-limit sanity checks for the 0-D mirror model (no golden baseline yet).

Run: python polyfusion/tests/test_mirror_sanity.py
Verifies monotonicity and limit behaviour that any correct mirror model must obey.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_mirror  # noqa: E402

# BEAM-like reference point (Realta-class HTS mirror), D-T.
BASE = dict(a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0,
            ni0=3e20, Ti0=15.0, Te0=10.0, Rw=0.8, icase=1)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    r = solve_mirror(**BASE)
    print(f"base: Pfus={r.Pfus:.3f}MW Q={r.Qfus:.3f} tau_m={r.tau_m:.3e}s "
          f"phi_i={r.phi_i:.2f} phi_e={r.phi_e:.2f} beta={r.beta:.3f} ntau={r.ntau:.2e}")

    # 1. all key outputs finite & positive
    allok &= _ok(all(math.isfinite(v) and v > 0 for v in
                     [r.Pfus, r.tau_m, r.Vp, r.ne0, r.beta, r.phi_i, r.phi_e]),
                 "outputs finite & positive")
    # 2. electron potential exceeds ion potential (ambipolarity)
    allok &= _ok(r.phi_e > r.phi_i > 0, "phi_e > phi_i > 0")
    # 3. combined tau is the parallel-min (<= each channel)
    allok &= _ok(r.tau_m <= r.tau_rho and r.tau_m <= (r.tau_Past + r.tau_gd) + 1e-30,
                 "tau_m <= each channel")
    # 4. higher mirror ratio -> better confinement -> higher Q.
    # Q reflects confinement only through the self-consistent end-loss closure
    # (Ptrans = Int n(phi+T)dV / tau_m); under the DEFAULT use_tauE=1 the
    # transport account is the fixed Eth/tauE energy-confinement model, which
    # at this hot BEAM point already ignites (Pheat<=0 -> Q capped at 1000) so
    # the Q-increase is unobservable.  Exercise the loss closure with use_tauE=0.
    lo = solve_mirror(**{**BASE, "R_mirror": 6.0, "use_tauE": 0.0})
    hi = solve_mirror(**{**BASE, "R_mirror": 20.0, "use_tauE": 0.0})
    allok &= _ok(hi.tau_m > lo.tau_m and hi.Qfus > lo.Qfus,
                 f"R_mirror up -> tau_m & Q up ({lo.Qfus:.2f}->{hi.Qfus:.2f})")
    # 5. higher density -> more fusion power
    dn = solve_mirror(**{**BASE, "ni0": 6e20})
    allok &= _ok(dn.Pfus > r.Pfus, f"density up -> Pfus up ({r.Pfus:.2f}->{dn.Pfus:.2f})")
    # 6. beta scales ~ n*T / B^2 ; raising B lowers beta
    hb = solve_mirror(**{**BASE, "B_vac": 6.0})
    allok &= _ok(hb.beta < r.beta, f"B up -> beta down ({r.beta:.3f}->{hb.beta:.3f})")
    # 7. diamagnetic well: B0 < B_vac and R_mc > R_mirror
    allok &= _ok(r.B0 < BASE["B_vac"] and r.R_mc > BASE["R_mirror"],
                 "diamagnetic well B0<Bvac, R_mc>R_mirror")
    # 8. aneutronic p-B11 runs and is finite
    pb = solve_mirror(**{**BASE, "icase": 5, "Ti0": 100.0, "Te0": 100.0, "f1": 0.9})
    allok &= _ok(math.isfinite(pb.Pfus) and pb.Pfus > 0, f"p-B11 runs (Pfus={pb.Pfus:.3f}MW)")
    # 9. v2 flat-profile limit reproduces v1 numbers exactly (Sn=ST=0,g=0,f_throat=0)
    # f_alpha=1.0 explicit: v1 assumed full charged-product deposition; the
    # batch-2 default is the loss-cone bound sqrt(1-1/R_mc) (docs/30).
    # use_tauE=0: the v1 numbers (esp. Q=1.125) were derived against the
    # self-consistent end-loss closure Ptrans = Int n(phi+T)dV / tau_m.
    # The later use_tauE switch made the DEFAULT transport account the
    # Eth/tauE energy-confinement model (Ptrans = Eth/tauE, tauE=1.0s here);
    # since tau_m=0.2512s << tauE=1.0s that model under-predicts the end loss
    # ~10x at this hot point (Ptrans 53.8 MW -> 5.1 MW), collapsing Pheat to
    # -4.4 MW (false ignition, Q capped at 1000).  Pfus/tau_m/beta/phi_i are
    # closure-independent and still match v1; only the transport/heating side
    # (hence Q) is governed by the closure, so reproduce v1 with use_tauE=0.
    flat = solve_mirror(a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, ni0=3e20,
                        Ti0=15.0, Te0=10.0, Sn=0.0, ST=0.0, g=0.0, f_throat=0.0,
                        Rw=0.8, icase=1, f_alpha=1.0, use_tauE=0.0)
    # Pfus/Q carry the funsc quadrature convention (2*sum(x)*dx = 1.01) now
    # that the mirror uses the tokamak-identical profile integral: v1*1.0100.
    v1 = dict(Pfus=49.871, Qfus=1.125, tau_m=0.2512, beta=0.336, phi_i=23.03)
    okf = all(abs(getattr(flat, k) - v) / v < 2e-3 for k, v in v1.items())
    allok &= _ok(okf, f"flat limit reproduces v1 (Pfus={flat.Pfus:.3f} Q={flat.Qfus:.3f} tau={flat.tau_m:.4f} beta={flat.beta:.3f})")

    print("\nRESULT:", "ALL SANITY CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
