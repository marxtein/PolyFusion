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
