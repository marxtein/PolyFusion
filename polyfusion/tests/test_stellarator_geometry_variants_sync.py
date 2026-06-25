from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.stellarator import (  # noqa: E402
    _nearaxis_boundary_fn_with_rho,
    _shape_boundary_fn_with_rho,
    section_outlines,
)
from polyfusion.io import run_case  # noqa: E402
from polyfusion.presets_io import load_presets  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")

AUTHORITY = {
    "W7-X": "boundary",
    "LHD": "boundary",
    "HSX": "boundary",
    "CFQS": "boundary",
    "precise-QA": "axis",
    "precise-QH": "axis",
    "QH-nfp3": "axis",
    "HELIAS": "simple",
    "NAE-QA": "simple",
    "用户设计 User Design": "simple",
}


def _payload_for_mode(preset: dict, mode: str) -> dict:
    p = dict(preset)
    variants = p["geometry_variants"]
    v = variants[mode]
    p["geometry_variants"] = variants
    if mode == "simple":
        p.update({k: v[k] for k in ("delta_h", "etabar") if k in v})
        for k in ("shape", "rc", "zs", "iota", "Vp_override", "Sw_override"):
            p.pop(k, None)
    elif mode == "axis":
        p.update({k: v[k] for k in ("rc", "zs", "etabar") if k in v})
        for k in ("shape", "delta_h", "iota", "Vp_override", "Sw_override"):
            p.pop(k, None)
    elif mode == "boundary":
        p.update({k: v[k] for k in ("shape", "iota", "Vp_override", "Sw_override", "etabar") if k in v})
        for k in ("rc", "zs", "delta_h"):
            p.pop(k, None)
    else:
        raise AssertionError(mode)
    return p


def _assert_outline_sane(outline: dict) -> None:
    assert outline.get("sections")
    for section in outline["sections"]:
        assert section["R"] and section["Z"]
        assert len(section["R"]) == len(section["Z"])
        assert all(math.isfinite(x) for x in section["R"])
        assert all(math.isfinite(z) for z in section["Z"])


def _extract_function(src: str, name: str) -> str:
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
    raise AssertionError(f"could not extract function {name}")


def test_all_presets_have_complete_geometry_variants():
    presets, _ = load_presets("stellarator")
    assert set(AUTHORITY) <= set(presets)
    for name, preset in presets.items():
        variants = preset.get("geometry_variants")
        assert isinstance(variants, dict), name
        assert variants.get("authority") == AUTHORITY[name]
        for mode in ("simple", "axis", "boundary"):
            assert isinstance(variants.get(mode), dict), f"{name}/{mode}"
            assert variants[mode], f"{name}/{mode}"


def test_authoritative_geometry_is_preserved_in_variant():
    presets, _ = load_presets("stellarator")
    for name, authority in AUTHORITY.items():
        p = presets[name]
        v = p["geometry_variants"][authority]
        if authority == "boundary":
            assert v["shape"] == p["shape"]
            assert v["iota"] == p["iota"]
            assert v["Vp_override"] == p["Vp_override"]
            assert v["Sw_override"] == p["Sw_override"]
        elif authority == "axis":
            assert v["rc"] == p["rc"]
            assert v["zs"] == p["zs"]
            assert v["etabar"] == p["etabar"]
        else:
            assert v["delta_h"] == p["delta_h"]
            assert v["etabar"] == p["etabar"]


@pytest.mark.parametrize("mode", ["simple", "axis", "boundary"])
def test_every_preset_mode_runs_case_and_section_outlines(mode):
    presets, _ = load_presets("stellarator")
    for name, preset in presets.items():
        payload = _payload_for_mode(preset, mode)
        run = run_case(payload, config="stellarator")
        assert "errors" not in run, f"{name}/{mode}: {run.get('errors')}"
        assert run["outputs"]["valid"] == 1.0, f"{name}/{mode}"
        _assert_outline_sane(section_outlines(**payload))


def test_shape_view_uses_same_200_point_boundary_sampling_as_integral_path():
    presets, _ = load_presets("stellarator")
    cases = [
        _payload_for_mode(presets["HELIAS"], "simple"),
        _payload_for_mode(presets["W7-X"], "boundary"),
    ]
    for payload in cases:
        outline = section_outlines(**payload)
        sec = outline["sections"][0]
        display_R = sec["R"][:-1]
        display_Z = sec["Z"][:-1]
        assert len(sec["R"]) == 201
        assert sec["R"][0] == pytest.approx(sec["R"][-1])
        assert sec["Z"][0] == pytest.approx(sec["Z"][-1])
        if "shape" in payload:
            boundary_fn, _ = _shape_boundary_fn_with_rho(
                payload["R0"], payload["a"], payload["shape"])
        else:
            boundary_fn, _ = _nearaxis_boundary_fn_with_rho(
                payload["R0"], payload["a"], payload["N_fp"],
                payload.get("delta_h", 0.0), payload["etabar"],
                rc=payload.get("rc"), zs=payload.get("zs"))
        integ_R, integ_Z = boundary_fn(0.0, 1.0)
        assert display_R == pytest.approx(integ_R.tolist())
        assert display_Z == pytest.approx(integ_Z.tolist())


