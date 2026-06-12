"""Release-mode tauE switch smoke checks.

Run: python polyfusion/tests/test_release_simplified.py

Every configuration exposes a ``use_tauE`` switch:
    use_tauE=1 -> user-provided tauE transport account;
    use_tauE=0 -> the configuration's implemented self-consistent loss model.

Dipole has no implemented self-consistent loss closure, so it is intentionally
locked to use_tauE=1.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from polyfusion.io import list_configs, run_case  # noqa: E402


def ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return bool(cond)


def main() -> int:
    all_ok = True
    meta = list_configs()

    for cfg, m in meta.items():
        params = set(m["params"])
        all_ok &= ok("use_tauE" in params, f"{cfg}: tauE switch is visible")
        all_ok &= ok("tauE" in params, f"{cfg}: tauE is user-visible")

        preset = m["presets"][0]
        r = run_case({"use_tauE": 1}, preset=preset, config=cfg)
        all_ok &= ok("outputs" in r, f"{cfg}/{preset}: preset runs")
        if "outputs" not in r:
            print("  errors:", r.get("errors"))
            continue
        o = r["outputs"]
        rad = o.get("Pbrem", 0.0) + o.get("Pcycl", 0.0) + o.get("P_line", 0.0)
        trans = o.get("Ptrans", o.get("Pth", 0.0))
        all_ok &= ok(math.isfinite(rad) and rad >= 0.0, f"{cfg}: radiation finite")
        all_ok &= ok(math.isfinite(trans) and trans >= 0.0,
                     f"{cfg}: transport is exposed")

    self_cases = [
        ("tokamak", "ITER", {"use_tauE": 0}),
        ("tokamak", "ITER", {"use_tauE": 0, "fT": 0}),
        ("mirror", "BEAM", {"use_tauE": 0}),
        ("mirror", "BEAM", {"use_tauE": 0, "Te0": 0}),
        ("frc", "FRC-DT", {"use_tauE": 0}),
        ("stellarator", "HELIAS", {"use_tauE": 0}),
        ("stellarator", "HELIAS", {"use_tauE": 0, "fT": 0}),
    ]
    for cfg, preset, override in self_cases:
        r = run_case(override, preset=preset, config=cfg)
        all_ok &= ok("outputs" in r, f"{cfg}: self mode {override} runs")

    r = run_case({"use_tauE": 0}, preset="Dipole-DD", config="dipole")
    all_ok &= ok("errors" in r, "dipole: self mode is explicitly unavailable")

    print("\nRESULT:", "TAUE SWITCH SMOKE PASS" if all_ok else "TAUE SWITCH SMOKE FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
