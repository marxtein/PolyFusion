"""Headless CLI for the PolyFusion (stdlib only).

Examples
--------
    python -m polyfusion --list
    python -m polyfusion --preset ITER
    python -m polyfusion --config mirror --preset BEAM
    python -m polyfusion --config mirror --preset BEAM --set Ti=20 ni0=4e20
    python -m polyfusion --params case.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .io import run_case, to_json, list_configs


def _parse_set(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set expects key=value, got {it!r}")
        k, v = it.split("=", 1)
        out[k] = int(v) if k == "icase" else float(v)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="polyfusion", description="ETSC 0-D core")
    ap.add_argument("--config", default="tokamak", help="configuration name")
    ap.add_argument("--preset", help="preset name (see --list)")
    ap.add_argument("--params", help="JSON file with parameter overrides")
    ap.add_argument("--set", nargs="*", metavar="K=V", help="inline overrides")
    ap.add_argument("--list", action="store_true", help="list configs/presets and exit")
    args = ap.parse_args(argv)

    if args.list:
        for name, meta in list_configs().items():
            print(f"[{name}] {meta['label']}  presets: {', '.join(meta['presets'])}")
        return 0

    overrides = {}
    if args.params:
        with open(args.params, encoding="utf-8") as fh:
            overrides.update(json.load(fh))
    overrides.update(_parse_set(args.set))

    if not (args.preset or overrides):
        ap.error("nothing to run: give --preset, --params, or --set")
        return 2

    res = run_case(overrides, preset=args.preset, config=args.config)
    print(to_json(res, indent=2))
    return 1 if "errors" in res else 0


if __name__ == "__main__":
    sys.exit(main())
