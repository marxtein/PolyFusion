"""Machine shape view exposes fine toroidal frames for the phase slider.

Run: python polyfusion/tests/test_stellarator_phase_frames.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.presets_io import load_presets  # noqa: E402
from polyfusion.configs.stellarator import section_outlines  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def _check_frames(name):
    """Both machines AND concepts must expose well-formed, nested phase frames
    so the continuous phase slider works on every preset (concepts used to have
    no frames -> no slider)."""
    sh = section_outlines(**load_presets("stellarator")[0][name])
    ok("frames" in sh and sh["frames"], f"{name}: shape has phase frames")
    frames = sh["frames"]
    ok(len(frames) >= 12, f"{name}: enough frames for a smooth slider ({len(frames)})")
    for fr in frames[:2]:
        for k in ("frac", "R", "Z", "surfaces", "wall"):
            ok(k in fr, f"{name}: frame has key '{k}'")
    fracs = [fr["frac"] for fr in frames]
    ok(
        all(fracs[i] < fracs[i + 1] for i in range(len(fracs) - 1)),
        f"{name}: frame fracs increase monotonically over the period",
    )
    f0, fm = frames[0], frames[len(frames) // 2]
    d = float(np.max(np.abs(np.array(f0["R"]) - np.array(fm["R"]))))
    ok(d > 0.02 * sh["a"], f"{name}: frames vary with phi (max dR {d:.3f})")
    # frames must nest strictly too (the slider draws them)
    from matplotlib.path import Path

    for fr in (frames[0], frames[len(frames) // 3], frames[len(frames) // 2]):
        s = fr["surfaces"]
        for i in range(len(s) - 1):
            poly = Path(np.column_stack([s[i + 1]["R"], s[i + 1]["Z"]]))
            out = int(
                (~poly.contains_points(np.column_stack([s[i]["R"], s[i]["Z"]]))).sum()
            )
            ok(out == 0, f"{name}: frame phi={fr['frac']:.2f} surface {i} nested")


def main():
    for name in ("W7-X", "LHD", "HSX", "CFQS", "HELIAS", "NAE-QA"):
        _check_frames(name)

    print("\nRESULT:", "PHASE FRAMES PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
