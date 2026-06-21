"""Real-equilibrium cyclotron field factor from a G-EQDSK |B|(R,Z).

For a real imported equilibrium the non-uniform-field cyclotron correction
should be computed from the actual field modulus

    c_B25 = < (|B|/B0_axis)^2.5 >_V ,   |B| = sqrt(B_T^2 + B_p^2),
    B_T = F(psi)/R,   B_p = |grad psi|/R,   B0_axis = F(psi_axis)/Rmaxis,

integrated over the real plasma cross-section (psi inside the boundary), rather
than the analytic Miller 1/R proxy.  funsc must use this real factor when a real
equilibrium (geom_model=2 with eq) is supplied and cyclotron_B_nonuniform=1.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion import eqdsk  # noqa: E402
from polyfusion.tokamak import funsc  # noqa: E402
from polyfusion.cyclotron import tokamak_B25_factor  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "data", "test_1.geqdsk")


def _g():
    return eqdsk.parse_geqdsk(open(FIXTURE).read())


def test_parser_retains_fpol():
    g = _g()
    assert "fpol" in g
    fpol = np.asarray(g["fpol"])
    assert fpol.shape == (g["nw"],)
    assert np.all(np.isfinite(fpol))
    assert np.any(fpol != 0.0)


def test_real_b25_is_finite_positive_and_sane():
    g = _g()
    c = eqdsk.cyclotron_b25_from_eqdsk(g)
    assert math.isfinite(c)
    assert 0.3 < c < 5.0          # a 2.5-moment of |B|/B_axis around a tokamak
    # B_T ~ 1/R dominates -> inboard high-field weights the 2.5 moment up
    assert c >= 1.0


def test_equilibrium_geometry_exposes_real_b25():
    g = _g()
    eq = eqdsk.equilibrium_geometry(g)
    assert "cyclotron_B25" in eq
    assert eq["cyclotron_B25"] == pytest.approx(eqdsk.cyclotron_b25_from_eqdsk(g), rel=1e-9)


def test_funsc_uses_real_b25_for_real_equilibrium():
    g = _g()
    eq = eqdsk.equilibrium_geometry(g)
    R0, a, kappa, delta = eq["R0"], eq["a"], eq["kappa"], eq["delta"]
    common = dict(Sn=0.5, ST=1.0, ni0=1e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5,
                  BT0=eq["bt0"], Ip=max(eq["ip"], 0.1), tauE=1.0, fHe=0.04, fimp=0.01,
                  Zimp=10, Rw=0.7, g=0.1, icase=1, geom_model=2.0, eq=eq)
    real = funsc(R0, a, kappa, delta, **common, cyclotron_B_nonuniform=1.0)
    off = funsc(R0, a, kappa, delta, **common, cyclotron_B_nonuniform=0.0)
    # toggle off -> factor 1
    assert off.cyclotron_B25_factor == pytest.approx(1.0)
    # toggle on with a real equilibrium -> the REAL field factor, not the Miller proxy
    assert real.cyclotron_B25_factor == pytest.approx(eq["cyclotron_B25"], rel=1e-9)
    miller = tokamak_B25_factor(R0, a, kappa, delta)
    assert real.cyclotron_B25_factor != pytest.approx(miller, rel=1e-6)
