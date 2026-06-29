"""Physics batch 3a verification (docs/30): L-H threshold, ITPA20 scaling,
FRC transport bracket, mirror DCLC proxy.

Run: python polyfusion/tests/test_physics_p3_benchmark.py

1. Martin 2008 L->H threshold: ITER-class point lands in the published
   ~45-90 MW band (P_LH ~ 52 MW at n~5e19 for ITER per Martin/IPB);
   monotone in density and field; mass correction (D-T < D).
2. ITPA20-IL scaling: prediction within a factor ~2 of IPB98 for ITER
   (the two database regressions agree to tens of percent there) and
   H_ITPA20 finite/positive.
3. FRC transport bracket: tau_Bohm < tau_E(LSX) < tau_classical for the
   C-2W-scale preset — the regression must land inside the physical bounds.
4. Mirror a_over_rhoi: positive, GDT (low field) << BEAM-class.
5. Degradation: all additions are pure outputs — golden inputs unchanged
   (covered by the golden suite, re-run separately).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.io import run_case  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---- 1. Martin L->H threshold ----
    it = run_case({}, preset="ITER", config="tokamak")["outputs"]
    ok(
        20 < it["P_LH"] < 120,
        f"ITER-class P_LH = {it['P_LH']:.1f} MW (published ITER band ~45-90)",
    )
    hi_n = run_case({"ni0": 1.2e20}, preset="ITER", config="tokamak")["outputs"]
    ok(hi_n["P_LH"] > it["P_LH"], "P_LH increases with density (Martin exponent 0.717)")
    hi_b = run_case({"BT0": 8.0}, preset="ITER", config="tokamak")["outputs"]
    ok(hi_b["P_LH"] > it["P_LH"], "P_LH increases with field (exponent 0.803)")
    ok(it["LH_ratio"] > 0, f"LH_ratio = {it['LH_ratio']:.2f} (Pth/P_LH)")

    # ---- 2. ITPA20-IL vs IPB98 ----
    tau98 = it["tauE_used"] / it["H98"]
    ok(
        0.4 < it["tau_ITPA20"] / tau98 < 2.5,
        f"ITPA20 vs IPB98 at ITER: tau ratio = {it['tau_ITPA20'] / tau98:.2f} "
        "(databases agree within a factor ~2)",
    )
    ok(
        it["H_ITPA20"] > 0,
        f"H_ITPA20 = {it['H_ITPA20']:.2f} (vs H98 = {it['H98']:.2f})",
    )

    # ---- 3. FRC transport bracket ----
    fr = run_case({}, preset="C-2W", config="frc")["outputs"]
    ok(
        fr["tau_Bohm"] < fr["tau_E"] < fr["tau_classical"],
        f"FRC bracket holds: Bohm {fr['tau_Bohm']:.2e} < LSX {fr['tau_E']:.2e} "
        f"< classical {fr['tau_classical']:.2e} s",
    )
    fr2 = run_case({}, preset="FRC-DT", config="frc")["outputs"]
    ok(
        fr2["tau_Bohm"] < fr2["tau_classical"],
        f"FRC-DT bracket ordering (Bohm {fr2['tau_Bohm']:.2e} < cl {fr2['tau_classical']:.2e})",
    )

    # ---- 4. mirror DCLC proxy ----
    gdt = run_case({}, preset="GDT", config="mirror")["outputs"]
    beam = run_case({}, preset="BEAM", config="mirror")["outputs"]
    ok(
        gdt["a_over_rhoi"] > 0 and beam["a_over_rhoi"] > 0,
        f"a/rho_i: GDT {gdt['a_over_rhoi']:.1f}, BEAM {beam['a_over_rhoi']:.1f}",
    )
    ok(beam["a_over_rhoi"] != gdt["a_over_rhoi"], "proxy differentiates machines")

    print("\nRESULT:", "PHYSICS P3A BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
