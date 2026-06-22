"""Engineering edge safety factor q_95.

The legacy ``q`` output is the cylindrical safety factor
``q = 5 a^2 B0 kappa / (R0 Ip)`` (kept verbatim for JS-reference / golden parity).
``q95`` is the standard shaped engineering edge value (ITER Physics Basis):

    q95 = (5 a^2 B0 / (R0 Ip)) * [1 + kappa^2 (1 + 2 delta^2 - 1.2 delta^3)]/2
          * (1.17 - 0.65 eps) / (1 - eps^2)^2,   eps = a/R0.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.tokamak import funsc  # noqa: E402


def _iter():
    # ITER-like point (matches the ITER preset scalars)
    return funsc(6.2, 3.1, 1.86, 0.5, 0.5, 1.0, 1.0e20, 15.0, 1.0, 1.0, 0.5,
                 5.3, 15.0, 1.0, 0.04, 0.01, 10, 0.7, 0.1, 1)


def test_q95_present_and_in_engineering_range_for_iter():
    res = _iter()
    assert hasattr(res, "q95")
    assert math.isfinite(res.q95)
    assert 2.0 < res.q95 < 6.0          # ITER-class q95 is ~3


def test_q95_matches_iter_ipb_formula():
    R0, A, kappa, delta, BT0, Ip = 6.2, 3.1, 1.86, 0.5, 5.3, 15.0
    a = R0 / A
    eps = a / R0
    shape = (1.0 + kappa**2 * (1.0 + 2.0 * delta**2 - 1.2 * delta**3)) / 2.0
    expected = (5.0 * a**2 * BT0 / (R0 * Ip)) * shape * (1.17 - 0.65 * eps) / (1.0 - eps**2)**2
    res = _iter()
    assert res.q95 == pytest.approx(expected, rel=1e-9)


def test_legacy_cylindrical_q_unchanged():
    # the cylindrical q must stay exactly the JS-parity formula
    R0, A, kappa, BT0, Ip = 6.2, 3.1, 1.86, 5.3, 15.0
    a = R0 / A
    res = _iter()
    assert res.q == pytest.approx(5.0 * BT0 * a**2 * kappa / (R0 * Ip), rel=1e-12)
    assert res.q95 > res.q              # shaped edge value exceeds the bare cylindrical q
