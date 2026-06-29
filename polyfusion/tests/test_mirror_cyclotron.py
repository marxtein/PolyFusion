"""Mirror-specific cyclotron radiation and manual tauC regression tests."""

from __future__ import annotations

import math
import os
import sys

import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.base import MIRROR_PRESETS, get  # noqa: E402
from polyfusion.configs.mirror import (  # noqa: E402
    _cyclotron_effective_temperature,
    _mirror_cyclotron_power,
    solve_mirror,
)
from polyfusion.constants import QE  # noqa: E402
from polyfusion.io import run_case  # noqa: E402


def _beam(**overrides):
    params = dict(MIRROR_PRESETS["BEAM"])
    params.update(overrides)
    return solve_mirror(**params)


def test_effective_temperature_matches_profile_limits():
    assert _cyclotron_effective_temperature(10.0, 0.0) == pytest.approx(10.0)
    assert _cyclotron_effective_temperature(10.0, 1.0) == pytest.approx(8.0)


def test_zero_throat_reduces_to_uniform_cylinder_formula():
    ne0 = 2.0e20
    Te0 = 10.0
    Sn = 0.5
    ST = 0.0
    Rw = 0.8
    a_c = 0.3
    L_c = 10.0
    B0 = 2.5
    expected = (
        4.14e-7
        * (ne0 / 1e20 / (1 + Sn)) ** 0.5
        * Te0**2.5
        * B0**2.5
        * (1 - Rw) ** 0.5
        * a_c**-0.5
        * (1 + 2.5 * Te0 / 511)
        * math.pi
        * a_c**2
        * L_c
    )
    actual = _mirror_cyclotron_power(
        ne0, Te0, Sn, ST, Rw, a_c, L_c, B0, R_mc=10.0, f_throat=0.0
    )
    assert actual == pytest.approx(expected, rel=1e-12)


def test_high_field_throats_increase_formula_power():
    no_throat = _beam(f_throat=0.0)
    with_throat = _beam(f_throat=0.1)
    assert with_throat.Pcycl > no_throat.Pcycl


def test_throat_uses_global_optical_radius_with_B25_volume_moment():
    ne0, Te0, Sn, ST = 2e20, 10.0, 0.5, 1.0
    Rw, a_c, L_c, B0, R_mc, f_throat = 0.8, 0.3, 10.0, 2.5, 12.0, 0.1
    u = np.linspace(0.0, 1.0, 20001)
    ratio = 1 + (R_mc - 1) * np.sin(math.pi * u / 2) ** 2
    a_z = a_c / np.sqrt(ratio)
    one_throat = np.trapezoid(
        (B0 * ratio) ** 2.5 * math.pi * a_z**2 * f_throat * L_c, u
    )
    field_moment = B0**2.5 * math.pi * a_c**2 * L_c + 2 * one_throat
    teff = _cyclotron_effective_temperature(Te0, ST)
    prefactor = (
        4.14e-7
        * (ne0 / 1e20 / (1 + Sn)) ** 0.5
        * teff**2.5
        * (1 - Rw) ** 0.5
        * (1 + 2.5 * teff / 511)
    )
    expected = prefactor * a_c**-0.5 * field_moment
    actual = _mirror_cyclotron_power(ne0, Te0, Sn, ST, Rw, a_c, L_c, B0, R_mc, f_throat)
    assert actual == pytest.approx(expected, rel=2e-7)


def test_manual_tauC_uses_electron_energy_and_scales_inverse_with_time():
    one = _beam(use_tauC=1.0, tauC=1.0)
    two = _beam(use_tauC=1.0, tauC=2.0)
    p = MIRROR_PRESETS["BEAM"]
    expected_eth_e = (
        1.5 * one.ne0 * p["Te0"] * 1e3 * QE / (1 + p["Sn"] + p["ST"]) * one.Vp * 1e-6
    )
    assert one.Pcycl == pytest.approx(expected_eth_e)
    assert one.Pcycl == pytest.approx(2 * two.Pcycl)
    assert one.tauC_eff == pytest.approx(1.0)
    assert two.tauC_eff == pytest.approx(2.0)


def test_manual_tauC_is_independent_of_wall_reflectivity():
    low = _beam(use_tauC=1.0, tauC=0.5, Rw=0.1)
    high = _beam(use_tauC=1.0, tauC=0.5, Rw=0.99)
    assert low.Pcycl == pytest.approx(high.Pcycl)


def test_formula_mode_responds_to_reflectivity_field_and_throat_length():
    base = _beam()
    reflective = _beam(Rw=0.95)
    stronger = _beam(B_vac=4.0)
    higher_ratio = _beam(R_mirror=15.0)
    longer_throat = _beam(f_throat=0.2)
    assert reflective.Pcycl < base.Pcycl
    assert stronger.Pcycl > base.Pcycl
    assert higher_ratio.Pcycl > base.Pcycl
    assert longer_throat.Pcycl > base.Pcycl
    assert base.tauC_eff > 0


def test_tauC_must_be_positive_only_in_manual_mode():
    assert _beam(use_tauC=0.0, tauC=0.0).Pcycl >= 0
    with pytest.raises(ValueError, match="tauC must be > 0"):
        _beam(use_tauC=1.0, tauC=0.0)
    result = run_case({"use_tauC": 1.0, "tauC": 0.0}, preset="BEAM", config="mirror")
    assert any("tauC must be > 0" in message for message in result["errors"])
    missing = get("mirror").validate(
        {k: v for k, v in MIRROR_PRESETS["BEAM"].items() if k != "tauC"}
        | {"use_tauC": 1.0}
    )
    assert any("tauC is required" in message for message in missing)


def test_self_consistent_temperature_preserves_selected_tauC_mode():
    manual = _beam(use_tauE=0.0, Te0=0.0, use_tauC=1.0, tauC=3.0)
    formula = _beam(use_tauE=0.0, Te0=0.0, use_tauC=0.0, tauC=3.0)
    assert manual.tauC_eff == pytest.approx(3.0)
    assert formula.tauC_eff != pytest.approx(3.0)
    assert manual.Pcycl != pytest.approx(formula.Pcycl)


def test_registry_exposes_tauC_inputs():
    params = set(get("mirror").params)
    assert {"use_tauC", "tauC"} <= params


def test_frontend_exposes_tauC_mode_and_locking_contract():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    src = open(os.path.join(root, "app", "index.html"), encoding="utf-8").read()
    assert "use_tauC:" in src
    assert "tauC:" in src
    assert "'use_tauC'" in src
    assert "migrateTauC" in src
    assert "VALS.use_tauC===1" in src
    assert "lock('tauC',!manualTauC)" in src
    assert "lock('Rw',manualTauC)" in src
    assert "tauC_eff:'τ<sub>C,eff</sub>'" in src
