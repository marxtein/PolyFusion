#!/usr/bin/env python3
"""Build reproducible VSC report payloads for all five configurations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.server import _do_scan  # noqa: E402
from polyfusion.configs.base import get  # noqa: E402
from polyfusion.io import run_case  # noqa: E402


CONFIGURATIONS = {
    "tokamak": "ITER",
    "mirror": "BEAM",
    "frc": "C-2W",
    "dipole": "Dipole-DD",
    "stellarator": "HELIAS",
}
OPAQUE_PARAMS = {"shape", "geometry_variants", "eq", "equilibrium"}
DROP_KEYS = {
    "inputs",
    "shape",
    "equilibrium",
    "_geom_mode",
    "fields",
    "x",
    "y",
    "valid",
    "scan_errors",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _array_footprint(value: list[Any]) -> int:
    cells = 1
    nested: Any = value
    depth = 0
    while isinstance(nested, list):
        cells *= len(nested) or 1
        nested = nested[0] if nested else None
        depth += 1
    if depth == 0 or cells == 0:
        return 0
    if not isinstance(nested, (str, int, float, bool, type(None))):
        return sys.maxsize
    return cells


def strip_large_arrays(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Mirror the report payload reduction in ``app/index.html``."""
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in DROP_KEYS:
            continue
        if isinstance(item, dict):
            if all(
                nested is None or isinstance(nested, (str, int, float, bool))
                for nested in item.values()
            ):
                result[key] = _json_safe(item)
        elif isinstance(item, list):
            if _array_footprint(item) <= 40_000:
                result[key] = _json_safe(item)
        else:
            result[key] = _json_safe(item)
    return result


def _report_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_safe(value)
        for key, value in params.items()
        if not key.startswith("_") and key not in OPAQUE_PARAMS
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> str:
    payload = _canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + b"\n")
    return hashlib.sha256(payload).hexdigest()


def _grid_values(scan_defaults: dict[str, Any], grid_size: int) -> tuple[list[float], list[float]]:
    def values(start: float, stop: float) -> list[float]:
        if grid_size == 1:
            return [start]
        step = (stop - start) / (grid_size - 1)
        return [start + index * step for index in range(grid_size)]

    return (
        values(float(scan_defaults["xmin"]), float(scan_defaults["xmax"])),
        values(float(scan_defaults["ymin"]), float(scan_defaults["ymax"])),
    )


def build_corpus(
    output_dir: Path,
    grid_size: int,
    *,
    replace: bool,
    force_delete_reports: bool = False,
) -> dict[str, Any]:
    if grid_size < 8:
        raise ValueError("grid size must be at least 8 so every configuration has >=64 cases")
    if output_dir.exists() and replace:
        report_files = list((output_dir / "ai-reports").glob("**/*.md"))
        if report_files and not force_delete_reports:
            raise RuntimeError(
                f"refusing to delete {len(report_files)} archived AI reports; "
                "pass --force-delete-reports only when intentional"
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": created_at,
        "generator": "scripts/build_report_corpus.py",
        "grid_size": grid_size,
        "case_count": 0,
        "configurations": [],
        "cases": [],
    }

    for config, preset in CONFIGURATIONS.items():
        config_started = time.perf_counter()
        spec = get(config)
        defaults = spec.scan_defaults
        xkey, ykey = defaults["xkey"], defaults["ykey"]
        xvalues, yvalues = _grid_values(defaults, grid_size)
        scan_request = {
            "config": config,
            "preset": preset,
            "overrides": {},
            "xkey": xkey,
            "ykey": ykey,
            "xmin": xvalues[0],
            "xmax": xvalues[-1],
            "nx": grid_size,
            "ymin": yvalues[0],
            "ymax": yvalues[-1],
            "ny": grid_size,
            "window": spec.best_window,
        }
        scan = _do_scan(scan_request)
        scan_path = Path("scans") / f"{config}.json"
        scan_hash = _write_json(output_dir / scan_path, scan)
        report_scan = strip_large_arrays(scan)

        valid_count = 0
        best_count = 0
        for xindex, xvalue in enumerate(xvalues):
            for yindex, yvalue in enumerate(yvalues):
                ordinal = xindex * grid_size + yindex + 1
                case_id = f"{config}-{ordinal:03d}"
                overrides = {xkey: xvalue, ykey: yvalue}
                run = run_case(overrides, preset=preset, config=config)
                params = dict(spec.presets[preset])
                params.update(overrides)
                payload = {
                    "config": config,
                    "config_label": spec.label,
                    "preset": preset,
                    "params": _report_params(params),
                    "last_run": strip_large_arrays(run),
                    "last_scan": report_scan,
                    "images": {},
                    "timestamp": created_at,
                    "user": "corpus-builder",
                    "lang": "zh",
                }
                payload_path = Path("payloads") / config / f"{case_id}.json"
                payload_hash = _write_json(output_dir / payload_path, payload)
                outputs = run.get("outputs", {})
                valid = bool(float(outputs.get("valid", 0) or 0) > 0.5)
                in_best = bool(scan["best"][yindex][xindex])
                valid_count += int(valid)
                best_count += int(in_best)
                manifest["cases"].append(
                    {
                        "case_id": case_id,
                        "config": config,
                        "preset": preset,
                        "xkey": xkey,
                        "xvalue": xvalue,
                        "ykey": ykey,
                        "yvalue": yvalue,
                        "valid": valid,
                        "in_best": in_best,
                        "payload": payload_path.as_posix(),
                        "payload_sha256": payload_hash,
                        "scan": scan_path.as_posix(),
                        "scan_sha256": scan_hash,
                        "ai_report_status": "pending",
                    }
                )

        config_cases = grid_size * grid_size
        manifest["configurations"].append(
            {
                "config": config,
                "label": spec.label,
                "preset": preset,
                "xkey": xkey,
                "ykey": ykey,
                "case_count": config_cases,
                "valid_count": valid_count,
                "best_count": best_count,
                "scan": scan_path.as_posix(),
                "scan_sha256": scan_hash,
                "runtime_seconds": round(time.perf_counter() - config_started, 6),
            }
        )
        manifest["case_count"] += config_cases

    manifest["runtime_seconds"] = round(time.perf_counter() - started, 6)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "deterministic-report-corpus",
    )
    parser.add_argument("--grid-size", type=int, default=8)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--force-delete-reports", action="store_true")
    args = parser.parse_args()
    manifest = build_corpus(
        args.output.resolve(),
        args.grid_size,
        replace=args.replace,
        force_delete_reports=args.force_delete_reports,
    )
    print(
        f"built {manifest['case_count']} cases across "
        f"{len(manifest['configurations'])} configurations in "
        f"{manifest['runtime_seconds']:.3f}s"
    )
    for item in manifest["configurations"]:
        print(
            f"{item['config']}: cases={item['case_count']} "
            f"valid={item['valid_count']} best={item['best_count']} "
            f"runtime={item['runtime_seconds']:.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
