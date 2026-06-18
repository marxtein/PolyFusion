import os
import math
import numpy as np
import pytest
from polyfusion import eqdsk

FIXTURE = os.path.join(os.path.dirname(__file__), "data", "test_1.geqdsk")


def test_parse_geqdsk_dims_axis_boundary():
    g = eqdsk.parse_geqdsk(open(FIXTURE).read())
    assert g["nw"] == 101 and g["nh"] == 101
    assert g["psirz"].shape == (101, 101)
    assert g["rmaxis"] == pytest.approx(0.9323, abs=1e-3)
    assert g["rbbbs"].size == g["zbbbs"].size >= 200
    assert 0.0 < g["rbbbs"].min() < g["rbbbs"].max() < 2.0


def test_parse_geqdsk_rejects_truncated():
    with pytest.raises(ValueError):
        eqdsk.parse_geqdsk("FREEGS  garbage  3 101 101\n 0.1 0.2 0.3\n")


def test_equilibrium_geometry_real_fixture():
    g = eqdsk.parse_geqdsk(open(FIXTURE).read())
    eq = eqdsk.equilibrium_geometry(g)
    assert eq["R0"] == pytest.approx(0.83, abs=0.05)
    assert eq["a"] == pytest.approx(0.60, abs=0.05)
    assert 1.5 < eq["kappa"] < 2.2
    assert 6.5 < eq["Vp"] < 9.0
    assert 45.0 < eq["Sp"] < 65.0
    assert eq["shaf_shift"] > 0.0
    assert eq["axis"]["R"][0] == pytest.approx(g["rmaxis"])
    fs = eq["flux_surfaces"]
    assert len(fs) >= 4
    widths = [max(s["R"]) - min(s["R"]) for s in fs]
    assert widths == sorted(widths)
    for s in fs:
        assert len(s["R"]) == len(s["Z"]) >= 16


def test_equilibrium_geometry_jsonable():
    import json
    g = eqdsk.parse_geqdsk(open(FIXTURE).read())
    eq = eqdsk.equilibrium_geometry(g)
    json.dumps(eq)


def test_equilibrium_geometry_rejects_empty_boundary():
    g = eqdsk.parse_geqdsk(open(FIXTURE).read())
    g["rbbbs"] = np.array([])
    g["zbbbs"] = np.array([])
    with pytest.raises(ValueError):
        eqdsk.equilibrium_geometry(g)


def test_equilibrium_geometry_exposes_bt0_ip():
    g = eqdsk.parse_geqdsk(open(FIXTURE).read())
    assert "current" in g
    eq = eqdsk.equilibrium_geometry(g)
    # bt0 = toroidal field at the MAGNETIC AXIS (vacuum field ~ 1/R):
    #   B_axis = |bcentr| * rcentr / rmaxis
    b_axis = abs(g["bcentr"]) * g["rcentr"] / g["rmaxis"]
    assert eq["bt0"] == pytest.approx(b_axis, rel=1e-9)
    assert eq["bt0"] > 0
    # the magnetic axis is outboard of rcentr, so the axis field is weaker
    assert eq["bt0"] < abs(g["bcentr"])
    assert eq["ip"] == pytest.approx(abs(g["current"]) / 1e6, rel=1e-9)
    assert eq["ip"] > 0
