import math
import numpy as np
import pytest
from polyfusion import tokageom as tg


def test_revolution_metrics_circular_torus():
    # a circle of minor radius a at major radius R0 -> known torus
    R0, a = 6.0, 1.5
    th = np.linspace(0.0, 2 * np.pi, 2000, endpoint=False)
    R = R0 + a * np.cos(th)
    Z = a * np.sin(th)
    Vp, Sp = tg.revolution_metrics(R, Z)
    assert Vp == pytest.approx(2 * math.pi**2 * R0 * a**2, rel=1e-3)   # 2 pi^2 R a^2
    assert Sp == pytest.approx(4 * math.pi**2 * R0 * a, rel=1e-3)      # 4 pi^2 R a


def test_miller_boundary_volume_matches_known_torus():
    # ITER-like: R0=6.2, a=2.0 (A=3.1), kappa=1.7, delta=0.33
    R, Z = tg.miller_boundary(R0=6.2, a=2.0, kappa=1.7, delta=0.33, n_theta=720)
    Vp, Sp = tg.revolution_metrics(R, Z)
    # circular-limit cross-check: extent and elongation sane
    assert R.max() == pytest.approx(8.2, rel=1e-6)        # R0 + a
    assert R.min() == pytest.approx(4.2, rel=1e-6)        # R0 - a
    assert Z.max() == pytest.approx(1.7 * 2.0, rel=1e-6)  # kappa * a
    assert 700.0 < Vp < 820.0                              # validated CF/Miller ~786 m^3
