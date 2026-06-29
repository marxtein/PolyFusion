"""Stellarator minor-radius API and effective-radius power-account checks.

Run: python polyfusion/tests/test_stellarator_minor_radius_api.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.configs.base import get  # noqa: E402
from polyfusion.io import list_configs, run_case  # noqa: E402


def ok(cond: bool, msg: str) -> bool:
    print(("PASS" if cond else "FAIL"), msg)
    return bool(cond)


def main() -> int:
    allok = True
    meta = list_configs()["stellarator"]
    allok &= ok("a" in meta["params"], "stellarator UI/API exposes minor radius a")
    allok &= ok(
        "A" not in meta["params"], "stellarator UI/API no longer exposes aspect ratio A"
    )

    spec = get("stellarator")
    w7x = dict(spec.presets["W7-X"])
    allok &= ok(
        "a" in w7x and "A" not in w7x, "packaged W7-X preset stores a, not legacy A"
    )

    legacy = dict(w7x)
    if "a" in legacy:
        legacy["A"] = legacy["R0"] / legacy.pop("a")
    new_payload = dict(w7x)
    if "a" not in new_payload and "A" in new_payload:
        new_payload["a"] = new_payload["R0"] / new_payload.pop("A")
    new = run_case(new_payload, config="stellarator")
    old = run_case(legacy, config="stellarator")
    allok &= ok("errors" not in old, "legacy A payload is migrated before validation")
    allok &= ok(
        "a" in old.get("inputs", {}) and "A" not in old.get("inputs", {}),
        "legacy A payload is normalized to a in returned inputs",
    )
    if "outputs" in new and "outputs" in old:
        allok &= ok(
            abs(new["outputs"]["Vp"] - old["outputs"]["Vp"]) < 1e-12,
            "legacy A and new a payloads solve to the same Vp",
        )

    out = new.get("outputs", {})
    if out:
        a_vol = math.sqrt(out["Vp"] / (2 * math.pi**2 * new_payload["R0"]))
        allok &= ok(
            abs(out["a_vol"] - a_vol) < 1e-12,
            "a_vol is volume-equivalent minor radius from Vp and R0",
        )
        allok &= ok(
            abs(out["A_flux"] - out["Vp"] / out["L_ax"]) < 1e-12,
            "A_flux reports effective section area Vp/L_ax",
        )

    print("\nRESULT:", "STELLARATOR MINOR-RADIUS API PASS" if allok else "SOME FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
