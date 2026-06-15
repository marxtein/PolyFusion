"""Stellarator module verification (Scheme D: single near-axis geometry).

Run: python polyfusion/tests/test_stellarator_benchmark.py

The legacy rotating-ellipse transform ``iota0 = (N/2)(k-1)^2/(k^2+1)`` and its
Floquet cross-check were removed in Scheme D together with ``kappa_s`` and the
fourier-display section cartoon.  What remains here is the genuine physics
validation that survives the API change:

1. DEGENERATION: a planar circular axis (delta_h=0) with a measured iota reduces
   the fusion physics (Pfus/Pbrem/Eth/betaT) to the tokamak funsc(kappa=1,
   delta=0) — the 0-D power account is shaping-independent given the volume.
2. GEOMETRY volume anchor: the model plasma volume of a W7-X-scale helical axis
   matches the published ~30 m^3 (axis_length geometry only).
3. W7-X record-shot ISS04 closure anchor with the MEASURED iota = 0.88
   (H_ISS04 ~ 1.1, lit. 1-1.4) — the confinement closure is unchanged.
4. NEAR-AXIS (Garren-Boozer) engine anchor: for the NAE-QA preset axis
   (Landreman-Sengupta r1 section 5.1 scaled to R0=18 m) iota_geom must equal
   the published 0.418306910215178 and the max elongation 2.41373705531443, the
   helical-axis TORSION contributes to iota (delta_h matters), and the volume
   is the EXACT integral of the drawn near-axis boundary (a few % below the
   analytic Pappus estimate; Scheme D Task 1).
5. SECTION OUTLINES for the shape view: near-axis mode, elongation varying along
   the period, each section carrying nested flux surfaces and a wall layer.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import (axis_length,  # noqa: E402
                                            section_outlines,
                                            stellarator_geometry_metrics,
                                            boundary_metrics,
                                            _nearaxis_boundary_fn)
from polyfusion.tokamak import funsc  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---- 1. circular degeneration: fusion physics == tokamak exactly ----
    # delta_h=0 -> planar circular axis -> Vp = pi*a^2 * 2*pi*R0 (the tokamak
    # circular volume); a measured iota satisfies the zero-transform guard.
    # etabar only shapes the (here irrelevant) cross-section; the 0-D power
    # account depends on the volume alone, so it must equal funsc(kappa=1,delta=0).
    st = solve_stellarator(R0=18.0, A=10.0, N_fp=5, delta_h=0.0, etabar=0.05,
                           Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0,
                           f1=0.5, B0=5.0, tauE=1.0, fHe=0.04, fimp=0.01,
                           Zimp=10, Rw=0.7, g=0.1, icase=1, iota=1.0)
    tok = funsc(18.0, 10.0, 1.0, 0.0, 0.5, 1.0, 2e20, 15.0, 1.0, 1.0, 0.5,
                5.0, 10.0, 1.0, 0.04, 0.01, 10, 0.7, 0.1, 1)
    # Vp now comes from the EXACT boundary integral (Scheme D Task 1), not the
    # analytic pi*a^2*2*pi*R0.  A PLANAR CIRCULAR axis (delta_h=0) is a
    # DEGENERATE near-axis case — constant curvature, zero torsion makes the
    # sigma/second-order equations ill-conditioned, so the solve carries ~1e-3
    # numerical noise that is sensitive to BLAS reduction order (thread count).
    # Real helical/shaped configs are bit-stable; this degenerate anchor only
    # needs ~0.3% (still a meaningful tokamak-parity check on the VOLUME — the
    # power-density parity below is exact).
    Vp_exact = math.pi * 1.8**2 * 2 * math.pi * 18.0
    ok(abs(st.Vp - Vp_exact) / Vp_exact < 3e-3,
       f"planar circular axis: Vp == pi*a^2*2*pi*R0 by exact integral "
       f"({st.Vp:.4f} vs {Vp_exact:.4f})")
    # physics parity: given the SAME plasma the 0-D power account is identical to
    # the tokamak.  betaT is volume-INTENSIVE (exact parity); Pfus/Pbrem/Eth are
    # extensive (proportional to Vp), so they carry the ~2e-4 volume-integration
    # offset — compare them PER UNIT VOLUME to isolate the (identical) physics.
    ok(abs(st.betaT - tok.betaT) / abs(tok.betaT) < 1e-9,
       f"circular degeneration: betaT == tokamak ({st.betaT:.6g})")
    for q in ("Pfus", "Pbrem", "Eth"):
        sv, tv = getattr(st, q) / st.Vp, getattr(tok, q) / tok.Vp
        ok(abs(sv - tv) / abs(tv) < 1e-9,
           f"circular degeneration: {q}/Vp == tokamak ({getattr(st, q):.6g})")

    # ---- 2. geometry volume anchor (W7-X-scale helical axis) ----
    V_w7x = math.pi * 0.51**2 * axis_length(5.5, 5, 0.25)
    ok(25 < V_w7x < 36, f"W7-X model volume = {V_w7x:.1f} m^3 (published ~30)")

    # ---- 3. W7-X record-shot ISS04 anchor with MEASURED iota ----
    # W7-X is quasi-isodynamic: single-harmonic near-axis cannot represent it, so
    # the closure uses the measured transform (the same override the W7-X preset
    # carries).  H_ISS04 must land in the literature 1-1.4 band.
    i_w7x = 0.88
    a, R, B, P_MW, nbar19, tau_meas = 0.51, 5.5, 2.5, 5.2, 8.0, 0.22
    tau = 0.134 * a**2.28 * R**0.64 * P_MW**-0.61 * nbar19**0.54 * B**0.84 * i_w7x**0.41
    H = tau_meas / tau
    ok(0.8 < H < 1.5, f"W7-X record-shot H_ISS04 = {H:.2f} with measured iota=0.88 (lit. 1-1.4)")

    # ---- 4. near-axis (Garren-Boozer) engine anchor against published values ----
    common = dict(A=10.0, Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0,
                  fT=1.0, fsig=1.0, f1=0.5, B0=5.5, tauE=0.85, fHe=0.04,
                  fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1, f_ren=1.2)
    na = solve_stellarator(R0=18.0, N_fp=3, delta_h=0.045 * 18.0,
                           etabar=0.9 / 18.0, **common)
    ok(abs(na.iota_geom - 0.418306910215178) < 1e-6,
       f"near-axis NAE-QA: iota = {na.iota_geom:.9f} (published 0.418306910)")
    ok(abs(na.elong_max - 2.41373705531443) / 2.41373705531443 < 2e-3,
       f"near-axis NAE-QA: max elongation = {na.elong_max:.4f} (published 2.4137)")
    ok(na.helicity == 0.0, "near-axis NAE-QA: helicity 0 (quasi-axisymmetric)")
    # solver Vp is the EXACT integral of the drawn near-axis boundary (Task 1):
    # it equals boundary_metrics of that boundary, and sits a few % below the
    # analytic Pappus pi*a^2*L_ax (the bean/curvature correction).
    _bfn, _nfp = _nearaxis_boundary_fn(R0=18.0, A=10.0, N_fp=3,
                                       delta_h=0.045 * 18.0, etabar=0.9 / 18.0)
    V_int, _ = boundary_metrics(_bfn, _nfp, 0.1)
    ok(abs(na.Vp - V_int) / V_int < 1e-9,
       f"near-axis volume == exact boundary integral ({na.Vp:.3f} == {V_int:.3f})")
    pap = math.pi * 1.8**2 * na.L_ax
    ok(0.9 < na.Vp / pap < 1.0,
       f"exact volume a few % below Pappus pi*a^2*L_ax ({na.Vp / pap:.4f})")
    gm = stellarator_geometry_metrics(R0=18.0, A=10.0, N_fp=3,
                                      rc=[18.0, 0.045 * 18.0],
                                      zs=[0.0, -0.045 * 18.0],
                                      etabar=0.9 / 18.0, g=0.1)
    ok(abs(gm["Vp_geom"] - math.pi * 1.8**2 * gm["L_ax"]) < 1e-9,
       "geometry-metrics Vp_geom is the analytic Pappus estimate (pi*a^2*L_ax)")
    ok(0.9 < na.Vp / gm["Vp_geom"] < 1.0,
       f"solver Vp (exact integral) is a few % below the Pappus estimate "
       f"({na.Vp / gm['Vp_geom']:.4f})")
    ok(abs(np.trapezoid(gm["profile_weight"], gm["profile_rho"]) - 1.0) < 1e-6,
       "geometry metrics profile weight integrates to 1")
    ok(abs(gm["A_flux"] - math.pi * 1.8**2) / gm["A_flux"] < 1e-12,
       "geometry metrics use flux-conserving cross-section area")
    # torsion contribution: stronger helical excursion -> different iota
    # (the legacy rotating ellipse was blind to delta_h by construction)
    na2 = solve_stellarator(R0=18.0, N_fp=3, delta_h=0.08 * 18.0,
                            etabar=0.9 / 18.0, **common)
    ok(abs(na2.iota_geom - na.iota_geom) > 0.05,
       f"near-axis iota responds to axis torsion: {na.iota_geom:.3f} -> "
       f"{na2.iota_geom:.3f} as delta_h grows")
    # quasi-helical branch: large helical excursion (r1 5.2-like axis, R0=10)
    # must land in the |helicity| = 1 QH regime with a healthy transform.
    # (The exact published 5.2 iota needs rc1 != zs1, outside this scalar API;
    # the module-level test_nearaxis_benchmark.py covers it exactly.)
    nqh = solve_stellarator(R0=10.0, N_fp=4, delta_h=2.65, etabar=-2.25 / 10.0,
                            **{**common, "A": 8.0})
    ok(abs(nqh.helicity) == 1 and nqh.iota_geom > 0.5,
       f"near-axis QH branch: helicity = {nqh.helicity:.0f}, "
       f"iota = {nqh.iota_geom:.3f} (QH regime reached)")

    # ---- 5. cross-section outlines for the shape view (near-axis) ----
    def shoelace(R, Z):
        R, Z = np.asarray(R), np.asarray(Z)
        return 0.5 * abs(np.sum(R[:-1] * Z[1:] - R[1:] * Z[:-1]))

    a = 18.0 / 10.0
    # near-axis SHAPE view: now SECOND-ORDER (bean/crescent) by default — the
    # r^2 terms break the first-order ellipse.  Sections vary in elongation
    # along the period; each carries nested flux surfaces and a wall layer.
    # NB the display boundary is drawn at a bounded display radius a_disp <= a
    # (so the r^2 cartoon never self-intersects), so its PROJECTED area is no
    # longer ~pi*a^2 — that is purely cosmetic.  The 0-D power-account anchor is
    # A_flux = pi*a^2 in stellarator_geometry_metrics, asserted separately.
    nae = section_outlines(R0=18.0, A=10.0, N_fp=3, delta_h=0.81, etabar=0.05)
    ok(nae["mode"] == "near-axis" and nae["metric_mode"] == "near-axis-r2"
       and len(nae["sections"]) == 3,
       "near-axis outlines: 3 sections, second-order (r2) metric mode")
    ok(0 < nae["a_disp"] <= nae["a"] + 1e-12,
       f"bounded display radius a_disp={nae['a_disp']:.3f} <= a={nae['a']:.3f}")
    elongs = [s["elong"] for s in nae["sections"]]
    ok(max(elongs) - min(elongs) > 0.05,
       f"near-axis elongation varies along period: {['%.2f' % e for e in elongs]}")
    for s in nae["sections"]:
        ok("surfaces" in s and len(s["surfaces"]) >= 5,
           f"near-axis section {s['label']}: nested analytic flux surfaces returned")
        ok("wall" in s and len(s["wall"]["R"]) == len(s["R"])
           and len(s["wall"]["Z"]) == len(s["Z"]),
           f"near-axis section {s['label']}: wall layer present")
        ar = shoelace(s["R"], s["Z"])
        ok(ar > 0,
           f"near-axis section {s['label']}: nonzero closed projected area ({ar:.4f})")
        ok(all(np.isfinite(s["R"])) and all(np.isfinite(s["Z"])),
           f"near-axis section {s['label']}: finite outline")
    # the 0-D power-account section area stays first-order pi*a^2 (unchanged)
    gm = stellarator_geometry_metrics(18.0, 10.0, 3, [18.0, 0.81], [0.0, -0.81], 0.05)
    ok(abs(gm["A_flux"] - math.pi * a**2) < 1e-9,
       f"power-account A_flux still pi*a^2 ({gm['A_flux']:.4f})")

    print("\nRESULT:", "STELLARATOR BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