def test_posterior_perimeters_use_exact_boundary_integral_surface_areas():
    presets, _ = load_presets("stellarator")
    for name in ("HELIAS", "NAE-QA", "W7-X", "LHD", "HSX", "CFQS"):
        mode = presets[name]["geometry_variants"]["authority"]
        payload = _payload_for_mode(presets[name], mode)
        run = run_case(payload, config="stellarator")
        assert "errors" not in run, f"{name}: {run.get('errors')}"
        out = run["outputs"]
        assert out["C_sec_mean"] * out["L_ax"] == pytest.approx(out["Sp_geom"])
        assert out["C_wall_mean"] * out["L_ax"] == pytest.approx(out["Sw_geom"])


def test_synthetic_boundary_variants_do_not_claim_measured_values():
    presets, _ = load_presets("stellarator")
    for name, preset in presets.items():
        boundary = preset["geometry_variants"]["boundary"]
        source = boundary.get("shape", {}).get("source", "")
        if "synthetic" in source:
            assert boundary.get("iota", 0) == 0, name
            assert boundary.get("Vp_override", 0) == 0, name
            assert boundary.get("Sw_override", 0) == 0, name


def test_frontend_has_no_geometry_sync_feature():
    src = open(INDEX, encoding="utf-8").read()
    server = open(os.path.join(ROOT, "app", "server.py"), encoding="utf-8").read()
    assert "syncStellGeometryVariants" not in src
    assert "syncGeom" not in src
    assert "同步到其他几何" not in src
    assert "/api/stellarator/sync_geometry" not in server


def test_frontend_boundary_keeps_its_own_iota_input_without_authority_semantics():
    src = open(INDEX, encoding="utf-8").read()
    assert "p==='Vp_override'||p==='Sw_override'||p==='iota'" in src
    assert "iota_geom_authoritative" not in src
    assert "边界自身参数自洽计算" in src
    assert "使用权威/拟合几何值" not in src


def test_boundary_fourier_mode_numbers_must_be_integers():
    presets, _ = load_presets("stellarator")
    payload = _payload_for_mode(presets["W7-X"], "boundary")
    payload["shape"] = json.loads(json.dumps(payload["shape"]))
    payload["shape"]["Z"][0][1] = -1.5
    run = run_case(payload, config="stellarator")
    assert run["errors"]
    assert "integer" in run["errors"][0]


def test_frontend_rejects_noninteger_boundary_fourier_modes():
    src = open(INDEX, encoding="utf-8").read()
    support = [_extract_function(src, "parseBoundaryFourier")]
    js = f"""
{chr(10).join(support)}
const good = parseBoundaryFourier('[0,-1,0.46], [1,2,-0.3]');
const bad = parseBoundaryFourier('[0,-1.5,0.46]');
console.log(JSON.stringify({{good, bad}}));
"""
    out = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    data = json.loads(out)
    assert data["good"] == [[0, -1, 0.46], [1, 2, -0.3]]
    assert data["bad"] is None


def test_frontend_mode_switch_prefers_geometry_variants():
    src = open(INDEX, encoding="utf-8").read()
    support = [
        _extract_function(src, "isPlainObject"),
        _extract_function(src, "cloneJson"),
        _extract_function(src, "isFiniteNum"),
        _extract_function(src, "inferStellGeomMode"),
        _extract_function(src, "stashStellGeom"),
        _extract_function(src, "defaultBoundaryShape"),
        _extract_function(src, "stellVariant"),
        _extract_function(src, "normalizeStellBoundaryIota"),
        _extract_function(src, "applyStellVariant"),
        _extract_function(src, "setStellGeomMode"),
    ]
    vals = {
        "R0": 5.5,
        "a": 0.55,
        "N_fp": 5,
        "delta_h": 0.25,
        "etabar": 0.119,
        "shape": {"kind": "fourier", "nfp": 5, "R": [[1, 0, 1]], "Z": [[-1, 0, 1]], "source": "auth"},
        "geometry_variants": {
            "authority": "boundary",
            "simple": {"delta_h": 0.31, "etabar": 0.119},
            "axis": {"rc": [5.5, 0.123], "zs": [0, -0.456], "etabar": 0.119},
            "boundary": {
                "shape": {"kind": "fourier", "nfp": 5, "R": [[1, 0, 1]], "Z": [[-1, 0, 1]], "source": "variant-boundary"},
                "iota": 0.88,
                "Vp_override": 30,
                "Sw_override": 128,
                "etabar": 0.119,
            },
        },
    }
    js = f"""
let CUR = 'stellarator';
let ADVANCED = false;
let STELL_STASH = {{rc: [99], zs: [99]}};
let VALS = {json.dumps(vals, ensure_ascii=False)};
{chr(10).join(support)}
VALS._geom_mode = inferStellGeomMode();
setStellGeomMode('axis');
const axis = {{rc: VALS.rc, zs: VALS.zs, hasShape: !!VALS.shape}};
setStellGeomMode('boundary');
const boundary = {{source: VALS.shape.source, iota: VALS.iota, vp: VALS.Vp_override, sw: VALS.Sw_override, hasRc: !!VALS.rc}};
setStellGeomMode('simple');
const simple = {{delta_h: VALS.delta_h, etabar: VALS.etabar, hasShape: !!VALS.shape, hasRc: !!VALS.rc, hasIota: 'iota' in VALS}};
console.log(JSON.stringify({{axis, boundary, simple}}));
"""
    out = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    data = json.loads(out)
    assert data["axis"] == {"rc": [5.5, 0.123], "zs": [0, -0.456], "hasShape": False}
    assert data["boundary"] == {"source": "variant-boundary", "iota": 0.88, "vp": 30, "sw": 128, "hasRc": False}
    assert data["simple"] == {"delta_h": 0.31, "etabar": 0.119, "hasShape": False, "hasRc": False, "hasIota": False}


