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
