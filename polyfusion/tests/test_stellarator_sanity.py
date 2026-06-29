"""Physical-limit sanity checks for the 0-D stellarator model (Scheme D).

Single near-axis (Garren-Boozer) geometry: ``etabar`` (!= 0) is the sole
shaping knob and elongation is a DERIVED OUTPUT; the helical-axis excursion
``delta_h`` feeds iota through the axis torsion.

Run: python polyfusion/tests/test_stellarator_sanity.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_stellarator  # noqa: E402

# post-Scheme-D base: near-axis, etabar-driven, NO kappa_s (template =
# test_stellarator_param_activity.py BASE)
BASE = dict(
    R0=18.0,
    a=1.8,
    N_fp=5,
    delta_h=0.9,
    etabar=0.05,
    Sn=0.5,
    ST=1.0,
    ni0=2e20,
    Ti0=15.0,
    fT=1.0,
    fsig=1.0,
    f1=0.5,
    B0=5.0,
    tauE=1.0,
    fHe=0.04,
    fimp=0.01,
    Zimp=10,
    Rw=0.7,
    g=0.1,
    icase=1,
)


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True
    r = solve_stellarator(**BASE)
    print(
        f"base: Pfus={r.Pfus:.1f}MW Q={r.Qfus:.3f} iota_geom={r.iota_geom:.3f} "
        f"elong_max={r.elong_max:.3f} H_ISS04={r.H_ISS04:.3f} V={r.Vp:.1f} "
        f"betaT={r.betaT * 100:.2f}%"
    )

    allok &= _ok(
        all(
            math.isfinite(v) and v > 0
            for v in [r.Pfus, r.Vp, r.ne0, r.betaT, r.H_ISS04, r.tau_ISS04, r.iota_geom]
        ),
        "outputs finite & positive",
    )
    # 1. more field periods -> more transform (same shaping)
    lo = solve_stellarator(**{**BASE, "N_fp": 4})
    hi = solve_stellarator(**{**BASE, "N_fp": 6})
    allok &= _ok(
        hi.iota_geom > lo.iota_geom,
        f"N_fp up -> iota up ({lo.iota_geom:.3f}->{hi.iota_geom:.3f})",
    )
    # 2a. stronger shaping (etabar) -> more elongation (derived output)
    sh = solve_stellarator(**{**BASE, "etabar": 0.07})
    allok &= _ok(
        sh.elong_max > r.elong_max,
        f"etabar up -> elongation up ({r.elong_max:.3f}->{sh.elong_max:.3f})",
    )
    # 2b. helical excursion feeds iota through axis torsion
    dh = solve_stellarator(**{**BASE, "delta_h": 1.2})
    allok &= _ok(
        abs(dh.iota_geom - r.iota_geom) > 1e-6,
        f"delta_h changes iota (torsion) ({r.iota_geom:.3f}->{dh.iota_geom:.3f})",
    )
    # 3. near-axis mode ignores boundary-only iota input
    ov = solve_stellarator(**{**BASE, "iota": 0.5})
    allok &= _ok(
        ov.iota == r.iota and ov.iota_geom == r.iota_geom,
        "near-axis iota comes from current geometry",
    )
    # 4. helical axis lengthens L_ax relative to an almost-planar axis.
    st0 = solve_stellarator(**{**BASE, "delta_h": 1e-3})
    # the helical excursion lengthens the magnetic axis (geometric fact).  With
    # the exact boundary integral the volume is no longer strictly monotonic with
    # L_ax (the bean/curvature correction can outweigh the longer axis), so we
    # assert the axis lengthening and that both volumes stay finite & positive.
    allok &= _ok(
        r.L_ax > st0.L_ax and r.Vp > 0 and st0.Vp > 0,
        f"helical axis lengthens L_ax {st0.L_ax:.1f}->{r.L_ax:.1f} m "
        f"(Vp {st0.Vp:.0f}->{r.Vp:.0f})",
    )
    # 5. ISS04: B up -> tau up -> H down at fixed tauE
    hb = solve_stellarator(**{**BASE, "B0": 8.0})
    allok &= _ok(
        hb.tau_ISS04 > r.tau_ISS04 and hb.H_ISS04 < r.H_ISS04,
        "B up -> tau_ISS04 up, H down",
    )
    # 6. f_ren scales tau linearly
    fr = solve_stellarator(**{**BASE, "f_ren": 1.4})
    allok &= _ok(
        abs(fr.tau_ISS04 / r.tau_ISS04 - 1.4) < 1e-9, "f_ren scales tau_ISS04 linearly"
    )
    # 7. Sudo margin computed; p-B11 runs
    allok &= _ok(r.nbar_o_Sudo > 0, "Sudo margin computed")
    pb = solve_stellarator(
        **{**BASE, "icase": 5, "Ti0": 100.0, "f1": 0.9, "fHe": 0.0, "fimp": 0.0}
    )
    allok &= _ok(
        math.isfinite(pb.Pfus) and pb.Pfus > 0, f"p-B11 runs (Pfus={pb.Pfus:.2f}MW)"
    )

    print("\nRESULT:", "ALL SANITY CHECKS PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