def test_frontend_restores_matching_authoritative_boundary_iota_from_stale_zero():
    src = open(INDEX, encoding="utf-8").read()
    support = [
        _extract_function(src, "isPlainObject"),
        _extract_function(src, "cloneJson"),
        _extract_function(src, "isFiniteNum"),
        _extract_function(src, "inferStellGeomMode"),
        _extract_function(src, "stellGeomMode"),
        _extract_function(src, "normalizeStellBoundaryIota"),
    ]
    shape = {
        "kind": "fourier", "nfp": 5,
        "R": [[1, 0, 1.0]], "Z": [[-1, 0, 1.0]],
    }
    vals = {
        "_geom_mode": "boundary",
        "shape": shape,
        "iota": 0.0,
        "geometry_variants": {
            "authority": "boundary",
            "boundary": {"shape": shape, "iota": 0.88},
        },
    }
    js = f"""
let CUR = 'stellarator';
let VALS = {json.dumps(vals)};
{chr(10).join(support)}
normalizeStellBoundaryIota();
const restored = VALS.iota;
VALS.iota = 0;
VALS.shape.R[0][2] = 0.9;
normalizeStellBoundaryIota();
console.log(JSON.stringify({{restored, edited: VALS.iota}}));
"""
    out = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    data = json.loads(out)
    assert data == {"restored": 0.88, "edited": 0}


def test_iota_uses_only_the_current_geometry_parameters():
    presets, _ = load_presets("stellarator")
    for mode in ("simple", "axis"):
        payload = _payload_for_mode(presets["W7-X"], mode)
        baseline = dict(payload)
        baseline["iota"] = 0.0
        overridden = dict(payload)
        overridden["iota"] = 9.9
        overridden["geometry_variants"] = {
            "authority": "boundary",
            "boundary": {"shape": overridden.get("shape"), "iota": 8.8},
        }
        run0 = run_case(baseline, config="stellarator")
        run1 = run_case(overridden, config="stellarator")
        assert "errors" not in run0, f"{mode}: {run0.get('errors')}"
        assert "errors" not in run1, f"{mode}: {run1.get('errors')}"
        assert run0["outputs"]["iota"] == pytest.approx(run0["outputs"]["iota_geom"])
        assert run1["outputs"]["iota"] == pytest.approx(run1["outputs"]["iota_geom"])
        assert run1["outputs"]["iota"] == pytest.approx(run0["outputs"]["iota"])
        assert run1["outputs"]["iota_geom_authoritative"] == 0.0

    boundary = _payload_for_mode(presets["W7-X"], "boundary")
    boundary["iota"] = 0.73
    boundary["geometry_variants"] = {
        "authority": "axis",
        "boundary": {"shape": boundary["shape"], "iota": 8.8},
    }
    run = run_case(boundary, config="stellarator")
    assert "errors" not in run, run.get("errors")
    assert run["outputs"]["iota"] == pytest.approx(0.73)
    assert run["outputs"]["iota_geom"] == pytest.approx(0.73)


def test_sw_override_derives_sp_from_uniform_wall_gap():
    presets, _ = load_presets("stellarator")
    payload = _payload_for_mode(presets["W7-X"], "boundary")
    payload["g"] = 0.05
    run = run_case(payload, config="stellarator")
    assert "errors" not in run
    out = run["outputs"]
    expected_sp = payload["Sw_override"] * out["a_vol"] / (out["a_vol"] + payload["g"])
    assert out["Sw"] == pytest.approx(payload["Sw_override"])
    assert out["Sp"] == pytest.approx(expected_sp)


def test_boundary_authority_axis_and_simple_iota_are_close_to_authority():
    presets, _ = load_presets("stellarator")
    for name in ("W7-X", "LHD", "HSX", "CFQS"):
        preset = presets[name]
        target = preset["geometry_variants"]["boundary"]["iota"]
        for mode in ("simple", "axis"):
            payload = _payload_for_mode(preset, mode)
            run = run_case(payload, config="stellarator")
            assert "errors" not in run, f"{name}/{mode}: {run.get('errors')}"
            assert abs(run["outputs"]["iota_geom"] - target) < max(0.25, 0.5 * target), (
                name, mode, run["outputs"]["iota_geom"], target
            )
