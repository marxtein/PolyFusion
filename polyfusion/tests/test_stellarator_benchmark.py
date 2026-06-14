"""Stellarator module verification — v2 (docs/27).

Run: python polyfusion/tests/test_stellarator_benchmark.py

1. FLOQUET cross-check: the closed-form rotating-ellipse transform
       iota0 = (N/2)(k-1)^2/(k^2+1)
   is verified against direct numerical integration of the near-axis
   field-line ODE  dz/dphi = K(phi) z  (rotating quadrupole,
   eps = M(k^2-1)/(k^2+1)), extracting the accumulated rotation angle.
2. ANALYTIC identities: iota(k=1)=0; iota(k)=iota(1/k); linear in N_fp.
3. DEVICE anchors from GEOMETRY ALONE (no fitted iota):
       W7-X (N=5, k=2.72): iota ~ 0.86-0.97 measured, V ~ 30 m^3 published
       LHD  (N=10, k=1.51): iota ~ 0.4 measured on axis
       HSX  (N=4, k=3.96):  iota ~ 1.05 (its famous value)
4. DEGENERATION: kappa_s=1, delta_h=0 reduces to a circular torus; fusion
   physics (Pfus/Pbrem/Eth/betaT) must equal tokamak funsc(kappa=1,delta=0).
5. W7-X record-shot ISS04 anchor, now with the GEOMETRIC iota.
6. NEAR-AXIS MODE (v3): etabar != 0 activates the Garren-Boozer first-order
   geometry; for the NAE-QA preset axis (Landreman-Sengupta r1 section 5.1
   scaled to R0=18 m) iota must equal the published 0.418306910215178 and the
   max elongation the published 2.41373705531443 — and unlike the rotating
   ellipse, the helical-axis TORSION contributes to iota (delta_h matters).
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import (iota_rotating_ellipse, axis_length,  # noqa: E402
                                            section_outlines,
                                            stellarator_geometry_metrics)
from polyfusion.tokamak import funsc  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def ellipse_residual(R, Z):
    """Residual of the best quadratic ellipse in normalized coords.

    A perfect rotated/translated ellipse has residual near zero for
    A*x^2 + B*x*y + C*y^2 + D*x + E*y = 1.  This intentionally catches the
    old rotating-ellipse display geometry rather than only axis-aligned cases.
    """
    R, Z = np.asarray(R), np.asarray(Z)
    Rc, Zc = np.mean(R), np.mean(Z)
    xr, yz = R - Rc, Z - Zc
    ar = max(np.max(np.abs(xr)), 1e-12)
    bz = max(np.max(np.abs(yz)), 1e-12)
    x, y = xr / ar, yz / bz
    M = np.column_stack([x * x, x * y, y * y, x, y])
    coef, *_ = np.linalg.lstsq(M, np.ones_like(x), rcond=None)
    q = M @ coef
    return float(np.sqrt(np.mean((q - 1.0) ** 2)))


def iota_floquet_numeric(kappa_s, N_fp, nsteps=2000, nturns=100):
    """Independent route: RK4-integrate the rotating-quadrupole field-line
    equations over one toroidal turn; the accumulated polar-angle rotation
    of the solution vector gives the transform."""
    M = N_fp / 2.0
    k = kappa_s
    eps = M * (k * k - 1.0) / (k * k + 1.0)

    def K(phi):
        c2, s2 = math.cos(2 * M * phi), math.sin(2 * M * phi)
        return np.array([[eps * c2, eps * s2], [eps * s2, -eps * c2]])

    phis = np.linspace(0.0, 2 * math.pi * nturns, nsteps * nturns + 1)
    h = phis[1] - phis[0]
    z = np.array([1.0, 0.0])
    theta_acc, prev = 0.0, 0.0
    for i in range(nsteps * nturns):
        p = phis[i]
        k1 = K(p) @ z
        k2 = K(p + h / 2) @ (z + h / 2 * k1)
        k3 = K(p + h / 2) @ (z + h / 2 * k2)
        k4 = K(p + h) @ (z + h * k3)
        z = z + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        ang = math.atan2(z[1], z[0])
        d = ang - prev
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        theta_acc += d
        prev = ang
        z = z / np.linalg.norm(z)
    return abs(theta_acc) / (2 * math.pi * nturns)


def main():
    # ---- 1. closed form vs numeric Floquet integration ----
    for (k, N) in [(2.0, 5), (2.72, 5), (1.51, 10), (3.96, 4)]:
        ana = iota_rotating_ellipse(k, N)
        num = iota_floquet_numeric(k, N)
        ok(abs(num - ana) / max(ana, 1e-9) < 0.02,
           f"Floquet numeric vs closed form (k={k},N={N}): {num:.4f} vs {ana:.4f}")

    # ---- 2. analytic identities ----
    ok(iota_rotating_ellipse(1.0, 5) == 0.0, "iota(k=1)=0 (circle: no transform)")
    ok(abs(iota_rotating_ellipse(2.5, 5) - iota_rotating_ellipse(1 / 2.5, 5)) < 1e-12,
       "iota invariant under k -> 1/k")
    ok(abs(iota_rotating_ellipse(2.0, 10) - 2 * iota_rotating_ellipse(2.0, 5)) < 1e-12,
       "iota linear in N_fp")

    # ---- 3. device anchors from geometry alone ----
    i_w7x = iota_rotating_ellipse(2.72, 5)
    ok(0.80 < i_w7x < 1.0, f"W7-X geometry iota = {i_w7x:.3f} (measured 0.86-0.97)")
    V_w7x = math.pi * 0.51**2 * axis_length(5.5, 5, 0.25)
    ok(25 < V_w7x < 36, f"W7-X model volume = {V_w7x:.1f} m^3 (published ~30)")
    i_lhd = iota_rotating_ellipse(1.51, 10)
    ok(0.3 < i_lhd < 0.5, f"LHD geometry iota = {i_lhd:.3f} (measured ~0.4 on axis)")
    i_hsx = iota_rotating_ellipse(3.96, 4)
    ok(0.95 < i_hsx < 1.15, f"HSX geometry iota = {i_hsx:.3f} (famous ~1.05)")

    # ---- 4. kappa_s=1 degeneration: fusion physics == tokamak exactly ----
    st = solve_stellarator(R0=18.0, A=10.0, kappa_s=1.0, N_fp=5, delta_h=0.0,
                           Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0,
                           f1=0.5, B0=5.0, tauE=1.0, fHe=0.04, fimp=0.01,
                           Zimp=10, Rw=0.7, g=0.1, icase=1, iota=1.0)
    tok = funsc(18.0, 10.0, 1.0, 0.0, 0.5, 1.0, 2e20, 15.0, 1.0, 1.0, 0.5,
                5.0, 10.0, 1.0, 0.04, 0.01, 10, 0.7, 0.1, 1)
    for q in ("Pfus", "Pbrem", "Eth", "betaT"):
        sv, tv = getattr(st, q), getattr(tok, q)
        ok(abs(sv - tv) / abs(tv) < 1e-9, f"k_s=1 degeneration: {q} == tokamak ({sv:.6g})")

    # ---- 5. W7-X record-shot ISS04 anchor with GEOMETRIC iota ----
    a, R, B, P_MW, nbar19, tau_meas = 0.51, 5.5, 2.5, 5.2, 8.0, 0.22
    tau = 0.134 * a**2.28 * R**0.64 * P_MW**-0.61 * nbar19**0.54 * B**0.84 * i_w7x**0.41
    H = tau_meas / tau
    ok(0.8 < H < 1.5, f"W7-X record-shot H_ISS04 = {H:.2f} with geometric iota (lit. 1-1.4)")

    # ---- 6. near-axis (Garren-Boozer) mode against published values ----
    common = dict(A=10.0, kappa_s=2.41, Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0,
                  fT=1.0, fsig=1.0, f1=0.5, B0=5.5, tauE=0.85, fHe=0.04,
                  fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1, f_ren=1.2)
    na = solve_stellarator(R0=18.0, N_fp=3, delta_h=0.045 * 18.0,
                           etabar=0.9 / 18.0, **common)
    ok(abs(na.iota_geom - 0.418306910215178) < 1e-6,
       f"near-axis NAE-QA: iota = {na.iota_geom:.9f} (published 0.418306910)")
    ok(abs(na.elong_max - 2.41373705531443) / 2.41373705531443 < 2e-3,
       f"near-axis NAE-QA: max elongation = {na.elong_max:.4f} (published 2.4137)")
    ok(na.helicity == 0.0, "near-axis NAE-QA: helicity 0 (quasi-axisymmetric)")
    ok(abs(na.Vp - math.pi * 1.8**2 * na.L_ax) / na.Vp < 1e-12,
       "near-axis volume follows Pappus with flux-conserving section area")
    gm = stellarator_geometry_metrics(R0=18.0, A=10.0, kappa_s=2.41, N_fp=3,
                                      delta_h=0.045 * 18.0, etabar=0.9 / 18.0,
                                      g=0.1)
    ok(abs(gm["Vp_geom"] - na.Vp) / na.Vp < 1e-12,
       "geometry metrics volume matches solver Vp")
    ok(abs(np.trapezoid(gm["profile_weight"], gm["profile_rho"]) - 1.0) < 1e-6,
       "geometry metrics profile weight integrates to 1")
    ok(abs(gm["A_flux"] - math.pi * 1.8**2) / gm["A_flux"] < 1e-12,
       "geometry metrics use flux-conserving cross-section area")
    # torsion contribution: stronger helical excursion -> different iota
    # (the legacy rotating ellipse is blind to delta_h by construction)
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

    # ---- 7. cross-section outlines for the shape view ----
    def shoelace(R, Z):
        R, Z = np.asarray(R), np.asarray(Z)
        return 0.5 * abs(np.sum(R[:-1] * Z[1:] - R[1:] * Z[:-1]))

    a = 18.0 / 10.0
    # legacy rotating ellipse: 3 closed sections, exact area pi*a^2, rotated
    leg = section_outlines(R0=18.0, A=10.0, kappa_s=2.7, N_fp=5, delta_h=0.9)
    legm = stellarator_geometry_metrics(R0=18.0, A=10.0, kappa_s=2.7,
                                        N_fp=5, delta_h=0.9, etabar=0.0, g=0.1)
    ok(abs(legm["A_flux"] - math.pi * a**2) / (math.pi * a**2) < 1e-12,
       "legacy metrics: flux area is pi*a^2")
    ok(abs(legm["Vp_geom"] - math.pi * a**2 * axis_length(18.0, 5, 0.9))
       / legm["Vp_geom"] < 1e-12,
       "legacy metrics: Vp_geom = pi*a^2*L_ax")
    ok(leg["mode"] == "fourier-display" and leg["metric_mode"] == "rotating-ellipse"
       and len(leg["sections"]) == 3,
       "legacy outlines: 3 non-elliptic display sections with rotating-ellipse metrics")
    residuals = [ellipse_residual(s["R"], s["Z"]) for s in leg["sections"]]
    ok(max(residuals) > 0.05,
       f"stellarator display sections are non-elliptic (residuals={['%.3f' % r for r in residuals]})")
    spans = [(max(s["R"]) - min(s["R"]), max(s["Z"]) - min(s["Z"])) for s in leg["sections"]]
    ok(max(w / h for w, h in spans) / min(w / h for w, h in spans) > 1.8,
       "stellarator display sections change character between toroidal cuts")
    for s in leg["sections"]:
        ar = shoelace(s["R"], s["Z"])
        ok(abs(ar - math.pi * a**2) / (math.pi * a**2) < 1e-3,
           f"legacy section {s['label']}: area = pi*a^2 ({ar:.4f})")
        ok("surfaces" in s and len(s["surfaces"]) >= 5,
           f"legacy section {s['label']}: nested analytic flux surfaces returned")
        edge = s["surfaces"][-1]
        mid = min(s["surfaces"], key=lambda q: abs(q["rho"] - 0.5))
        edge_area = shoelace(edge["R"], edge["Z"])
        mid_area = shoelace(mid["R"], mid["Z"])
        ok(abs(edge_area - ar) / ar < 1e-12,
           f"legacy section {s['label']}: rho=1 surface matches boundary")
        ok(abs(mid_area / edge_area - mid["rho"] ** 2) < 2e-3,
           f"legacy section {s['label']}: area scales as rho^2")
    # near-axis: sections vary in elongation along the period; projected area
    # within ~20% of pi*a^2 (section plane is tilted vs the R-Z plane)
    nae = section_outlines(R0=18.0, A=10.0, kappa_s=2.41, N_fp=3,
                           delta_h=0.81, etabar=0.05)
    ok(nae["mode"] == "near-axis" and len(nae["sections"]) == 3,
       "near-axis outlines: 3 sections")
    elongs = [s["elong"] for s in nae["sections"]]
    ok(max(elongs) - min(elongs) > 0.05,
       f"near-axis elongation varies along period: {['%.2f' % e for e in elongs]}")
    for s in nae["sections"]:
        ok("surfaces" in s and len(s["surfaces"]) >= 5,
           f"near-axis section {s['label']}: nested analytic flux surfaces returned")
        ar = shoelace(s["R"], s["Z"])
        ok(abs(ar - math.pi * a**2) / (math.pi * a**2) < 0.2,
           f"near-axis section {s['label']}: projected area ~ pi*a^2 ({ar:.3f})")
        ok(all(np.isfinite(s["R"])) and all(np.isfinite(s["Z"])),
           f"near-axis section {s['label']}: finite outline")

    print("\nRESULT:", "STELLARATOR BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
