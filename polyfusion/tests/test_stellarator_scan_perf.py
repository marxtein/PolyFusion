"""POPCON scan performance: stellarator geometry is scan-invariant and memoized.

A POPCON sweeps Ti0/ni0/B0/... which do NOT change the geometry, yet the solver
used to recompute the (expensive) near-axis r1+r2 solves and the boundary
integral at every grid point.  Now ``_stellarator_geometry`` memoizes by the
geometry parameters, so a whole Ti0xni0 grid computes the geometry ONCE.  When a
scan key IS geometric the key changes and it correctly recomputes.

(Also caps BLAS threads before numpy — on this Windows numpy the threaded path
is ~1000x slower for medium near-axis matrices; the app does the same.)

Run: python polyfusion/tests/test_stellarator_scan_perf.py
"""

import os
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import get  # noqa: E402
from polyfusion.configs.stellarator import _GEOM_CACHE  # noqa: E402
from polyfusion.scan import scan2d  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    spec = get("stellarator")
    base = dict(spec.presets["HELIAS"])

    # --- Ti0 x ni0 scan: geometry is invariant -> computed ONCE, and fast ---
    _GEOM_CACHE.clear()
    xv = np.linspace(8.0, 30.0, 7)
    yv = np.linspace(0.5e20, 3.0e20, 7)
    t = time.time()
    g = scan2d(spec, base, "Ti0", "ni0", xv, yv)
    dt = time.time() - t
    ok(dt < 15.0,
       f"7x7 HELIAS Ti0xni0 scan is fast ({dt:.2f}s; ~200s without the fix)")
    ok(len(_GEOM_CACHE) == 1,
       f"geometry computed ONCE for the whole scan (cache size {len(_GEOM_CACHE)})")

    Vp = np.asarray(g["Vp"], float)
    vals = Vp[np.isfinite(Vp)]
    ok(vals.size > 0 and np.ptp(vals) < 1e-6 * np.mean(vals),
       "Vp identical across the Ti0xni0 grid (geometry scan-invariant)")
    iota = np.asarray(g["iota"], float)
    iv = iota[np.isfinite(iota)]
    ok(np.ptp(iv) < 1e-9 * abs(np.mean(iv)), "iota identical across the grid")

    # --- cached solve is byte-identical to the first (uncached) solve ---
    _GEOM_CACHE.clear()
    p = {**base, "Ti0": 15.0, "ni0": 2e20}
    r1 = spec.solve(p)                 # cache miss (computes geometry)
    r2 = spec.solve(p)                 # cache hit
    ok(r1["Vp"] == r2["Vp"] and r1["iota"] == r2["iota"] and r1["Sw"] == r2["Sw"],
       "cached solve identical to the first computed solve")

    # --- a GEOMETRIC scan key recomputes geometry per distinct value ---
    _GEOM_CACHE.clear()
    scan2d(spec, base, "etabar", "Ti0",
           np.linspace(0.04, 0.06, 4), np.linspace(10.0, 20.0, 3))
    ok(len(_GEOM_CACHE) == 4,
       f"geometric scan key recomputes geometry per distinct etabar "
       f"(cache size {len(_GEOM_CACHE)}, expected 4)")

    print("\nRESULT:", "SCAN PERF PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
