"""Mirror geometry module regression tests.

Run: python polyfusion/tests/test_mirror_geometry.py
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.geometry import get_geometry  # noqa: E402
from polyfusion.configs.mirror import solve_mirror  # noqa: E402
from polyfusion.configs.base import MIRROR_PRESETS  # noqa: E402


def test_sin2_volume_matches_original():
    """sin2_simple volume matches the analytic formula from mirror.py."""
    geom_cls = get_geometry("sin2_simple")
    geom = geom_cls(
        a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, beta=0.336, f_throat=0.1
    )
    R_mc = 10.0 / math.sqrt(1 - 0.336)
    V_cyl = math.pi * 0.09 * 10.0
    V_end = 2 * math.pi * 0.09 * 1.0 / math.sqrt(R_mc)
    expected = V_cyl + V_end
    assert abs(geom.volume() - expected) / expected < 1e-12


def test_sin2_registered():
    assert get_geometry("sin2_simple").__name__ == "Sin2SimpleGeometry"


def test_multi_zone_registered():
    assert get_geometry("multi_zone").__name__ == "MultiZoneGeometry"


def test_solve_mirror_default_geometry():
    """Default solve_mirror uses sin2_simple."""
    res = solve_mirror(**MIRROR_PRESETS["BEAM"])
    assert abs(res.Vp - 2.9889) < 0.01


def test_solve_mirror_multi_zone():
    """solve_mirror with multi_zone runs and includes expander volume."""
    kwargs = {k: v for k, v in MIRROR_PRESETS["BEAM"].items() if k != "geometry"}
    res = solve_mirror(geometry="multi_zone", **kwargs)
    assert res.Vp > 2.99


def test_multi_zone_wall_larger():
    """multi_zone wall surface includes throat, so > sin2_simple."""
    from polyfusion.geometry.sin2_simple import Sin2SimpleGeometry
    from polyfusion.geometry.multi_zone import MultiZoneGeometry

    g1 = Sin2SimpleGeometry(
        a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, beta=0.336, f_throat=0.1
    )
    g2 = MultiZoneGeometry(
        a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, beta=0.336, L_th=1.0
    )
    assert g2.wall_surface() > g1.wall_surface()


def test_multi_zone_f_axial():
    """f_axial is stored on geometry instance."""
    from polyfusion.geometry.multi_zone import MultiZoneGeometry

    g = MultiZoneGeometry(
        a_c=0.3, L_c=10.0, B_vac=3.0, R_mirror=10.0, beta=0.336, f_axial=0.65
    )
    assert abs(g.f_axial - 0.65) < 1e-12


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                print(f"FAIL {name}: {e}")
