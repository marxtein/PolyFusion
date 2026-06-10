"""Mirror module verification (docs/20): analytic identities + regime physics.

Run: python polyfusion/tests/test_mirror_benchmark.py

No public worked-number table exists for MCTrans++ (the paper is
methodological), so per docs/18 the mirror is verified by:

1. INDEPENDENT re-computation: the three confinement channels
   (Pastukhov, gas-dynamic, radial) are re-implemented here from the
   published formulas (arXiv:2411.06644) with separate arithmetic and
   compared against the module outputs.
2. ANALYTIC identity: G(R) -> ln(4R+1) asymptote for large mirror ratio.
3. REGIME physics: at GDT (warm, collisional, R=35) the gas-dynamic
   channel must dominate the end-loss time; at BEAM (hot, collisionless)
   the Pastukhov channel must dominate.  This is the defining physics of
   the two device classes, with parameters from the literature.
4. ORDER-OF-MAGNITUDE anchor: WHAM/BEAM-class targets tau_p ~ 0.1-1 s.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_mirror  # noqa: E402
from polyfusion.configs.base import MIRROR_PRESETS  # noqa: E402

QE, MP = 1.6022e-19, 1.6726e-27
PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def channels_independent(a_c, L_c, B_vac, R_mirror, ni0, Ti, Te, M, lnL=17.0):
    """Re-derive the three confinement times from the published formulas."""
    mi = M * MP
    # diamagnetic well (n_e ~ n_i here: pure fuel, Z=1)
    p = (ni0 * Ti + ni0 * Te) * 1e3 * QE
    beta = 2 * 4e-7 * math.pi * p / B_vac**2
    B0 = B_vac * math.sqrt(1 - beta)
    R_mc = R_mirror / math.sqrt(1 - beta)
    phi_i = Te * math.log(R_mirror)
    r = phi_i / Ti
    tau_ii = (Ti * 1e3) ** 1.5 * math.sqrt(M) / (4.80e-8 * (ni0 * 1e-6) * lnL)
    v_th = math.sqrt(Ti * 1e3 * QE / (2 * mi))
    s = math.sqrt(1 + 1 / R_mc)
    G = s * math.log((s + 1) / (s - 1))
    den = 1 + Ti / (2 * phi_i) - (Ti / (2 * phi_i)) ** 2
    tau_P = math.sqrt(math.pi) / 2 * tau_ii * r * math.exp(r) * G / den
    tau_g = math.sqrt(math.pi) * R_mc * (L_c / v_th) * math.exp(r)
    rho = v_th / (QE * B0 / mi)
    tau_r = (a_c / rho) ** 2 * tau_ii
    return tau_P, tau_g, tau_r


def main():
    # ---- 1. independent recomputation at the BEAM point ----
    P = dict(MIRROR_PRESETS["BEAM"])
    res = solve_mirror(**P)
    M = 2.5  # D-T 50:50
    tP, tg, tr = channels_independent(P["a_c"], P["L_c"], P["B_vac"], P["R_mirror"],
                                      P["ni0"], P["Ti0"], P["Te0"], M)
    for name, mine, ref in [("tau_Past", res.tau_Past, tP),
                            ("tau_gd", res.tau_gd, tg),
                            ("tau_rho", res.tau_rho, tr)]:
        rel = abs(mine - ref) / ref
        ok(rel < 1e-9, f"independent recompute {name}: module={mine:.4e} ref={ref:.4e} rel={rel:.1e}")

    # ---- 2. analytic asymptote G(R) ~ ln(4R+1) ----
    R = 100.0
    s = math.sqrt(1 + 1 / R)
    G = s * math.log((s + 1) / (s - 1))
    ok(abs(G - math.log(4 * R + 1)) / G < 0.03,
       f"G(R=100)={G:.3f} vs ln(4R+1)={math.log(4*R+1):.3f} (<3%)")

    # ---- 3. regime classification (defining device physics) ----
    gdt = solve_mirror(**MIRROR_PRESETS["GDT"])
    ok(gdt.tau_gd > gdt.tau_Past,
       f"GDT (collisional, R=35): gas-dynamic dominates end loss "
       f"(tau_gd={gdt.tau_gd:.3f}s > tau_Past={gdt.tau_Past:.3f}s)")
    ok(res.tau_Past > res.tau_gd,
       f"BEAM (hot, collisionless): Pastukhov dominates "
       f"(tau_Past={res.tau_Past:.3f}s > tau_gd={res.tau_gd:.4f}s)")
    # mean free path criterion behind the GDT regime: lambda_ii < R*L
    g = MIRROR_PRESETS["GDT"]
    tau_ii = (g["Ti0"] * 1e3) ** 1.5 * math.sqrt(2.5) / (4.80e-8 * (g["ni0"] * 1e-6) * 17.0)
    lam = math.sqrt(g["Ti0"] * 1e3 * QE / (2 * 2.5 * MP)) * tau_ii
    ok(lam < g["R_mirror"] * g["L_c"],
       f"GDT mean free path {lam:.1f} m < R*L = {g['R_mirror']*g['L_c']:.0f} m (gas-dynamic criterion)")

    # ---- 4. order-of-magnitude anchor: WHAM/BEAM class tau ~ 0.1-1 s ----
    ok(0.03 < res.tau_c < 3.0,
       f"BEAM-class tau_c = {res.tau_c:.3f}s, order of WHAM target tau_p~1s")

    print("\nRESULT:", "MIRROR BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
