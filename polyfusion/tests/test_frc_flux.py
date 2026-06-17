"""FRC nested flux-surface construction (audit docs/42 P0+P1).

Run: python polyfusion/tests/test_frc_flux.py

The rigid-rotor midplane poloidal flux is analytic,
    psi_tilde(x) = ln[ cosh(K (2 x^2 - 1)) / cosh(K) ],   x = r / r_s,
with psi=0 on the magnetic axis (x=0) AND the separatrix radius (x=1), and the
minimum (the O point) at x = 1/sqrt(2).  The nested interior flux surfaces are
the level sets psi=const in (psi_o, 0), placed at their analytic midplane radii
and closed into loops around the O-point ring for the shape view.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.frc import (  # noqa: E402
    _rr_flux_norm,
    _rr_flux_radii,
    _frc_nested_surfaces,
    _mrr_separatrix,
    frc_shape_outlines,
    _solve_K,
)

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    K = 1.0
    xo = 1.0 / math.sqrt(2.0)
    psi_o = -math.log(math.cosh(K))

    # ---- 1. analytic midplane flux: zeros at axis & separatrix, min at O ----
    ok(abs(_rr_flux_norm(0.0, K)) < 1e-12, "psi_tilde(0) = 0 (magnetic axis)")
    ok(abs(_rr_flux_norm(1.0, K)) < 1e-12, "psi_tilde(1) = 0 (separatrix radius)")
    ok(abs(_rr_flux_norm(xo, K) - psi_o) < 1e-12,
       f"psi_tilde(1/sqrt2) = -ln cosh K = {psi_o:.6f} (O point, the minimum)")
    ok(_rr_flux_norm(0.5, K) < 0 and _rr_flux_norm(0.9, K) < 0,
       "interior flux is negative (below the psi=0 separatrix)")

    # ---- 2. flux radii: inversion round-trips, correct ordering ----
    for frac in (0.2, 0.5, 0.8):
        psi_star = psi_o * (1.0 - frac)        # in (psi_o, 0)
        x_in, x_out = _rr_flux_radii(psi_star, K)
        ok(0.0 < x_in < xo < x_out < 1.0,
           f"frac={frac}: 0 < x_in={x_in:.4f} < 1/sqrt2 < x_out={x_out:.4f} < 1")
        ok(abs(_rr_flux_norm(x_in, K) - psi_star) < 1e-9
           and abs(_rr_flux_norm(x_out, K) - psi_star) < 1e-9,
           f"frac={frac}: both radii reproduce psi*={psi_star:.5f}")

    # ---- 2b. limits: psi->0 gives (0,1); psi->psi_o gives (1/sqrt2,1/sqrt2) ----
    xi0, xo0 = _rr_flux_radii(-1e-9, K)
    ok(xi0 < 1e-3 and abs(xo0 - 1.0) < 1e-3, "psi->0^- radii -> (0, 1)")
    xim, xom = _rr_flux_radii(psi_o * (1 - 1e-9), K)
    ok(abs(xim - xo) < 1e-3 and abs(xom - xo) < 1e-3,
       "psi->psi_o radii collapse to the O-point ring 1/sqrt2")

    # ---- 3. nested surfaces: closed, nested, inside the SEPARATRIX ENVELOPE ----
    r_s, l_s, m = 0.5, 5.0, 4.0
    b = l_s / 2.0
    z_arch, r_arch = _mrr_separatrix(r_s, l_s, m)        # upper arch r_sep(z)
    def r_sep(z):
        return r_s * np.sqrt(np.clip(1.0 - np.abs(np.asarray(z) / b) ** m, 0.0, 1.0))
    surfs = _frc_nested_surfaces(z_arch, r_arch, r_s, K, n_levels=8)
    ok(len(surfs) == 8, "requested 8 nested surfaces returned")
    mid_r2 = []
    mins = []
    z_amps = []
    for s in surfs:
        z = np.asarray(s["z"]); r = np.asarray(s["r"])
        ok(abs(r[0] - r[-1]) < 1e-9 and abs(z[0] - z[-1]) < 1e-9,
           f"surface psi={s['psi']:.4f} is a closed loop")
        # the binding correctness check: every point inside r_sep(z), not just
        # the midplane width (this is the test that the first cut was missing)
        over = float(np.max(r - r_sep(z)))
        ok(over <= 1e-9 and r.min() >= -1e-9,
           f"surface psi={s['psi']:.4f} inside separatrix envelope "
           f"(max overshoot {over:.2e})")
        ok(np.abs(z).max() < b + 1e-9,
           f"surface psi={s['psi']:.4f} within half-length |z| < l_s/2")
        mid_r2.append(r.max())
        mins.append(r.min())
        z_amps.append(np.abs(z).max())
    ok(all(x < y for x, y in zip(mid_r2, mid_r2[1:])),
       "surfaces nest: outer radius strictly increasing")
    ok(all(x > y for x, y in zip(mins, mins[1:])),
       "surfaces nest: inner radius strictly decreasing (outer reach toward axis)")
    ok(all(x < y for x, y in zip(z_amps, z_amps[1:])),
       "surfaces nest: axial amplitude strictly increasing")
    r_o = r_s / math.sqrt(2.0)
    # the family must SPAN from near the axis (outermost) to the O point ring
    # (innermost): the flux fills the whole confined band, not just a ring far
    # from the axis (user feedback: "离轴太远").
    ok(mins[-1] < 0.45 * r_o,
       f"outermost interior surface reaches toward the axis (min r={mins[-1]:.3f} < 0.45 r_o={0.45*r_o:.3f})")
    ok(mins[0] > 0.55 * r_o,
       f"innermost surface hugs the O-point ring (min r={mins[0]:.3f} > 0.55 r_o={0.55*r_o:.3f})")

    # ---- 4. outline dict carries surfaces + O/X points (both modes) ----
    for mode in ("superellipse", "mrr"):
        d = frc_shape_outlines(r_s=0.5, l_s=5.0, r_w=0.7, f_shape=0.85,
                               sep_model=mode)
        ok(isinstance(d.get("surfaces"), list) and len(d["surfaces"]) > 0,
           f"{mode}: outline carries non-empty nested surfaces")
        # upper (r>0) and lower (r<0) O-point families are SEPARATE closed
        # curves — never merged into one polyline (the merge drew a spurious
        # vertical connector across the axis).
        sign_consistent = all(
            (min(s["r"]) > -1e-9) or (max(s["r"]) < 1e-9) for s in d["surfaces"])
        ok(sign_consistent,
           f"{mode}: each surface lies entirely on one side of the axis (no merge connector)")
        op = d.get("o_points"); xp = d.get("x_points")
        ok(op is not None and abs(op["r"][0] - 0.5 / math.sqrt(2)) < 1e-9
           and abs(op["z"][0]) < 1e-12,
           f"{mode}: O-point at (z=0, r=r_s/sqrt2)")
        ok(xp is not None and abs(xp["z"][0] - 2.5) < 1e-9
           and abs(xp["r"][0]) < 1e-12,
           f"{mode}: X-point at (z=+-l_s/2, r=0)")
        rw = 0.7
        inside = all(max(np.abs(s["r"])) < rw for s in d["surfaces"])
        ok(inside, f"{mode}: all nested surfaces inside the wall r_w")
        # every surface point must sit inside the drawn separatrix envelope
        sz = np.array(d["separatrix"]["z"]); sr = np.array(d["separatrix"]["r"])
        up = sr >= -1e-12; zz = sz[up]; rr = sr[up]
        o = np.argsort(zz); zz, rr = zz[o], rr[o]
        # check |r| vs the envelope so upper (+r_o) and lower (-r_o) families
        # are both covered by the symmetric arch
        worst = 0.0
        for s in d["surfaces"]:
            z = np.array(s["z"]); r = np.abs(np.array(s["r"]))
            worst = max(worst, float(np.max(r - np.interp(z, zz, rr))))
        ok(worst <= 1e-6, f"{mode}: surfaces inside separatrix envelope "
                          f"(max overshoot {worst:.2e})")

        # ---- open SOL field lines OUTSIDE the separatrix (audit docs/42 P2) ----
        ol = d.get("open_lines")
        ok(isinstance(ol, list) and len(ol) > 0,
           f"{mode}: outline carries open SOL field lines")
        worst_in = 0.0      # how far INSIDE the separatrix (should be ~0: outside)
        max_r = 0.0
        spans = True
        for s in ol:
            z = np.array(s["z"]); r = np.abs(np.array(s["r"]))
            worst_in = max(worst_in, float(np.max(np.interp(z, zz, rr) - r)))
            max_r = max(max_r, float(r.max()))
            spans = spans and (np.abs(z).max() > 2.5)   # extends past |z|=l_s/2
        ok(worst_in <= 1e-6,
           f"{mode}: open lines stay OUTSIDE the separatrix (max intrusion {worst_in:.2e})")
        ok(max_r <= rw + 1e-9, f"{mode}: open lines stay inside the wall r_w")
        ok(spans, f"{mode}: open lines extend past the separatrix ends (open, not closed)")
        ok(all((min(s["r"]) > -1e-9) or (max(s["r"]) < 1e-9) for s in ol),
           f"{mode}: open lines are sign-consistent (separate upper/lower)")

    print("\nRESULT:", "FRC FLUX PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
