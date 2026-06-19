"""Cross-configuration fast cyclotron models and manual tauC modes."""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.base import DIPOLE_PRESETS, FRC_PRESETS, get  # noqa: E402
from polyfusion.configs.dipole import solve_dipole  # noqa: E402
from polyfusion.configs.frc import solve_frc  # noqa: E402
from polyfusion.constants import QE  # noqa: E402
from polyfusion.io import run_case  # noqa: E402


def _frc(**overrides):
    params = dict(FRC_PRESETS["FRC-DT"])
    params.update(overrides)
    return solve_frc(**params)


def _dipole(**overrides):
    params = dict(DIPOLE_PRESETS["Dipole-DHe3"])
    params.update(overrides)
    return solve_dipole(**params)


def test_frc_uses_B_25_volume_moment_not_mean_field_power():
    result = _frc()
    assert 0 < result.GB < 1
    assert result.GB25 > result.GB**2.5
    old = (
        4.14e-7
        * (result.ne0 * result.G1 / 1e20) ** 0.5
        * FRC_PRESETS["FRC-DT"]["Te"] ** 2.5
        * (FRC_PRESETS["FRC-DT"]["B_e"] * result.GB) ** 2.5
        * (1 - FRC_PRESETS["FRC-DT"]["Rw"]) ** 0.5
        * FRC_PRESETS["FRC-DT"]["r_s"] ** -0.5
        * (1 + 2.5 * FRC_PRESETS["FRC-DT"]["Te"] / 511)
        * result.Vp
    )
    assert result.Pcycl > old
    assert result.Pcycl / old == pytest.approx(
        result.GB25 / result.GB**2.5, rel=1e-10
    )


def test_frc_manual_tauC_uses_electron_energy():
    result = _frc(use_tauC=1.0, tauC=2.0)
    p = FRC_PRESETS["FRC-DT"]
    eth_e = (
        1.5 * result.ne0 * p["Te"] * 1e3 * QE * result.G1 * result.Vp * 1e-6
    )
    assert result.Pcycl == pytest.approx(eth_e / 2.0)
    assert result.tauC_eff == pytest.approx(2.0)
    assert _frc(use_tauC=1.0, tauC=2.0, Rw=0.1).Pcycl == pytest.approx(
        _frc(use_tauC=1.0, tauC=2.0, Rw=0.99).Pcycl
    )


def test_dipole_presets_default_to_finite_ring_proxy():
    assert all(p["ring_model"] == 1 for p in DIPOLE_PRESETS.values())
    result = _dipole()
    assert result.ring_model == 1.0
    assert result.cyclotron_model == "equatorial_shell_proxy"


def test_dipole_manual_tauC_uses_shell_integrated_electron_energy():
    result = _dipole(use_tauC=1.0, tauC=4.0)
    assert result.Pcycl == pytest.approx(result.Eth_e / 4.0)
    assert result.tauC_eff == pytest.approx(4.0)
    low = _dipole(use_tauC=1.0, tauC=4.0, Rw=0.1)
    high = _dipole(use_tauC=1.0, tauC=4.0, Rw=0.99)
    assert low.Pcycl == pytest.approx(high.Pcycl)


@pytest.mark.parametrize(
    ("config", "preset"),
    [("frc", "FRC-DT"), ("dipole", "Dipole-DHe3")],
)
def test_manual_tauC_requires_explicit_positive_value(config, preset):
    missing = run_case({"use_tauC": 1.0}, preset=None, config=config)
    assert "errors" in missing
    preset_missing = dict(get(config).presets[preset])
    preset_missing.pop("tauC")
    errors = get(config).validate(preset_missing | {"use_tauC": 1.0})
    assert any("tauC is required" in message for message in errors)


def test_registry_exposes_tauC_for_all_three_non_toroidal_models():
    for config in ("mirror", "frc", "dipole"):
        assert {"use_tauC", "tauC"} <= set(get(config).params)
