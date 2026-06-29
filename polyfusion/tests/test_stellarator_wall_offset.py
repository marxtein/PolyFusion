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
    R = np.asarray(R)
    Z = np.asarray(Z)
    n = len(R)
    inside = False
    j = n - 1
    for i in range(n):
        if ((Z[i] > py) != (Z[j] > py)) and (
            px < (R[j] - R[i]) * (py - Z[i]) / (Z[j] - Z[i] + 1e-30) + R[i]
        ):
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
        R = np.asarray(R)
        Z = np.asarray(Z)
        return abs(float(np.sum(R * np.roll(Z, -1) - np.roll(R, -1) * Z)))

    assert area2(wR, wZ) > area2(R, Z)


def test_imported_equilibrium_flux_surfaces_inside_boundary():
    """Imported VMEC (W7-X) flux surfaces must nest INSIDE the plasma boundary.

    Bug: the synthesized nested surfaces used a per-harmonic fade that let the
    bean cross-section's inner surfaces poke outside the boundary on the concave
    side ("磁面与边界交叠").  The wall-containment test missed it because the wall
    has a gap that hid the overshoot.  Fix: morph from the magnetic axis +
    per-vertex clamp to the first boundary crossing.
    """
    import os

    nc = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "app",
        "equilibria",
        "stellarator",
        "W7-X.nc",
    )
    if not os.path.isfile(nc):
        return  # bundled file absent (skip)
    from polyfusion import equilibrium_import as EI
    from polyfusion.configs.stellarator import _machine_boundary_outlines

    imp = EI._read_vmec(nc)
    m = imp["metrics"]
    out = _machine_boundary_outlines(
        m["R0_m"], m["boundary_scale_m"], imp["nfp"], 0.0, 0.05, imp["shape"], 200
    )
    for s in out["sections"]:
        bR, bZ = s["R"], s["Z"]
        for su in s["surfaces"]:
            if su["rho"] >= 0.999:
                continue  # rho=1 coincides with the boundary
            outside = sum(not _inside(x, y, bR, bZ) for x, y in zip(su["R"], su["Z"]))
            assert outside == 0, (
                f"{s['label']} rho={su['rho']:.2f}: {outside} surface points "
                f"outside boundary"
            )


def test_imported_equilibrium_uses_real_nested_interior_surfaces():
    """When a VMEC equilibrium is imported the shape view must draw the wout's
    OWN interior flux surfaces (nested by construction), not the synthesized
    cartoon fade.  Non-imported presets keep the fade (no interior_surfaces)."""
    import os

    nc = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "app",
        "equilibria",
        "stellarator",
        "W7-X.nc",
    )
    if not os.path.isfile(nc):
        return
    from polyfusion import equilibrium_import as EI
    from polyfusion.configs.stellarator import _machine_boundary_outlines

    imp = EI._read_vmec(nc)
    interior = imp["shape"].get("interior_surfaces")
    assert interior and len(interior) >= 3, "import must carry real interior surfaces"
    assert interior[-1]["rho"] == 1.0

    out = _machine_boundary_outlines(
        imp["metrics"]["R0_m"],
        imp["metrics"]["boundary_scale_m"],
        imp["nfp"],
        0.0,
        0.05,
        imp["shape"],
        200,
    )
    for s in out["sections"]:
        sfc = s["surfaces"]
        # each surface strictly inside the next one out (real nesting)
        for k in range(len(sfc) - 1):
            inner, outer = sfc[k], sfc[k + 1]
            bad = sum(
                not _inside(x, y, outer["R"], outer["Z"])
                for x, y in zip(inner["R"], inner["Z"])
            )
            assert bad == 0, f"{s['label']} surface {k} not nested inside {k + 1}"


if __name__ == "__main__":
    test_concave_section_wall_never_inside_plasma()
    test_convex_section_wall_outside_and_enlarged()
    test_imported_equilibrium_flux_surfaces_inside_boundary()
    test_imported_equilibrium_uses_real_nested_interior_surfaces()
    print("PASS")
