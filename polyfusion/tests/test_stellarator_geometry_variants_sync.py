from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.stellarator import section_outlines, sync_geometry_variants  # noqa: E402
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


def test_synthetic_boundary_variants_do_not_claim_measured_values():
    presets, _ = load_presets("stellarator")
    for name, preset in presets.items():
        boundary = preset["geometry_variants"]["boundary"]
        source = boundary.get("shape", {}).get("source", "")
        if "synthetic" in source:
            assert boundary.get("iota", 0) == 0, name
            assert boundary.get("Vp_override", 0) == 0, name
            assert boundary.get("Sw_override", 0) == 0, name


def test_frontend_sync_generates_axis_and_synthetic_boundary():
    src = open(INDEX, encoding="utf-8").read()
    support = [
        _extract_function(src, "isPlainObject"),
        _extract_function(src, "cloneJson"),
        _extract_function(src, "isFiniteNum"),
        _extract_function(src, "inferStellGeomMode"),
        _extract_function(src, "stashStellGeom"),
        _extract_function(src, "stellGeomMode"),
        _extract_function(src, "stellVariant"),
        _extract_function(src, "applyStellVariant"),
        _extract_function(src, "canSyncStellGeometry"),
        _extract_function(src, "stellSyncPayload"),
        _extract_function(src, "showSyncError"),
        _extract_function(src, "syncStellGeometryVariants"),
    ]
    js = f"""
let CUR = 'stellarator';
let VALS = {{}};
let STELL_STASH = {{}};
let ADVANCED = false;
let calls = [];
function L(zh,en){{return en||zh;}}
const document = {{getElementById: () => null}};
async function jpost(url, body){{
  calls.push({{url, body}});
  const mode = body.source_mode;
  return {{geometry_variants: {{
    authority: mode,
    simple: {{delta_h: 0.31, etabar: 0.08}},
    axis: {{rc: [6, 0.31], zs: [0, -0.31], etabar: 0.08}},
    boundary: {{shape: {{kind: 'fourier', nfp: 5, R: [[1,0,1]], Z: [[-1,0,1]], source: 'mock'}}, iota: mode === 'boundary' ? 0.7 : 0, Vp_override: 0, Sw_override: 0, etabar: 0.08}}
  }}}};
}}
{chr(10).join(support)}
(async () => {{
  const cases = [
    {{R0: 6, a: 0.8, N_fp: 5, delta_h: 0.3, etabar: 0.07, _geom_mode: 'simple'}},
    {{R0: 6, a: 0.8, N_fp: 5, rc: [6, 0.3], zs: [0, -0.3], etabar: 0.07, _geom_mode: 'axis'}},
    {{R0: 6, a: 0.8, N_fp: 5, shape: {{kind: 'fourier', nfp: 5, R: [[1,0,1]], Z: [[-1,0,1]]}}, iota: 0.7, Vp_override: 20, Sw_override: 90, etabar: 0.07, _geom_mode: 'boundary'}}
  ];
  const out = [];
  for (const c of cases) {{
    VALS = c; STELL_STASH = {{}};
    const ok = canSyncStellGeometry();
    const changed = await syncStellGeometryVariants();
    out.push({{ok, changed, mode: VALS._geom_mode, authority: VALS.geometry_variants.authority, call: calls[calls.length - 1]}});
  }}
  console.log(JSON.stringify(out));
}})();
"""
    out = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    data = json.loads(out)
    assert [d["ok"] for d in data] == [True, True, True]
    assert [d["changed"] for d in data] == [True, True, True]
    assert [d["authority"] for d in data] == ["simple", "axis", "boundary"]
    assert [d["call"]["url"] for d in data] == ["/api/stellarator/sync_geometry"] * 3
    assert [d["call"]["body"]["source_mode"] for d in data] == ["simple", "axis", "boundary"]
    assert "delta_h" not in data[1]["call"]["body"]["params"]
    assert "rc" not in data[2]["call"]["body"]["params"]


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


def test_boundary_mode_reports_authoritative_iota_geom():
    presets, _ = load_presets("stellarator")
    for name in ("W7-X", "LHD", "HSX", "CFQS"):
        payload = _payload_for_mode(presets[name], "boundary")
        run = run_case(payload, config="stellarator")
        assert "errors" not in run, f"{name}: {run.get('errors')}"
        assert run["outputs"]["iota"] == pytest.approx(payload["iota"])
        assert run["outputs"]["iota_geom"] == pytest.approx(payload["iota"])


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


@pytest.mark.parametrize("source_mode", ["simple", "axis", "boundary"])
def test_backend_sync_generates_other_modes_from_current_mode(source_mode):
    presets, _ = load_presets("stellarator")
    for name, preset in presets.items():
        source = _payload_for_mode(preset, source_mode)
        synced = sync_geometry_variants(source, source_mode=source_mode)
        assert synced["authority"] == source_mode
        for mode in ("simple", "axis", "boundary"):
            assert synced.get(mode), f"{name}/{source_mode}->{mode}"
            payload = dict(source)
            payload["geometry_variants"] = synced
            payload = _payload_for_mode(payload, mode)
            run = run_case(payload, config="stellarator")
            assert "errors" not in run, f"{name}/{source_mode}->{mode}: {run.get('errors')}"


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
