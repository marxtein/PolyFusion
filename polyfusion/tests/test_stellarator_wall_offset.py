"""Wall offset must stay OUTSIDE the plasma, even for non-star-shaped sections.

Bug: ``_offset_closed_curve_normal`` oriented its normals with a per-vertex
centroid test (``n . (P - centroid) < 0`` -> flip).  That is only valid for
star-shaped (convex-ish) cross-sections.  Imported VMEC equilibria (e.g. W7-X)
have bean / crescent cuts that are NOT star-shaped about their centroid; at the
concave notch the test flipped the (already correct) outward normal INWARD, so
the wall dipped inside the plasma ("壁跑到等离子体里面").

Fix: orient the normals from the polygon winding (shoelace signed area), which
is globally consistent for any simple closed curve.

Run: python -m pytest polyfusion/tests/test_stellarator_wall_offset.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.stellarator import _offset_closed_curve_normal  # noqa: E402


def _inside(px, py, R, Z):
    R = np.asarray(R); Z = np.asarray(Z); n = len(R); inside = False; j = n - 1
    for i in range(n):
        if ((Z[i] > py) != (Z[j] > py)) and (
                px < (R[j] - R[i]) * (py - Z[i]) / (Z[j] - Z[i] + 1e-30) + R[i]):
            inside = not inside
        j = i
    return inside


def _dart(reverse=False):
    """A simple closed polygon with a reflex (concave) vertex at (2, 1.2)."""
    verts = [(0, 0), (4, 0), (4, 4), (2, 1.2), (0, 4)]
    if reverse:
        verts = verts[::-1]
    verts.append(verts[0])
    R = np.array([v[0] for v in verts], float)
    Z = np.array([v[1] for v in verts], float)
    return R, Z


def test_concave_section_wall_never_inside_plasma():
    # both windings: orientation handling must work CW and CCW
    for reverse in (False, True):
        R, Z = _dart(reverse)
        wR, wZ = _offset_closed_curve_normal(R, Z, 0.25)
        inside = sum(_inside(x, y, R, Z) for x, y in zip(wR, wZ))
        assert inside == 0, f"reverse={reverse}: {inside} wall vertices inside plasma"


def test_convex_section_wall_outside_and_enlarged():
    # regression: a convex ellipse must still offset strictly outward
    t = np.linspace(0, 2 * np.pi, 160, endpoint=False)
    R = np.append(6 + 1.2 * np.cos(t), 6 + 1.2)
    Z = np.append(0.8 * np.sin(t), 0.0)
    wR, wZ = _offset_closed_curve_normal(R, Z, 0.1)
    assert sum(_inside(x, y, R, Z) for x, y in zip(wR, wZ)) == 0
    # wall area strictly larger than plasma area (shoelace magnitude)
    def area2(R, Z):
        R = np.asarray(R); Z = np.asarray(Z)
        return abs(float(np.sum(R * np.roll(Z, -1) - np.roll(R, -1) * Z)))
    assert area2(wR, wZ) > area2(R, Z)


if __name__ == "__main__":
    test_concave_section_wall_never_inside_plasma()
    test_convex_section_wall_outside_and_enlarged()
    print("PASS")
