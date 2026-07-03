"""Static regressions for FRC/dipole physics notes and profile rendering."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_frc_profile_uses_backend_rigid_rotor_parameter_not_gaussian_proxy():
    src = open(INDEX, encoding="utf-8").read()
    assert "LASTRUN.outputs.K_rr" in src
    assert "1/Math.pow(Math.cosh(K*(2*rho*rho-1)),2)" in src
    assert "TT.push(1)" in src
    assert "Math.exp(-Math.pow((rho-x0)/w,2))" not in src


def test_frontend_states_frc_fit_and_dipole_coordinate_and_wall_limits():
    src = open(INDEX, encoding="utf-8").read()
    assert "BORAY 风格 Z-R 轴对称半平面" in src
    assert "separatrix ψ=0 and closed flux surfaces are drawn for R≥0 only" in src
    assert "ρ<sub>U</sub>=ln(U/U<sub>in</sub>)/ln(U<sub>out</sub>/U<sub>in</sub>)" in src
    assert "球形面积代理" in src
    assert "spherical-area proxy" in src


def test_dipole_frontend_consumes_backend_geometry_instead_of_always_drawing_point_dipole():
    src = open(INDEX, encoding="utf-8").read()
    assert "LASTRUN.shape.type==='dipole'" in src
    assert "sh.surfaces.forEach" in src


def test_dipole_field_input_is_labeled_as_dipole_equivalent_scale():
    src = open(INDEX, encoding="utf-8").read()
    assert "点偶极等效场标度" in src
    assert "dipole-equivalent field scale" in src
    assert "环表面场" not in src
