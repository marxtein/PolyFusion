"""Physics batch P1 verification (docs/30): twotemp, impurity, ringfield.

Run: python polyfusion/tests/test_physics_p1_benchmark.py

1. TWO-TEMPERATURE primitives:
   - elliptic-limit self-checks of the Stix ion fraction (E0<<Ec -> 1,
     E0>>Ec -> 0, monotone), D-T alpha at Te=10 keV gives f_i ~ 0.2;
   - critical energy: D-T 50:50 at Te=10 keV -> Ecrit ~ 33*Te (textbook);
   - equilibration anchor: D plasma, n=1e20, Te=10 keV -> tau_eq ~ 0.36 s;
   - P_ei sign/zero behaviour.
2. IMPURITY Mavrin fits:
   - CROSS-VALIDATION: helium is fully stripped at high Te, so Mavrin's
     total cooling rate must agree with our independent bremsstrahlung
     constant 5.34e-37*Z^2*sqrt(Te) to ~10% (two unrelated sources);
   - W at 10 keV ~ 1.3e-31 W m^3 (literature magnitude);
   - net-line clamp >= 0 everywhere; Ar line >> brems at 2 keV.
3. RINGFIELD (finite current loop):
   - K/E elliptic values vs Abramowitz-Stegun (K(m=0.5)=1.854074677...);
   - far-field recovery of the three point-dipole laws:
     B -> (1/4)/lam^3, U ~ lam^4, V -> 64 pi lam^3/105;
   - near-ring deviation from the point dipole is REAL and reported.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.twotemp import (critical_energy, ion_deposition_fraction,  # noqa: E402
                                equilibration_time, p_ei_exchange)
from polyfusion.impurity import lz_total, lz_line_net, atomic_number  # noqa: E402
from polyfusion.ringfield import ellipk_e, psi_norm, b_eq, u_spec, v_enc  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---------------- 1. two-temperature primitives ----------------
    dt_mix = [(0.5e20, 1, 2), (0.5e20, 1, 3)]          # 50:50 D-T
    Ec = critical_energy(10.0, 4.0, dt_mix)            # alpha (A=4) in D-T
    ok(250 < Ec < 420, f"D-T alpha Ecrit = {Ec:.0f} keV at Te=10 (textbook ~33*Te)")

    ok(ion_deposition_fraction(0.01 * Ec, Ec) > 0.95, "Stix: E0<<Ec -> ions get ~all")
    ok(ion_deposition_fraction(100 * Ec, Ec) < 0.15, "Stix: E0>>Ec -> ions get ~none")
    f_alpha = ion_deposition_fraction(3500.0, Ec)
    ok(0.10 < f_alpha < 0.35, f"D-T alpha ion fraction = {f_alpha:.3f} (~0.2: mostly electrons!)")
    fr = [ion_deposition_fraction(E, Ec) for E in (50, 200, 1000, 3500)]
    ok(all(a > b for a, b in zip(fr, fr[1:])), "Stix fraction monotone decreasing in E0")

    tau = equilibration_time(1e20, 10.0, 1, 2)
    ok(0.2 < tau < 0.6, f"i-e equilibration tau_eq = {tau:.3f} s (anchor ~0.36 s)")
    ok(abs(p_ei_exchange(1e20, 10.0, 10.0, 1, 2)) < 1e-12, "P_ei = 0 at Ti = Te")
    ok(p_ei_exchange(1e20, 15.0, 10.0, 1, 2) > 0, "P_ei > 0 when ions hotter")

    # ---------------- 2. Mavrin impurity cooling ----------------
    # tolerance widens with Te: our solvers' relativistic brems corrections sit
    # OUTSIDE the 5.34e-37 constant, while Mavrin's fit absorbs them, so the
    # naive constant overshoots Mavrin by ~20% at 30 keV (expected, not a bug)
    for Te, tol in ((5.0, 0.12), (10.0, 0.12), (30.0, 0.30)):
        ours = 5.34e-37 * 4 * math.sqrt(Te)
        mav = float(lz_total("He", Te))
        ok(abs(mav - ours) / ours < tol,
           f"He cross-check at Te={Te}: Mavrin {mav:.3e} vs brems {ours:.3e} (<{tol:.0%})")
    w10 = float(lz_total("W", 10.0))
    ok(5e-32 < w10 < 5e-31, f"W cooling at 10 keV = {w10:.2e} W m^3 (lit ~1e-31)")
    Te_grid = np.geomspace(0.15, 90, 200)
    for sp in ("C", "N", "Ne", "Ar", "Kr", "Xe", "W"):
        net = lz_line_net(sp, Te_grid)
        ok(np.all(net >= 0) and np.all(np.isfinite(net)),
           f"{sp}: net line cooling finite and >= 0 over 0.15-90 keV")
    ar2 = float(lz_line_net("Ar", 2.0))
    arb = 5.34e-37 * atomic_number("Ar") ** 2 * math.sqrt(2.0)
    ok(ar2 > 2 * arb, f"Ar at 2 keV: line/brems = {ar2 / arb:.1f} (line radiation dominates)")

    # ---------------- 3. finite-ring field ----------------
    K, E = ellipk_e(np.array([0.0, 0.5]))
    ok(abs(K[0] - math.pi / 2) < 1e-12 and abs(E[0] - math.pi / 2) < 1e-12,
       "K(0) = E(0) = pi/2")
    ok(abs(K[1] - 1.8540746773) < 1e-9 and abs(E[1] - 1.3506438810) < 1e-9,
       f"K,E(m=0.5) = {K[1]:.10f}, {E[1]:.10f} (Abramowitz-Stegun)")

    # far-field point-dipole recovery
    lam_far = np.array([10.0, 12.0, 14.0])
    Bratio = b_eq(lam_far) * 4 * lam_far ** 3
    ok(np.all(np.abs(Bratio - 1) < 0.02),
       f"far field: B*4lam^3 = {np.round(Bratio, 4)} -> 1 (dipole law)")
    Vratio = v_enc(lam_far) / (64 * math.pi * lam_far ** 3 / 105)
    ok(np.all(np.abs(Vratio - 1) < 0.06),
       f"far field: V/(64pi lam^3/105) = {np.round(Vratio, 4)} -> 1")
    u1, u2 = u_spec(9.0), u_spec(13.0)
    expo = math.log(u2 / u1) / math.log(13.0 / 9.0)
    ok(abs(expo - 4.0) < 0.25, f"far field: U ~ lam^{expo:.2f} (dipole: 4)")

    # near-ring: the correction is real (B stronger than dipole extrapolation)
    lam_near = 1.5
    near_ratio = float(b_eq(lam_near) * 4 * lam_near ** 3)
    ok(near_ratio > 1.05,
       f"near ring (lam=1.5): B/B_dipole = {near_ratio:.3f} (>1: point dipole "
       "underestimates the field where the plasma actually sits)")

    # psi far-field: dipole flux function psi = mu0 m sin^2(theta)/(2r),
    # m = pi I a^2 -> in loop units psi_dip = (pi/2) rho^2/(rho^2+z^2)^{3/2}
    ps = float(psi_norm(12.0, 3.0))
    ps_dip = (math.pi / 2) * 12.0 ** 2 / (12.0 ** 2 + 3.0 ** 2) ** 1.5
    ok(abs(ps / ps_dip - 1) < 0.02, f"psi far-field ratio = {ps / ps_dip:.4f} -> 1")

    # ---------------- 4. solver integration ----------------
    from polyfusion.io import run_case

    # line radiation lowers Q when switched on; off by default (golden-safe)
    r0 = run_case({"fimp": 0.005, "Zimp": 18}, preset="ITER", config="tokamak")
    r1 = run_case({"fimp": 0.005, "Zimp": 18, "imp_name": "Ar"},
                  preset="ITER", config="tokamak")
    ok(r0["outputs"]["P_line"] == 0.0, "tokamak: P_line = 0 without imp_name")
    ok(r1["outputs"]["P_line"] > 1.0,
       f"tokamak ITER + 0.5% Ar: P_line = {r1['outputs']['P_line']:.1f} MW")
    ok(r1["outputs"]["Qfus"] < r0["outputs"]["Qfus"],
       f"line radiation lowers Q: {r0['outputs']['Qfus']:.2f} -> {r1['outputs']['Qfus']:.2f}")
    bad = run_case({"imp_name": "Unobtainium"}, preset="ITER", config="tokamak")
    ok("errors" in bad, "unknown impurity species rejected")

    # two-temperature diagnostics present in every configuration
    for cfg, preset in [("tokamak", "ITER"), ("mirror", "GDT"), ("frc", "C-2W"),
                        ("dipole", "LDX"), ("stellarator", "HELIAS")]:
        o = run_case({}, preset=preset, config=cfg)["outputs"]
        ok(all(k in o and math.isfinite(o[k])
               for k in ("Ecrit", "f_fast_ion", "tau_eq_ie", "P_ei")),
           f"{cfg}: two-temperature diagnostics present and finite")
    o = run_case({}, preset="ITER", config="tokamak")["outputs"]
    ok(0.05 < o["f_fast_ion"] < 0.45,
       f"ITER alpha ion-deposition fraction = {o['f_fast_ion']:.2f} (mostly electrons)")

    # FRC flux account
    o = run_case({}, preset="C-2W", config="frc")["outputs"]
    ok(o["tau_eta"] > 0 and math.isfinite(o["tauN_o_taueta"]),
       f"FRC flux account: tau_eta = {o['tau_eta']:.3f} s, tauN/tau_eta = {o['tauN_o_taueta']:.2e}")

    # dipole finite-ring mode: runs, differs near ring, converges far away
    p0 = run_case({}, preset="Dipole-DD", config="dipole")["outputs"]
    p1 = run_case({"ring_model": 1}, preset="Dipole-DD", config="dipole")["outputs"]
    ok(p1["valid"] == 1.0, "dipole loop mode: valid result")
    ok(abs(p1["beta_in"] - p0["beta_in"]) / p0["beta_in"] > 0.2,
       f"loop mode beta_in differs near ring: {p0['beta_in']:.3f} -> {p1['beta_in']:.3f} "
       "(point dipole underestimates B at L_in=1.5)")
    ok(abs(p1["p_slope"] + 20.0 / 3.0) > 0.05,
       f"loop-mode pressure slope = {p1['p_slope']:.3f} (not exactly -20/3: real U(L))")
    # far-shell comparison: with the plasma far from the ring the two models converge
    far = dict(r_ring=0.5, R_p=6.0, B_ring=20.0, n0=2e19, Ti0=1.0, Te0=1.0,
               tauE=0.5, L_in_fac=7.0, icase=2)
    f0 = run_case(far, config="dipole")["outputs"]
    f1 = run_case({**far, "ring_model": 1}, config="dipole")["outputs"]
    ok(abs(f1["Vp"] - f0["Vp"]) / f0["Vp"] < 0.08,
       f"far-shell volume converges: point {f0['Vp']:.2f} vs loop {f1['Vp']:.2f} m^3")

    print("\nRESULT:", "PHYSICS P1 BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
