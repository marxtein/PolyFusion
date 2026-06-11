"""Near-axis geometry verification against pyQSC published reference values.

Run: python polyfusion/tests/test_nearaxis_benchmark.py

All reference numbers below are taken verbatim from the pyQSC test suite
(github.com/landreman/pyQSC, qsc/tests/), which itself is validated against
the Fortran quasisymmetry code and the published values of Landreman,
Sengupta & Plunk, J. Plasma Phys. 85 (2019) 905850103:

1. CURVATURE/TORSION goldens: rc=[1.3,0.3,0.01,-0.001], zs=[0,0.4,-0.02,-0.003],
   nfp=5, nphi=15 -> 15 exact values each (pyQSC asserts rtol=1e-13).
2. IOTA / ELONGATION / HELICITY goldens for the published stellarator-symmetric
   r1 sections (5.3 is NON-symmetric — zc!=0, sigma0=-0.6 — outside the scope
   of this symmetric-only implementation, so it is not included):
       r1 section 5.1: iota = 0.418306910215178, max_elong = 2.41373705531443
       r1 section 5.2: iota = 1.93109725535729,  max_elong = 3.08125973323805
3. INVARIANCES: scale invariance (lengths * s, etabar / s), etabar-sign
   invariance, grid-resolution convergence.
4. LIMITS: planar circular axis -> iota = 0 (axisymmetry); axis length of the
   circular axis = 2*pi*R0.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.nearaxis import solve_near_axis, spectral_diff_matrix  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


# pyQSC golden arrays (qsc/tests/test_qsc.py, test_curvature_torsion)
GOLD_CURV = [1.74354628565018, 1.61776632275718, 1.5167042487094,
             1.9179603622369, 2.95373444883134, 3.01448808361584,
             1.7714523990583, 1.02055493647363, 1.02055493647363,
             1.77145239905828, 3.01448808361582, 2.95373444883135,
             1.91796036223691, 1.5167042487094, 1.61776632275717]
GOLD_TORS = [0.257226801231061, -0.131225053326418, -1.12989287766591,
             -1.72727988032403, -1.48973327005739, -1.34398161921833,
             -1.76040161697108, -2.96573007082039, -2.96573007082041,
             -1.7604016169711, -1.34398161921833, -1.48973327005739,
             -1.72727988032403, -1.12989287766593, -0.13122505332643]

# (name, rc, zs, nfp, etabar, iota_ref, max_elong_ref, helicity_ref)
R1_CASES = [
    ("r1 section 5.1", [1, 0.045], [0, -0.045], 3, -0.9,
     0.418306910215178, 2.41373705531443, 0),
    ("r1 section 5.2", [1, 0.265], [0, -0.21], 4, -2.25,
     1.93109725535729, 3.08125973323805, -1),
]


def main():
    # ---- 0. spectral differentiation sanity ----
    n, period = 15, 2 * math.pi / 5
    D = spectral_diff_matrix(n, period)
    t = np.linspace(0, period, n, endpoint=False)
    f = np.sin(2 * 2 * math.pi / period * t)
    fp = 2 * 2 * math.pi / period * np.cos(2 * 2 * math.pi / period * t)
    ok(np.max(np.abs(D @ f - fp)) < 1e-10, "spectral D exact on resolved sin mode")

    # ---- 1. curvature / torsion goldens (pyQSC, rtol 1e-13) ----
    na = solve_near_axis([1.3, 0.3, 0.01, -0.001], [0, 0.4, -0.02, -0.003],
                         nfp=5, etabar=1.0, nphi=15)
    ok(np.allclose(na.curvature, GOLD_CURV, rtol=1e-11, atol=1e-11),
       f"curvature matches pyQSC golden (max dev {np.max(np.abs(na.curvature - GOLD_CURV)):.2e})")
    ok(np.allclose(na.torsion, GOLD_TORS, rtol=1e-11, atol=1e-11),
       f"torsion matches pyQSC golden (max dev {np.max(np.abs(na.torsion - GOLD_TORS)):.2e})")

    # ---- 2. published r1 configurations: iota, elongation, helicity ----
    for name, rc, zs, nfp, etab, iota_ref, elong_ref, hel_ref in R1_CASES:
        na = solve_near_axis(rc, zs, nfp, etab, nphi=63)
        ok(abs(na.iota - iota_ref) / abs(iota_ref) < 1e-8,
           f"{name}: iota = {na.iota:.12f} (ref {iota_ref})")
        ok(abs(na.max_elongation - elong_ref) / elong_ref < 2e-3,
           f"{name}: max elongation = {na.max_elongation:.6f} (ref {elong_ref})")
        ok(na.helicity == hel_ref, f"{name}: helicity = {na.helicity} (ref {hel_ref})")

    # ---- 3a. scale invariance: lengths * s, etabar / s -> same iota ----
    s = 18.0
    a = solve_near_axis([1, 0.045], [0, -0.045], 3, -0.9, nphi=63)
    b = solve_near_axis([s, 0.045 * s], [0, -0.045 * s], 3, -0.9 / s, nphi=63)
    ok(abs(a.iota - b.iota) < 1e-10, f"iota scale-invariant ({a.iota:.9f} vs {b.iota:.9f})")
    ok(abs(b.axis_length - s * a.axis_length) / (s * a.axis_length) < 1e-12,
       "axis length scales linearly")

    # ---- 3b. etabar sign invariance (enters only squared) ----
    c = solve_near_axis([1, 0.045], [0, -0.045], 3, +0.9, nphi=63)
    ok(abs(a.iota - c.iota) < 1e-12, "iota invariant under etabar -> -etabar")

    # ---- 3c. grid convergence ----
    d = solve_near_axis([1, 0.045], [0, -0.045], 3, -0.9, nphi=31)
    ok(abs(d.iota - a.iota) < 1e-9, f"iota converged already at nphi=31 (dev {abs(d.iota-a.iota):.1e})")

    # ---- 4. limits ----
    e = solve_near_axis([5.5], [0.0], 5, -0.9, nphi=31)
    ok(abs(e.iota) < 1e-10, f"planar circular axis: iota = {e.iota:.2e} (axisymmetric -> 0)")
    ok(abs(e.axis_length - 2 * math.pi * 5.5) < 1e-9, "circular axis length = 2*pi*R0")

    print("\nRESULT:", "NEAR-AXIS BENCHMARK PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
