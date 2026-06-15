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


def main():
    presets, _ = load_presets("stellarator")
    sh = section_outlines(**presets["W7-X"])
    ok("frames" in sh, "machine shape has phase frames")
    frames = sh["frames"]
    ok(len(frames) >= 12, f"enough frames for a smooth slider ({len(frames)})")
    for fr in frames[:3]:
        for k in ("frac", "R", "Z", "surfaces", "wall"):
            ok(k in fr, f"frame has key '{k}'")
    fracs = [fr["frac"] for fr in frames]
    ok(all(fracs[i] < fracs[i+1] for i in range(len(fracs)-1)),
       "frame fracs increase monotonically over the period")
    # frames at different phi are genuinely different cross-sections
    f0, fm = frames[0], frames[len(frames)//2]
    d = float(np.max(np.abs(np.array(f0["R"]) - np.array(fm["R"]))))
    ok(d > 0.02 * sh["a"], f"frames vary with phi (max dR {d:.3f})")

    print("\nRESULT:", "PHASE FRAMES PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
