"""Tokamak volume-radius from nested-flux-surface layer integration.

Mirrors the stellarator's `_profile_volume_fraction`: build nested Miller
surfaces at internal scale s in [0,1], integrate each surface's volume, and map
the internal scale to the volume radius rho = sqrt(V_enclosed / V_plasma).
This is the coordinate infrastructure for importing real (flux-surface-based)
profiles later.

Key invariants:
  * vfrac is monotone, vfrac[0]=0, vfrac[-1]=1, rho=sqrt(vfrac).
  * circular (kappa=1, delta=0, shaf=0) degenerates to vfrac=s^2 (self-similar).
  * a shaped plasma (kappa>1) gives vfrac != s^2 (real shape enters the mapping).
  * the power account and the nbar_geom diagnostic are NUMERICALLY unchanged
    (profiles stay defined in the volume radius; the area-equivalent line
    average still degenerates to the analytic Gamma factor).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.tokageom import (  # noqa: E402
    tokamak_profile_volume_fraction,
    tokamak_geometry,
)
from polyfusion.tokamak import funsc, _line_average_factor  # noqa: E402


def test_layer_integration_circular_is_self_similar():
    s, rho, vfrac = tokamak_profile_volume_fraction(6.2, 2.0, 1.0, 0.0, 0.0, 1)
    assert s[0] == pytest.approx(0.0)
    assert s[-1] == pytest.approx(1.0)
    assert vfrac[0] == pytest.approx(0.0)
    assert vfrac[-1] == pytest.approx(1.0)
    # circular torus: V(s) = 2 pi^2 R0 (a s)^2 -> vfrac = s^2 exactly
    np.testing.assert_allclose(vfrac, s**2, atol=2e-3)
    np.testing.assert_allclose(rho, np.sqrt(np.clip(vfrac, 0, 1)), rtol=1e-12)


def test_layer_integration_shaped_departs_from_self_similar_and_is_monotone():
    s, rho, vfrac = tokamak_profile_volume_fraction(6.2, 2.0, 1.8, 0.5, 0.3, 1)
    assert vfrac[0] == pytest.approx(0.0)
    assert vfrac[-1] == pytest.approx(1.0)
    assert np.all(np.diff(vfrac) >= -1e-12)               # monotone
    np.testing.assert_allclose(rho, np.sqrt(np.clip(vfrac, 0, 1)), rtol=1e-12)
    # elongation tapers inward, so V(s) is NOT proportional to s^2: the mapping
    # must differ from the self-similar one somewhere in the interior.
    assert np.max(np.abs(vfrac - s**2)) > 1e-3


def test_geometry_dict_exposes_profile_arrays():
    geom = tokamak_geometry(1, 6.2, 3.1, 1.8, 0.5, 0.0, None, 0.0, 0.0)
    for key in ("profile_surface_scale", "profile_rho", "profile_vfrac"):
        assert key in geom
    rho = np.asarray(geom["profile_rho"])
    vfrac = np.asarray(geom["profile_vfrac"])
    np.testing.assert_allclose(rho, np.sqrt(np.clip(vfrac, 0, 1)), rtol=1e-12)


def test_nbar_geom_unchanged_by_layer_integration():
    # power account + line-average diagnostics must be numerically identical to
    # the analytic Gamma factor in BOTH circular and shaped cases (the change is
    # infrastructure-only; it must not move any reported number).
    for kappa, delta in ((1.0, 0.0), (1.8, 0.5)):
        res = funsc(6.2, 2.0, kappa, delta, 0.5, 1.0, 1e20, 15.0, 1.0, 1.0, 0.5,
                    5.3, 15.0, 1.0, 0.04, 0.01, 10, 0.7, 0.1, 1)
        assert res.nbar_geom == pytest.approx(res.ne0 * _line_average_factor(0.5), rel=1e-9)
        assert res.Te_line_geom == pytest.approx(res.Te0 * _line_average_factor(1.0), rel=1e-9)
        assert res.Ti_line_geom == pytest.approx(15.0 * _line_average_factor(1.0), rel=1e-9)
