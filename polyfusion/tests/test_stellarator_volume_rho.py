import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import (  # noqa: E402
    _stellarator_geometry,
    section_outlines,
)


BASE = dict(
    R0=18.0, a=1.8, N_fp=5, delta_h=0.9, etabar=0.05,
    Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0,
    f1=0.5, B0=5.0, tauE=1.0, fHe=0.04, fimp=0.01,
    Zimp=10, Rw=0.7, g=0.1, icase=1,
)


def test_stellarator_profile_rho_is_volume_radius():
    geom = _stellarator_geometry(
        BASE["R0"], BASE["a"], BASE["N_fp"], BASE["delta_h"],
        BASE["etabar"], BASE["g"], None, None, None,
    )
    rho = np.asarray(geom["profile_rho"], dtype=float)
    vfrac = np.asarray(geom["profile_vfrac"], dtype=float)
    scale = np.asarray(geom["profile_surface_scale"], dtype=float)

    assert rho == pytest.approx(np.sqrt(vfrac), abs=1e-12)
    assert rho[0] == pytest.approx(0.0)
    assert rho[-1] == pytest.approx(1.0)
    assert np.all(np.diff(rho) >= 0.0)
    assert np.all(np.diff(scale) > 0.0)


def test_stellarator_shape_surfaces_label_volume_rho():
    geom = _stellarator_geometry(
        BASE["R0"], BASE["a"], BASE["N_fp"], BASE["delta_h"],
        BASE["etabar"], BASE["g"], None, None, None,
    )
    shape = section_outlines(**BASE)
    scale_grid = np.asarray(geom["profile_surface_scale"], dtype=float)
    rho_grid = np.asarray(geom["profile_rho"], dtype=float)

    for surface in shape["sections"][0]["surfaces"]:
        expected = np.interp(surface["surface_scale"], scale_grid, rho_grid)
        assert surface["rho"] == pytest.approx(expected, abs=1e-12)
    assert shape["rho_definition"] == "sqrt(V_enclosed/V_plasma)"


def test_iota_keeps_axis_value_semantics():
    concept = solve_stellarator(**BASE)
    assert concept.iota == pytest.approx(concept.iota_geom)
    for removed in ("iota_rho", "iota_rho_2_3", "iota_axis",
                    "iota_profile_model"):
        assert not hasattr(concept, removed)

    circle = {
        "kind": "fourier", "nfp": 5,
        "R": [[0, 0, 0.0], [1, 0, 1.0]],
        "Z": [[-1, 0, 1.0]],
    }
    machine = solve_stellarator(
        **{**BASE, "delta_h": 0.0, "shape": circle, "iota": 0.4}
    )
    assert machine.iota == pytest.approx(0.4)


def test_stellarator_profile_ui_uses_volume_rho_label():
    html = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                     "app", "index.html"),
        encoding="utf-8",
    ).read()
    assert "(CUR==='stellarator'||CUR==='tokamak')?L('体积半径 ρ=√(V/Vp)'" in html
    assert "边界旋转变换 (>0=使用当前边界携带值；0=由边界自身参数自洽计算)" in html
    assert "ρ=2/3 旋转变换" not in html
