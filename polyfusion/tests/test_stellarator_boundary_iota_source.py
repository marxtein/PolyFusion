"""Boundary-mode iota must come from the boundary, never from a garbage
single-harmonic near-axis fit to the m=0 centerline.

iota (rotational transform) is a property of the full MHD equilibrium and is NOT
derivable from a truncated |m|,|n|<=2 boundary Fourier cartoon in a 0-D code.
For a real-machine boundary (W7-X) the previous fallback ran a near-axis solve on
the m=0 centerline and produced iota~2.32 (real 0.88). The backend must instead:

  * use an explicit ``iota>0`` when supplied (real machines), OR
  * use the near-axis iota only when the boundary carries a genuine near-axis
    axis (``axis_rc``/``axis_zs`` metadata — concepts synthesised from near-axis), OR
  * refuse (raise) when neither is available, rather than emit the centerline garbage.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.io import run_case  # noqa: E402
from polyfusion.presets import load_presets  # noqa: E402


def _boundary_payload(preset):
    p = dict(preset)
    v = preset["geometry_variants"]["boundary"]
    p.update({k: v[k] for k in ("shape", "iota", "Vp_override", "Sw_override", "etabar")
              if k in v})
    for k in ("rc", "zs", "delta_h"):
        p.pop(k, None)
    return p


def test_explicit_boundary_iota_is_used_verbatim():
    presets, _ = load_presets("stellarator")
    p = _boundary_payload(presets["W7-X"])
    p["iota"] = 0.88
    run = run_case(p, config="stellarator")
    assert "errors" not in run, run.get("errors")
    assert run["outputs"]["iota"] == pytest.approx(0.88)
    assert run["outputs"]["iota_geom"] == pytest.approx(0.88)


def test_real_machine_boundary_without_iota_refuses_centerline_garbage():
    """W7-X boundary (no axis_rc metadata) with iota=0 must NOT silently return
    the ~2.32 centerline near-axis fit; it must raise (force an explicit iota)."""
    presets, _ = load_presets("stellarator")
    p = _boundary_payload(presets["W7-X"])
    p["iota"] = 0.0
    assert "axis_rc" not in p["shape"]      # the condition that makes near-axis garbage
    run = run_case(p, config="stellarator")
    assert "errors" in run, "expected a refusal, got " + str(run.get("outputs", {}).get("iota"))
    assert any("iota" in e.lower() for e in run["errors"])


def test_concept_boundary_with_axis_metadata_uses_nearaxis_iota():
    """A boundary synthesised from a near-axis model carries axis_rc/axis_zs; the
    near-axis iota on that REAL axis is legitimate, so iota=0 is allowed there."""
    presets, _ = load_presets("stellarator")
    # HELIAS authority is 'simple'; its boundary variant is synthesised from
    # near-axis and carries axis_rc/axis_zs metadata.
    helias = presets["HELIAS"]
    bvar = helias["geometry_variants"]["boundary"]
    assert isinstance(bvar["shape"].get("axis_rc"), list)
    p = dict(helias)
    p.update({k: bvar[k] for k in ("shape", "iota", "Vp_override", "Sw_override", "etabar")
              if k in bvar})
    for k in ("rc", "zs", "delta_h"):
        p.pop(k, None)
    p["iota"] = 0.0          # rely on the near-axis-on-real-axis computation
    run = run_case(p, config="stellarator")
    assert "errors" not in run, run.get("errors")
    assert run["outputs"]["iota"] > 0.0
    assert run["outputs"]["iota"] < 2.0     # a sane near-axis transform, not garbage
