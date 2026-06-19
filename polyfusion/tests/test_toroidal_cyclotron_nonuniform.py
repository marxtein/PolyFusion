"""Optional nonuniform-B correction for tokamak and stellarator Pcycl."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.base import get  # noqa: E402
from polyfusion.io import run_case  # noqa: E402


@pytest.mark.parametrize(
    ("config", "preset"),
    [("tokamak", "ITER"), ("stellarator", "HELIAS")],
)
def test_nonuniform_field_switch_defaults_off_and_preserves_baseline(config, preset):
    default = run_case({}, preset=preset, config=config)["outputs"]
    explicit = run_case(
        {"cyclotron_B_nonuniform": 0.0}, preset=preset, config=config
    )["outputs"]
    assert explicit["Pcycl"] == pytest.approx(default["Pcycl"], rel=1e-13)
    assert explicit["cyclotron_B25_factor"] == pytest.approx(1.0)


def test_tokamak_nonuniform_field_increases_iter_cyclotron_loss():
    uniform = run_case(
        {"cyclotron_B_nonuniform": 0.0}, preset="ITER", config="tokamak"
    )["outputs"]
    nonuniform = run_case(
        {"cyclotron_B_nonuniform": 1.0}, preset="ITER", config="tokamak"
    )["outputs"]
    assert 1.1 < nonuniform["cyclotron_B25_factor"] < 1.3
    assert nonuniform["Pcycl"] == pytest.approx(
        uniform["Pcycl"] * nonuniform["cyclotron_B25_factor"], rel=1e-12
    )


def test_stellarator_nonuniform_field_uses_near_axis_B_strength_variation():
    uniform = run_case(
        {"cyclotron_B_nonuniform": 0.0}, preset="HELIAS", config="stellarator"
    )["outputs"]
    nonuniform = run_case(
        {"cyclotron_B_nonuniform": 1.0}, preset="HELIAS", config="stellarator"
    )["outputs"]
    assert 1.0 < nonuniform["cyclotron_B25_factor"] < 1.02
    assert nonuniform["Pcycl"] == pytest.approx(
        uniform["Pcycl"] * nonuniform["cyclotron_B25_factor"], rel=1e-12
    )


def test_self_consistent_solves_preserve_nonuniform_field_switch():
    tok = run_case(
        {"fT": 0.0, "cyclotron_B_nonuniform": 1.0},
        preset="ITER",
        config="tokamak",
    )["outputs"]
    stell = run_case(
        {"fT": 0.0, "cyclotron_B_nonuniform": 1.0},
        preset="HELIAS",
        config="stellarator",
    )["outputs"]
    assert tok["cyclotron_B25_factor"] > 1.0
    assert stell["cyclotron_B25_factor"] > 1.0


def test_registry_and_frontend_expose_nonuniform_field_switch():
    for config in ("tokamak", "stellarator"):
        assert "cyclotron_B_nonuniform" in get(config).params
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    src = open(os.path.join(root, "app", "index.html"), encoding="utf-8").read()
    assert "cyclotron_B_nonuniform:" in src
    assert "'cyclotron_B_nonuniform'" in src
    assert "cyclotron_B25_factor" in src
