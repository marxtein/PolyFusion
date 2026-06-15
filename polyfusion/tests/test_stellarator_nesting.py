"""Nested flux surfaces must round toward the axis (bean fades inward).

Bug: machine-boundary nested surfaces were uniform scaled copies of the boundary
toward the area-centroid, so every inner surface was a self-similar mini-bean
(unphysical — real flux surfaces become elliptical toward the axis, the bean is
only the outer surface).  Fix: scale each poloidal harmonic m by rho^|m|, so the
m=2 bean term fades as rho^2 and inner surfaces become the m=1 ellipse.

Run: python polyfusion/tests/test_stellarator_nesting.py
"""

import os
import sys

import numpy as np
from matplotlib.path import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets  # noqa: E402
from polyfusion.configs.stellarator import section_outlines  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _pts_outside(inner, outer):
    """How many vertices of ``inner`` lie outside the ``outer`` polygon."""
    Ri, Zi = np.asarray(inner["R"]), np.asarray(inner["Z"])
    poly = Path(np.column_stack([np.asarray(outer["R"]), np.asarray(outer["Z"])]))
    return int((~poly.contains_points(np.column_stack([Ri, Zi]))).sum())


def assert_strictly_nested(name):
    """Every flux surface must lie fully inside the next one out — at every
    toroidal cut, for every adjacent pair.  The W7-X phi=0 bean used to fail
    here (the rho=0.85 surface poked OUTSIDE the boundary near the bean tip)."""
    sh = section_outlines(**load_presets("stellarator")[0][name])
    for sec in sh["sections"]:
        surfs = sec["surfaces"]
        for i in range(len(surfs) - 1):
            out = _pts_outside(surfs[i], surfs[i + 1])
            ok(out == 0,
               f"{name} {sec['label']}: surface {i} (rho={surfs[i]['rho']:.2f}) "
               f"fully inside surface {i+1} ({out} pts outside)")


def _concave_frac(R, Z):
    R = np.asarray(R[:-1], float); Z = np.asarray(Z[:-1], float); n = R.size
    cr = []
    for i in range(n):
        ax, ay = R[(i+1) % n]-R[i], Z[(i+1) % n]-Z[i]
        bx, by = R[(i+2) % n]-R[(i+1) % n], Z[(i+2) % n]-Z[(i+1) % n]
        cr.append(ax*by - ay*bx)
    cr = np.array(cr); sgn = np.sign(np.sum(cr))
    return float(np.mean(np.sign(cr) != sgn))


def main():
    presets, _ = load_presets("stellarator")
    sh = section_outlines(**presets["W7-X"])
    bean = sh["sections"][0]               # phi=0 bean plane
    surfs = bean["surfaces"]
    boundary = surfs[-1]                    # rho = 1
    inner = surfs[0]                        # smallest rho

    cb = _concave_frac(boundary["R"], boundary["Z"])
    ci = _concave_frac(inner["R"], inner["Z"])
    ok(cb > 0.05, f"W7-X phi=0 boundary is a bean (concave {cb:.2f})")
    ok(ci < 0.5 * cb,
       f"innermost surface is rounder than boundary (concave {ci:.2f} < 0.5*{cb:.2f})")

    # surfaces still nest monotonically (no inversion) toward the axis
    exts = []
    for s in surfs:
        R = np.asarray(s["R"]); Z = np.asarray(s["Z"])
        exts.append(float(np.max(np.hypot(R - R.mean(), Z - Z.mean()))))
    ok(all(exts[i] < exts[i+1] for i in range(len(exts)-1)),
       f"nested extents increase monotonically: {[round(e,2) for e in exts]}")

    # rigorous, unified: surfaces must strictly nest (no crossing / overlap) for
    # every machine AND concept, at every toroidal cut.
    for name in ("W7-X", "HELIAS", "LHD", "HSX", "CFQS", "NAE-QA"):
        assert_strictly_nested(name)

    print("\nRESULT:", "NESTING PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
