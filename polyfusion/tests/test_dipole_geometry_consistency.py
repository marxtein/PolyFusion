"""Dipole backend/frontend geometry consistency regressions."""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion import ringfield  # noqa: E402
from polyfusion.configs.base import DIPOLE_PRESETS  # noqa: E402
from polyfusion.configs.dipole import dipole_shape_outlines, solve_dipole  # noqa: E402


def _params(**overrides):
    params = dict(DIPOLE_PRESETS["Dipole-DD"])
    params.update(overrides)
    return params


def test_finite_ring_u_ratio_uses_actual_flux_tube_volume():
    params = _params(ring_model=1)
    result = solve_dipole(**params)
    lam_in = params["L_in_fac"]
    lam_out = params["R_p"] / params["r_ring"]
    expected = float(ringfield.u_spec(lam_out) / ringfield.u_spec(lam_in))
    point_value = (lam_out / lam_in) ** 4

    assert result.U_ratio == pytest.approx(expected, rel=1e-12)
    assert abs(result.U_ratio / point_value - 1.0) > 0.02


@pytest.mark.parametrize("ring_model", [0, 1])
def test_shape_payload_has_closed_flux_surfaces_and_unified_profile_coordinate(ring_model):
    params = _params(ring_model=ring_model)
    shape = dipole_shape_outlines(**params)

    assert shape["type"] == "dipole"
    assert shape["mode"] == ("finite_ring" if ring_model else "point_dipole")
    assert shape["wall_model"] == "spherical_area_proxy"
    assert len(shape["surfaces"]) >= 5
    for surface in shape["surfaces"]:
        r = np.asarray(surface["r"])
        z = np.asarray(surface["z"])
        assert r[0] == pytest.approx(r[-1], abs=1e-9)
        assert z[0] == pytest.approx(z[-1], abs=1e-9)
        assert np.all(r >= -1e-10)

    profile = shape["profile"]
    rho = np.asarray(profile["rho_U"])
    n = np.asarray(profile["n"])
    temp = np.asarray(profile["T"])
    assert rho[0] == pytest.approx(0.0)
    assert rho[-1] == pytest.approx(1.0)
    assert np.all(np.diff(rho) > 0)
    assert n[0] == pytest.approx(1.0)
    assert temp[0] == pytest.approx(1.0)
    assert np.all(np.diff(n) < 0)
    assert np.all(np.diff(temp) < 0)
    assert profile["U_ratio"] > 1.0


def test_finite_ring_flux_surfaces_are_not_point_dipole_curves():
    point = dipole_shape_outlines(**_params(ring_model=0))
    loop = dipole_shape_outlines(**_params(ring_model=1))
    point_mid = point["surfaces"][2]
    loop_mid = loop["surfaces"][2]

    point_height = max(point_mid["z"])
    loop_height = max(loop_mid["z"])
    assert not math.isclose(point_height, loop_height, rel_tol=0.02)
