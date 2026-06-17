"""UI payload regression for real-machine stellarator Fourier boundaries.

Run: python polyfusion/tests/test_stellarator_shape_payload.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.base import get  # noqa: E402
from polyfusion.io import run_case  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


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


def _extract_const(src: str, name: str) -> str | None:
    needle = f"const {name}="
    try:
        start = src.index(needle)
    except ValueError:
        return None
    end = src.index(";", start) + 1
    return src[start:end]


def _run_clean(vals: dict) -> dict:
    src = open(INDEX, encoding="utf-8").read()
    support = [
        _extract_const(src, "OPAQUE_PARAMS") or "",
    ]
    try:
        support.append(_extract_function(src, "isPlainObject"))
    except ValueError:
        pass
    support.extend([
        _extract_function(src, "inferStellGeomMode"),
        _extract_function(src, "stellGeomMode"),
        _extract_function(src, "cleanStellOverrides"),
    ])
    clean_fn = _extract_function(src, "clean")
    js = f"""
let CUR = 'stellarator';
let VALS = {json.dumps(vals, ensure_ascii=False)};
{chr(10).join(support)}
{clean_fn}
console.log(JSON.stringify(clean()));
"""
    out = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    return json.loads(out)


def _run_mode_sequence(vals: dict) -> dict:
    src = open(INDEX, encoding="utf-8").read()
    support = [
        _extract_function(src, "isPlainObject"),
        _extract_function(src, "cloneJson"),
        _extract_function(src, "inferStellGeomMode"),
        _extract_function(src, "stellGeomMode"),
        _extract_function(src, "stashStellGeom"),
        _extract_function(src, "defaultBoundaryShape"),
        _extract_function(src, "setStellGeomMode"),
    ]
    js = f"""
let CUR = 'stellarator';
let VALS = {json.dumps(vals, ensure_ascii=False)};
let STELL_STASH = {{}};
{chr(10).join(support)}
VALS._geom_mode = inferStellGeomMode();
const initial = VALS._geom_mode;
setStellGeomMode('simple');
const simple = {{mode: VALS._geom_mode, hasShape: !!VALS.shape, hasRc: !!VALS.rc,
  hasIota: 'iota' in VALS, iota: VALS.iota, Vp_override: VALS.Vp_override, Sw_override: VALS.Sw_override}};
setStellGeomMode('axis');
const axis = {{mode: VALS._geom_mode, hasShape: !!VALS.shape,
  hasRc: Array.isArray(VALS.rc), hasZs: Array.isArray(VALS.zs)}};
setStellGeomMode('boundary');
const boundary = {{mode: VALS._geom_mode, hasShape: !!VALS.shape,
  iota: VALS.iota, Vp_override: VALS.Vp_override, Sw_override: VALS.Sw_override}};
console.log(JSON.stringify({{initial, simple, axis, boundary}}));
"""
    out = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
    return json.loads(out)


def ok(cond: bool, msg: str) -> bool:
    print(("PASS" if cond else "FAIL"), msg)
    return bool(cond)


def main() -> int:
    allok = True
    src = open(INDEX, encoding="utf-8").read()
    w7x = get("stellarator").presets["W7-X"]

    allok &= ok("\n  shape:[" not in src,
                "shape is not exposed as a standalone advanced UI field")
    allok &= ok("ADV_PARAMS=new Set(['rc','zs','Vp_override','Sw_override'])" in src,
                "only rc/zs and measured overrides are visible advanced inputs")
    allok &= ok("isPlainObject(VALS.shape)" in src,
                "machine presets with shape auto-expand the advanced inputs")
    allok &= ok('data-p="${p}"' in src and "VALS.shape[mk]" in src,
                "machine boundary R/Z coefficients render through rc/zs inputs")
    allok &= ok("boundary R Fourier" in src and "boundary Z Fourier" in src,
                "machine-boundary rc/zs labels distinguish boundary Fourier from axis Fourier")
    allok &= ok("item('simple'" in src and "item('axis'" in src
                and "item('boundary'" in src and 'data-gmode="${k}"' in src,
                "stellarator geometry mode switch exposes all three input modes")
    allok &= ok("function showParamForMode" in src and "p==='delta_h'" in src
                and "p==='Vp_override'||p==='Sw_override'" in src,
                "mode switch hides parameters that do not apply to the selected geometry input")
    allok &= ok("textarea class=\"shape-json\"" not in src,
                "there is no large standalone shape textarea")

    seq = _run_mode_sequence(dict(w7x))
    allok &= ok(seq["initial"] == "boundary",
                "W7-X preset starts in boundary Fourier mode")
    allok &= ok(seq["simple"]["mode"] == "simple" and not seq["simple"]["hasShape"]
                and not seq["simple"]["hasRc"] and not seq["simple"]["hasIota"],
                "simple near-axis mode removes machine boundary and measured overrides")
    allok &= ok(seq["axis"]["mode"] == "axis" and seq["axis"]["hasRc"]
                and seq["axis"]["hasZs"] and not seq["axis"]["hasShape"],
                "axis Fourier mode uses rc/zs and no machine shape")
    allok &= ok(seq["boundary"]["mode"] == "boundary" and seq["boundary"]["hasShape"]
                and seq["boundary"]["iota"] == w7x["iota"]
                and seq["boundary"]["Vp_override"] == w7x["Vp_override"]
                and seq["boundary"]["Sw_override"] == w7x["Sw_override"],
                "boundary Fourier mode restores shape and measured machine overrides")

    vals = dict(w7x)
    vals["delta_h"] = 0.250000
    payload = _run_clean(vals)
    allok &= ok("shape" in payload, "clean() preserves the Fourier shape object")
    if "shape" in payload:
        allok &= ok(payload["shape"] == w7x["shape"],
                    "clean() sends shape unchanged")
    allok &= ok("delta_h" not in payload,
                "boundary Fourier clean() omits unused delta_h")
    allok &= ok(payload.get("etabar") == w7x["etabar"],
                "boundary Fourier clean() keeps etabar for backend validation")

    edited = run_case(payload, config="stellarator")
    allok &= ok(edited.get("shape", {}).get("mode") == "machine-boundary",
                "same-value W7-X edit still renders the machine Fourier boundary")

    initial = run_case({}, preset="W7-X", config="stellarator")
    if "outputs" in edited and "outputs" in initial:
        allok &= ok(abs(edited["outputs"]["Vp_geom"] - initial["outputs"]["Vp_geom"]) < 1e-9,
                    "same-value edit preserves W7-X Vp_geom")
        allok &= ok(abs(edited["outputs"]["Sw_geom"] - initial["outputs"]["Sw_geom"]) < 1e-9,
                    "same-value edit preserves W7-X Sw_geom")

    print("\nRESULT:", "SHAPE PAYLOAD PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
