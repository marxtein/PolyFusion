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
                return src[start : i + 1]
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
    geom = json.loads(subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True))

    assert geom["R0"] == pytest.approx(6.2)
    assert geom["a"] == pytest.approx(2.0)
    assert geom["Raxis"] == pytest.approx(6.4)
    assert geom["shafranov"] == pytest.approx(0.2)


def test_tokamak_geometry_mode_uses_explicit_cf_or_real_equilibrium_label():
    html = open(os.path.join(ROOT, "app", "index.html"), encoding="utf-8").read()
    fn = _extract_js_function(html, "tokGeomModeHtml")
    js = f"""
function tokGeomMode(){{return '2';}}
function L(zh,en){{return zh;}}
{fn}
console.log(tokGeomModeHtml());
"""
    rendered = subprocess.check_output(
        ["node", "-e", js], cwd=ROOT, text=True, encoding="utf-8"
    )
    assert "CF 解析/真实平衡" in rendered
    assert ">平衡<" not in rendered


def test_zero_gap_backend_wall_is_drawn_dashed_after_boundary():
    html = open(os.path.join(ROOT, "app", "index.html"), encoding="utf-8").read()
    fn = _extract_js_function(html, "tokamakWallDrawSpec")
    js = f"""
{fn}
console.log(JSON.stringify([tokamakWallDrawSpec(0),tokamakWallDrawSpec(0.02)]));
"""
    zero, finite = json.loads(
        subprocess.check_output(
            ["node", "-e", js], cwd=ROOT, text=True, encoding="utf-8"
        )
    )
    assert zero == {"afterBoundary": True, "dash": "dash"}
    assert finite == {"afterBoundary": False, "dash": "solid"}


def test_tokamak_axis_trace_labels_analytic_double_ellipse_axis():
    html = open(os.path.join(ROOT, "app", "index.html"), encoding="utf-8").read()
    fn = _extract_js_function(html, "tokamakAxisTrace")
    js = f"""
{fn}
console.log(JSON.stringify(tokamakAxisTrace(3.2,0,'磁轴')));
"""
    trace = json.loads(
        subprocess.check_output(
            ["node", "-e", js], cwd=ROOT, text=True, encoding="utf-8"
        )
    )
    assert trace["x"] == [3.2]
    assert trace["y"] == [0]
    assert trace["text"] == ["磁轴"]
    assert trace["mode"] == "markers+text"


def test_double_ellipse_uses_shared_zero_gap_wall_overlay_rule():
    html = open(os.path.join(ROOT, "app", "index.html"), encoding="utf-8").read()
    branch = html[
        html.index("const rr=[0.2*a") : html.index(
            "// Geometry for the dimension callouts"
        )
    ]
    assert "tokamakWallDrawSpec(g)" in branch
    assert "if(wallSpec.afterBoundary)" in branch
