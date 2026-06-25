"""Predictive-mode (tauE=0) confinement scaling selector.

Three scaling laws live side-by-side in the result (H98 / HST / H_ITPA20) but
historically only IPB98 fed the root-finder. The ``tauE_scaling`` parameter
selects which scaling defines the predictive target H_fac.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.io import run_case  # noqa: E402
from polyfusion.tokamak import funsc  # noqa: E402


_ITER_BASE = dict(
    R0=6.2, A=3.1, kappa=1.86, delta=0.5,
    Sn=0.5, ST=1.0, ni0=1e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5,
    BT0=5.3, Ip=15.0, fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.05,
    icase=1, imp_name=None, f_aux_e=0.5,
    geom_model=0.0, eq=None,
    Vp_override=0.0, Sw_override=0.0,
    cyclotron_B_nonuniform=0.0,
)

# ST scaling targets a database fit on small spherical-tokamak machines
# (NSTX/MAST). On a big conventional tokamak like ITER, HST is tiny
# (~0.03 at tauE=2s) so HST=1 is unreachable in the [1e-3,50]s bracket.
# Use an NSTX-class operating point for ST-scaling root-finding tests.
_NSTX_BASE = dict(
    R0=0.85, A=1.4, kappa=2.0, delta=0.4,
    Sn=0.5, ST=1.0, ni0=5e19, Ti0=2.0, fT=1.0, fsig=1.0, f1=0.5,
    BT0=0.5, Ip=1.0, fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.05,
    icase=1, imp_name=None, f_aux_e=0.5,
    geom_model=0.0, eq=None,
    Vp_override=0.0, Sw_override=0.0,
    cyclotron_B_nonuniform=0.0,
)


def _solve(base=None, **over):
    p = dict(base if base is not None else _ITER_BASE, **over)
    return funsc(**p)


def test_default_scaling_is_ipb98_and_matches_legacy():
    """Default behavior (no tauE_scaling) = IPB98 root-finding, golden-stable."""
    res_default = _solve(tauE=0.0, use_tauE=0.0, H_fac=1.0)
    res_explicit = _solve(tauE=0.0, use_tauE=0.0, H_fac=1.0, tauE_scaling="ipb98")
    assert res_default.tauE_used == pytest.approx(res_explicit.tauE_used, rel=1e-12)
    assert res_default.H98 == pytest.approx(1.0, rel=1e-4)
    assert res_default.taue_mode == 1.0


def test_st_scaling_makes_HST_hit_H_fac():
    """When tauE_scaling='st', root-finder targets HST instead of H98."""
    res = _solve(_NSTX_BASE, tauE=0.0, use_tauE=0.0, H_fac=1.0, tauE_scaling="st")
    assert res.taue_mode == 1.0
    assert res.HST == pytest.approx(1.0, rel=1e-4)
    assert res.H98 != pytest.approx(1.0, rel=1e-2), (
        "if H98 also hit 1.0 the selector did nothing")


def test_itpa20_scaling_makes_H_ITPA20_hit_H_fac():
    res = _solve(tauE=0.0, use_tauE=0.0, H_fac=1.0, tauE_scaling="itpa20")
    assert res.taue_mode == 1.0
    assert res.H_ITPA20 == pytest.approx(1.0, rel=1e-4)
    assert res.H98 != pytest.approx(1.0, rel=1e-2)


def test_h_fac_scales_target_through_chosen_scaling():
    """H_fac=1.3 with ST scaling -> HST=1.3 (not H98=1.3)."""
    res = _solve(_NSTX_BASE, tauE=0.0, use_tauE=0.0, H_fac=1.3, tauE_scaling="st")
    assert res.HST == pytest.approx(1.3, rel=1e-4)


def test_invalid_scaling_raises():
    with pytest.raises(ValueError, match="tauE_scaling"):
        _solve(tauE=0.0, use_tauE=0.0, H_fac=1.0, tauE_scaling="bogus")


def test_manual_tauE_ignores_scaling_selector():
    """Manual mode (tauE>0): the selector is irrelevant — H98/HST/H_ITPA20 are
    just diagnostics. Solver must not crash, output must not move with the
    selector when tauE is fixed."""
    r1 = _solve(tauE=2.0, use_tauE=1.0, tauE_scaling="ipb98")
    r2 = _solve(tauE=2.0, use_tauE=1.0, tauE_scaling="st")
    r3 = _solve(tauE=2.0, use_tauE=1.0, tauE_scaling="itpa20")
    for r in (r1, r2, r3):
        assert math.isfinite(r.Pfus) and r.Pfus > 0
    assert r1.H98 == pytest.approx(r2.H98) == pytest.approx(r3.H98)


def test_config_layer_passes_scaling_through():
    """run_case() / ConfigSpec.solve must whitelist tauE_scaling."""
    params = dict(_NSTX_BASE)
    params.update(tauE=0.0, use_tauE=0.0, H_fac=1.0, tauE_scaling="st")
    res = run_case(params, config="tokamak")
    assert "errors" not in res, res.get("errors")
    out = res["outputs"]
    assert out["taue_mode"] == 1.0
    assert out["HST"] == pytest.approx(1.0, rel=1e-4)


def test_config_layer_rejects_invalid_scaling():
    params = dict(_ITER_BASE)
    params.update(tauE=0.0, use_tauE=0.0, H_fac=1.0, tauE_scaling="bogus")
    res = run_case(params, config="tokamak")
    assert "errors" in res
    assert any("tauE_scaling" in e for e in res["errors"])
