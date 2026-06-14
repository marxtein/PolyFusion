"""Presets-as-data loader checks (main()/exit-code style).

Verifies that every configuration's presets load from the packaged JSON, that
the golden ITER tokamak point still solves to its reference Pfus/Q, that a
representative preset of each config runs valid, and that a user-supplied
``~/.polyfusion/presets/<config>.json`` merges on top of the packaged data
(override/extend) without clobbering the shipped presets.

Run: python polyfusion/tests/test_presets_io.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets, _USER_DIR  # noqa: E402
from polyfusion.io import run_preset  # noqa: E402

# expected group-label sets per config (keys only; order not asserted)
EXPECTED_GROUPS = {
    "tokamak": {"实验装置 Experiments", "燃烧·反应堆 Burning·Reactor",
                "ENN 概念 Concepts"},
    "mirror": {"实验装置 Experiments", "概念·反应堆 Concepts"},
    "frc": {"实验装置 Experiments", "概念·反应堆 Concepts"},
    "dipole": {"实验装置 Experiments", "概念·反应堆 Concepts"},
    "stellarator": {"实验装置 Experiments", "反应堆 Reactor"},
}
# one representative preset per config that must run valid
REP_PRESET = {
    "tokamak": "ITER", "mirror": "GDT", "frc": "C-2W",
    "dipole": "LDX", "stellarator": "HELIAS",
}


def _ok(cond, msg):
    print(("PASS" if cond else "FAIL"), msg)
    return cond


def main():
    allok = True

    # 1. every config loads a non-empty presets dict + the expected groups
    for cfg, exp_groups in EXPECTED_GROUPS.items():
        presets, groups = load_presets(cfg)
        allok &= _ok(isinstance(presets, dict) and len(presets) > 0,
                     f"{cfg}: non-empty presets ({len(presets)})")
        allok &= _ok(set(groups) == exp_groups,
                     f"{cfg}: groups == expected ({sorted(groups)})")

    # 2. golden ITER tokamak point still solves to reference Pfus/Q
    o = run_preset("ITER", "tokamak")["outputs"]
    allok &= _ok(abs(o["Pfus"] - 381.39) < 0.05,
                 f"ITER Pfus ~ 381.39 (got {o['Pfus']:.5f})")
    allok &= _ok(abs(o["Qfus"] - 5.03) < 0.02,
                 f"ITER Qfus ~ 5.03 (got {o['Qfus']:.5f})")

    # 3. a representative preset of each config runs valid (no errors)
    for cfg, name in REP_PRESET.items():
        res = run_preset(name, cfg)
        valid = "errors" not in res and res.get("outputs", {}).get("valid") == 1.0
        allok &= _ok(valid, f"{cfg}: preset {name!r} runs valid")

    # 4. user-dir merge: a ~/.polyfusion/presets/tokamak.json adds a preset
    #    AND the packaged ITER survives.  Skip the write if a real user file is
    #    already there (do not clobber the user's data).
    user_path = os.path.join(_USER_DIR, "tokamak.json")
    if os.path.exists(user_path):
        print("SKIP user-dir merge: ~/.polyfusion/presets/tokamak.json exists "
              "(not clobbering real user data)")
    else:
        created_dir = not os.path.isdir(_USER_DIR)
        # minimal valid tokamak preset (all required params present)
        fake = {"presets": {"_TESTONLY_": {
            "R0": 6.0, "A": 3.0, "kappa": 1.8, "delta": 0.5, "Sn": 0.5,
            "ST": 1.0, "ni0": 1e20, "Ti0": 20.0, "fT": 1.0, "fsig": 1.0,
            "f1": 0.5, "BT0": 5.0, "Ip": 8.0, "tauE": 1.0, "fHe": 0.04,
            "fimp": 0.01, "Zimp": 10, "Rw": 0.7, "g": 0.05, "icase": 1}},
            "groups": {}}
        try:
            os.makedirs(_USER_DIR, exist_ok=True)
            with open(user_path, "w", encoding="utf-8") as fh:
                json.dump(fake, fh, ensure_ascii=False)
            # NB: load_presets() merges the user file; the REGISTRY's
            # spec.presets is a snapshot taken at import time, so run_preset()
            # only sees user presets present before import — we therefore assert
            # the merge at the loader level (the documented entry point).
            presets, _ = load_presets("tokamak")
            allok &= _ok("_TESTONLY_" in presets,
                         "user-dir merge: _TESTONLY_ present")
            allok &= _ok("ITER" in presets,
                         "user-dir merge: packaged ITER still present")
        finally:
            if os.path.isfile(user_path):
                os.remove(user_path)
            if created_dir:
                # remove the dir we created (and an empty parent if we made it)
                try:
                    os.rmdir(_USER_DIR)
                    os.rmdir(os.path.dirname(_USER_DIR))
                except OSError:
                    pass
        # confirm cleanup left the loader back to packaged-only state
        presets_after, _ = load_presets("tokamak")
        allok &= _ok("_TESTONLY_" not in presets_after,
                     "user-dir merge: cleaned up (_TESTONLY_ gone)")

    print("\nRESULT:", "ALL PRESETS-IO CHECKS PASS" if allok
          else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
