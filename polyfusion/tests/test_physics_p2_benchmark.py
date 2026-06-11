"""Physics batch P2 verification (docs/30): self-consistent Te, mirror
f_alpha loss-cone default, Angioni density-peaking diagnostic.

Run: python polyfusion/tests/test_physics_p2_benchmark.py

1. SELF-CONSISTENT Te (fT=0 / Te0=0 sentinels):
   - convergence: electron-channel residual ~ 0 at the solution;
   - EXACT refeed consistency: rerunning with fT fixed at fT_used must
     reproduce every power identically (the solve is a fixed point of the
     unmodified solver, not a parallel model);
   - physics direction: ITER-class D-T burning plasma -> fT_used ~ 1
     (alpha heating is mostly ELECTRON heating + strong coupling);
     weaker-coupling case (lower density) -> larger |Ti-Te| allowed;
   - mirror: BEAM Te0 solved below Ti (electron end loss + radiation);
     GDT bulk (collisional, no fast ions) equilibrates Te ~ Ti — the
     famous Te << Ti hierarchy needs the fast-ion component (batch 3).
2. MIRROR f_alpha default = sqrt(1 - 1/R_mc) (prompt loss-cone bound);
   explicit f_alpha=1 recovers the legacy closed-trap idealisation.
3. ANGIONI peaking suggestion: nu_n = 1.347 - 0.117 ln(nu_eff) - 4.03 betaT
   (NF 2007); Sn_sugg = nu_n - 1 since peak/<n> = 1+Sn for our profiles.
4. CONSISTENCY SWEEP: fT=0 / Te0=0 accepted by validation (moved from
   positive to bounds); fT<0 rejected; f_aux_e bounded; goldens untouched
   (legacy fT>0 path bit-identical).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.io import run_case  # noqa: E402
from polyfusion.configs import solve_mirror  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---- 1a. tokamak predictive Te: convergence + refeed identity ----
    r = run_case({"fT": 0}, preset="ITER", config="tokamak")
    ok("outputs" in r, "ITER fT=0 runs")
    o = r["outputs"]
    ok(o["te_mode"] == 1.0 and abs(o["te_resid"]) < 1e-6,
       f"ITER Te solve converged (resid={o['te_resid']:.1e} MW)")
    ok(0.85 < o["fT_used"] < 1.10,
       f"ITER fT_used = {o['fT_used']:.3f} (burning D-T: Te tracks Ti)")
    o2 = run_case({"fT": o["fT_used"]}, preset="ITER", config="tokamak")["outputs"]
    ok(all(abs(o[k] - o2[k]) <= 1e-9 * max(abs(o[k]), 1) for k in
           ("Pfus", "Pheat", "Pbrem", "Qfus")),
       "refeed identity: fixed fT at fT_used reproduces all powers exactly")

    # 1b. coupling direction: weaker coupling (lower density) -> Te decouples more
    lo = run_case({"fT": 0, "ni0": 2e19}, preset="ITER", config="tokamak")["outputs"]
    ok(abs(lo["fT_used"] - 1.0) > abs(o["fT_used"] - 1.0) - 1e-9,
       f"lower density decouples Te more: |fT-1| {abs(o['fT_used']-1):.3f} -> "
       f"{abs(lo['fT_used']-1):.3f}")

    # 1c. stellarator predictive Te
    s = run_case({"fT": 0}, preset="HELIAS", config="stellarator")["outputs"]
    ok(s["te_mode"] == 1.0 and abs(s["te_resid"]) < 1e-6 and 0.9 < s["fT_used"] < 1.2,
       f"HELIAS fT=0: fT_used = {s['fT_used']:.3f}, converged")

    # 1d. mirror predictive Te0
    m = run_case({"Te0": 0}, preset="BEAM", config="mirror")["outputs"]
    ok(m["te_mode"] == 1.0 and abs(m["te_resid"]) < 1e-6,
       f"BEAM Te0=0 converged (resid={m['te_resid']:.1e})")
    ok(0.2 < m["Te0_used"] < 15.0,
       f"BEAM solved Te0 = {m['Te0_used']:.2f} keV (< Ti = 15: end loss + radiation)")
    gdt = run_case({"Te0": 0}, preset="GDT", config="mirror")["outputs"]
    ok(gdt["te_mode"] == 1.0 and 0.6 < gdt["Te0_used"] / 0.25 < 1.1,
       f"GDT bulk Te0 = {gdt['Te0_used']:.3f} ~ Ti (collisional bulk equilibrates; "
       "Te<<Ti hierarchy needs fast ions, batch 3)")

    # ---- 2. mirror f_alpha loss-cone default ----
    base = dict(a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, ni0=3e20,
                Ti0=15.0, Te0=10.0, Rw=0.8, icase=1)
    d = solve_mirror(**base)                       # default: computed
    expect = math.sqrt(1.0 - 1.0 / d.R_mc)
    ok(abs(d.f_alpha_used - expect) < 1e-12,
       f"f_alpha default = sqrt(1-1/R_mc) = {d.f_alpha_used:.4f} (R_mc={d.R_mc:.1f})")
    e = solve_mirror(**base, f_alpha=1.0)
    ok(e.f_alpha_used == 1.0 and e.Pheat < d.Pheat,
       "explicit f_alpha=1 recovers legacy (smaller Pheat than loss-cone default)")
    ok(d.P_alpha_loss > 0, f"prompt alpha loss accounted: {d.P_alpha_loss:.2f} MW")

    # ---- 3. Angioni peaking diagnostic ----
    ri = run_case({}, preset="ITER", config="tokamak")
    i, inp = ri["outputs"], ri["inputs"]
    nu = (0.1 * i["Zeff"] * (i["ne0"] / (1 + inp["Sn"]) * 1e-19) * inp["R0"]
          / (i["Te0"] / (1 + inp["ST"])) ** 2)
    ok(abs(i["nu_eff_ang"] - nu) / nu < 1e-9,
       f"nu_eff formula check: {i['nu_eff_ang']:.4f} vs hand {nu:.4f}")
    ok(0.0 <= i["Sn_sugg"] < 1.2,
       f"ITER Sn_sugg = {i['Sn_sugg']:.3f} (Angioni band; compare input Sn=0.5)")

    # ---- 4. consistency sweep of the input interface ----
    bad = run_case({"fT": -0.5}, preset="ITER", config="tokamak")
    ok("errors" in bad, "fT < 0 rejected")
    bad = run_case({"f_aux_e": 1.5}, preset="ITER", config="tokamak")
    ok("errors" in bad, "f_aux_e > 1 rejected")
    okm = run_case({"Te0": 0}, preset="GDT", config="mirror")
    ok("outputs" in okm, "mirror Te0=0 passes validation (moved out of positive)")
    oks = run_case({"fT": 0}, preset="W7-X", config="stellarator")
    ok("outputs" in oks, "stellarator fT=0 passes validation")

    print("\nRESULT:", "PHYSICS P2 BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
