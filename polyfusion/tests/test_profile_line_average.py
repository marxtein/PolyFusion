import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs import solve_stellarator  # noqa: E402
from polyfusion.configs.stellarator import _stellarator_geometry  # noqa: E402
from polyfusion.tokamak import (  # noqa: E402
    _line_average_factor,
    _line_average_factor_from_vfrac,
    funsc,
)


def test_area_equivalent_line_average_matches_analytic_circle():
    rho = np.linspace(0.0, 1.0, 401)
    vfrac = rho**2
    for exponent in (0.0, 0.5, 1.0, 2.0):
        numeric = _line_average_factor_from_vfrac(exponent, rho, vfrac)
        analytic = _line_average_factor(exponent)
        assert numeric == pytest.approx(analytic, rel=2e-5, abs=1e-12)
    assert _line_average_factor_from_vfrac(0.0, rho, vfrac) == pytest.approx(1.0)


def test_tokamak_geometry_line_average_diagnostics_match_existing_nbar():
    result = funsc(
        18.0, 10.0, 1.0, 0.0, 0.5, 1.0, 2e20, 15.0, 1.0, 1.0, 0.5,
        5.0, 10.0, 1.0, 0.04, 0.01, 10, 0.7, 0.1, 1,
    )
    expected_te_line = result.Te0 * _line_average_factor(1.0)
    expected_ti_line = 15.0 * _line_average_factor(1.0)
    nGw = 1e20 * 10.0 / (math.pi * (18.0 / 10.0) ** 2)
    existing_nbar = result.nbar_o_nGw * nGw

    assert result.nbar_geom == pytest.approx(existing_nbar, rel=1e-10)
    assert result.Te_line_geom == pytest.approx(expected_te_line, rel=1e-10)
    assert result.Ti_line_geom == pytest.approx(expected_ti_line, rel=1e-10)


def test_stellarator_geometry_line_average_diagnostics_are_reported():
    base = dict(
        R0=18.0, a=1.8, N_fp=5, delta_h=0.0, etabar=0.05,
        Sn=0.5, ST=1.0, ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0,
        f1=0.5, B0=5.0, tauE=1.0, fHe=0.04, fimp=0.01,
        Zimp=10, Rw=0.7, g=0.1, icase=1, iota=1.0,
    )
    circular = solve_stellarator(**base)
    assert circular.nbar_geom == pytest.approx(circular.nbar, rel=5e-3)
    assert circular.Te_line_geom == pytest.approx(
        circular.Te0 * _line_average_factor(base["ST"]), rel=5e-3
    )
    assert circular.Ti_line_geom == pytest.approx(
        base["Ti0"] * _line_average_factor(base["ST"]), rel=5e-3
    )

    shaped = solve_stellarator(**{**base, "delta_h": 0.9, "iota": None})
    for value in (shaped.nbar_geom, shaped.Te_line_geom, shaped.Ti_line_geom):
        assert math.isfinite(value)
        assert value > 0.0
    assert shaped.nbar_geom < shaped.ne0
    assert shaped.Te_line_geom < shaped.Te0
    assert shaped.Ti_line_geom < base["Ti0"]


def test_stellarator_posteriors_report_traceable_intermediate_values():
    cfg = dict(
        R0=5.5, a=0.55, N_fp=5, delta_h=0.25, etabar=0.119,
        Sn=0.5, ST=1.0, ni0=1.6e20, Ti0=12.0, fT=0.9, fsig=1.0,
        f1=0.5, B0=2.5, tauE=0.25, fHe=0.04, fimp=0.01,
        Zimp=10, Rw=0.7, g=0.05, icase=1, iota=0.88,
        Vp_override=30.0, Sw_override=128.0,
    )
    result = solve_stellarator(**cfg)

    assert result.aspect_geom == pytest.approx(cfg["R0"] / cfg["a"])
    assert result.aspect_vol == pytest.approx(cfg["R0"] / result.a_vol)
    assert result.fnavg == pytest.approx(1.0 / (1.0 + cfg["Sn"]))
    assert result.fTavg == pytest.approx(1.0 / (1.0 + cfg["ST"]))
    assert result.fpavg == pytest.approx(1.0 / (1.0 + cfg["Sn"] + cfg["ST"]))
    assert result.beta_soft_limit == pytest.approx(0.05)
    assert result.beta_o_limit == pytest.approx(result.betaT / result.beta_soft_limit)
    assert result.nbar_o_Sudo == pytest.approx(result.nbar / result.n_Sudo)
    assert result.PL_ISS04 == pytest.approx(result.Pheat + 0.2 * result.Pfus)
    assert result.geom_volume_ratio == pytest.approx(result.Vp / result.Vp_geom)
    assert result.geom_wall_ratio == pytest.approx(result.Sw / result.Sw_geom)
    assert result.nbar_geom_o_nbar == pytest.approx(result.nbar_geom / result.nbar)
    for value in (
        result.n_Sudo,
        result.aspect_geom,
        result.aspect_vol,
        result.geom_volume_ratio,
        result.geom_wall_ratio,
    ):
        assert math.isfinite(value)
        assert value > 0.0


def test_stellarator_geometry_caches_monotone_profile_volume_fraction():
    geom = _stellarator_geometry(18.0, 1.8, 5, 0.9, 0.05, 0.1, None, None, None)
    rho = np.asarray(geom["profile_rho"], dtype=float)
    vfrac = np.asarray(geom["profile_vfrac"], dtype=float)

    assert rho[0] == pytest.approx(0.0)
    assert rho[-1] == pytest.approx(1.0)
    assert vfrac[0] == pytest.approx(0.0)
    assert vfrac[-1] == pytest.approx(1.0)
    assert np.all(np.diff(vfrac) >= -1e-12)
