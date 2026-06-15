"""Real-machine stellarator presets render literature-calibrated boundaries.

Single-harmonic near-axis cannot represent W7-X (bean->triangle), LHD (l=2
heliotron rotating ellipse), HSX (QHS bean) or CFQS (QA D-shape) — it gave
needle/microscopic ellipses, and for LHD's planar axis all three toroidal cuts
collapsed onto each other ("only one cross-section drawn").

These presets now carry an explicit ``shape`` descriptor: truncated (|m|,|n|<=2),
normalized boundary Fourier harmonics taken from PUBLIC DESC equilibria
(desc/examples), evaluated in DESC's double-Fourier product basis and rescaled to
the preset R0/a.  section_outlines draws their real character: three DISTINCT,
simple, sane-sized cross-sections.  Power account is untouched (machines override
iota/Vp/Sw).

Equilibrium sources:
  * W7-X (DESC desc/examples/W7-X, 5 periods): cross-section morphs bean
    (phi=0, tall) -> wide triangle (half period).  Verified against the real
    boundary (offline reconstruction).
  * LHD: canonical l=2 rotating-ellipse heliotron (DESC HELIOTRON structure) at
    N_fp=10 — elliptical cross-section rotating poloidally with toroidal angle.
  * CFQS: DESC desc/examples/ESTELL (2-field-period quasi-axisymmetric) proxy.
  * HSX (DESC desc/examples/HSX, 4 periods): quasi-helically symmetric.

Run: python polyfusion/tests/test_stellarator_machine_boundary.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets  # noqa: E402
from polyfusion.configs.stellarator import section_outlines  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _selfint(R, Z):
    R = np.asarray(R[:-1], float); Z = np.asarray(Z[:-1], float)
    n = R.size; P = list(zip(R, Z)); c = 0

    def ccw(p, q, r):
        return (r[1]-p[1])*(q[0]-p[0]) > (q[1]-p[1])*(r[0]-p[0])
    for i in range(n):
        for j in range(i+2, n):
            if i == 0 and j == n-1:
                continue
            a, b, cc, d = P[i], P[(i+1) % n], P[j], P[(j+1) % n]
            if ccw(a, cc, d) != ccw(b, cc, d) and ccw(a, b, cc) != ccw(a, b, d):
                c += 1
    return c


def _box_elong(R, Z):
    R = np.asarray(R); Z = np.asarray(Z)
    return (Z.max()-Z.min())/(R.max()-R.min())


def _concave_frac(R, Z):
    R = np.asarray(R[:-1], float); Z = np.asarray(Z[:-1], float); n = R.size
    cr = []
    for i in range(n):
        ax, ay = R[(i+1) % n]-R[i], Z[(i+1) % n]-Z[i]
        bx, by = R[(i+2) % n]-R[(i+1) % n], Z[(i+2) % n]-Z[(i+1) % n]
        cr.append(ax*by - ay*bx)
    cr = np.array(cr); sgn = np.sign(np.sum(cr))
    return float(np.mean(np.sign(cr) != sgn))


def _distinct(secs):
    """min pairwise boundary difference across the 3 cuts (normalized by a)."""
    d = 1e9
    for i in range(len(secs)):
        for j in range(i+1, len(secs)):
            Ri, Zi = np.array(secs[i]["R"]), np.array(secs[i]["Z"])
            Rj, Zj = np.array(secs[j]["R"]), np.array(secs[j]["Z"])
            d = min(d, float(np.max(np.hypot(Ri-Rj, Zi-Zj))))
    return d


MACHINES = ["W7-X", "LHD", "HSX", "CFQS"]
CONCEPTS = ["HELIAS", "NAE-QA"]


def main():
    presets, _ = load_presets("stellarator")

    for name in MACHINES:
        sh = section_outlines(**presets[name])
        a = sh["a"]
        ok("boundary" in sh["metric_mode"],
           f"{name}: explicit machine boundary ({sh['metric_mode']})")
        ok(len(sh["sections"]) == 3, f"{name}: 3 sections")
        # all three cuts are DISTINCT (this is exactly the LHD bug)
        dd = _distinct(sh["sections"])
        ok(dd > 0.05 * a,
           f"{name}: three cuts are distinct (min pairwise diff {dd:.3f} m)")
        for s in sh["sections"]:
            R, Z = s["R"], s["Z"]
            ok(_selfint(R, Z) == 0, f"{name}/{s['label']}: simple closed curve")
            cR, cZ = np.mean(R[:-1]), np.mean(Z[:-1])
            ext = float(np.max(np.hypot(np.array(R)-cR, np.array(Z)-cZ)))
            ok(0.4*a <= ext <= 4*a,
               f"{name}/{s['label']}: sane size (extent {ext:.3f} ~ a={a:.3f})")
            ok("wall" in s and len(s["wall"]["R"]) == len(R),
               f"{name}/{s['label']}: wall layer present")

    # W7-X: bean (concave) at one cut, strongly elongated at another
    w = section_outlines(**presets["W7-X"])["sections"]
    ok(max(_concave_frac(s["R"], s["Z"]) for s in w) > 0.05,
       "W7-X: at least one bean (concave) cross-section")
    elongs = [_box_elong(s["R"], s["Z"]) for s in w]
    ok(max(elongs) - min(elongs) > 0.5,
       f"W7-X: cross-section morphs bean<->triangle (box-elong {['%.2f'%e for e in elongs]})")

    # LHD: rotating ellipse -> box elongation swings strongly across cuts
    lh = section_outlines(**presets["LHD"])["sections"]
    le = [_box_elong(s["R"], s["Z"]) for s in lh]
    ok(max(le) / min(le) > 1.5,
       f"LHD: rotating ellipse (box-elong swing {['%.2f'%e for e in le]})")

    # concept reactors stay on the near-axis path
    for name in CONCEPTS:
        sh = section_outlines(**presets[name])
        ok("near-axis" in sh["metric_mode"],
           f"{name}: still near-axis ({sh['metric_mode']})")

    print("\nRESULT:", "MACHINE BOUNDARY CHECKS PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
