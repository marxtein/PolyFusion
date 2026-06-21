from __future__ import annotations

import json
import os
import subprocess

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _extract_js_function(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(name)


def test_shifted_equilibrium_keeps_r0_at_lcfs_geometric_center():
    html = open(os.path.join(ROOT, "app", "index.html"), encoding="utf-8").read()
    fn = _extract_js_function(html, "tokamakAnnotationGeometry")
    tok = {"R0": 6.2, "A": 3.1, "kappa": 1.7, "delta": 0.33}
    shape = {
        "lcfs": {
            "R": [8.2, 5.54, 4.2, 5.54],
            "Z": [0.0, 3.4, 0.0, -3.4],
        },
        "axis": {"R": [6.4], "Z": [0.0]},
    }
    js = f"""
{fn}
console.log(JSON.stringify(tokamakAnnotationGeometry(
  {json.dumps(tok)}, {json.dumps(shape)}
)));
"""
    geom = json.loads(
        subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    )

    assert geom["R0"] == pytest.approx(6.2)
    assert geom["a"] == pytest.approx(2.0)
    assert geom["Raxis"] == pytest.approx(6.4)
    assert geom["shafranov"] == pytest.approx(0.2)
