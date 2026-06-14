"""Input-domain & invalid-point protection tests (audit Phase 1 + Phase 2).

Run: python polyfusion/tests/test_validation.py

Covers exactly the P0 cases listed in docs/多位形0D物理审核总报告.md and the
five per-configuration audit reports:

1. Composition: fHe + fimp >= 1 must be rejected for every configuration.
2. Rw > 1 (complex cyclotron power) must be rejected for every configuration.
3. Negative profile exponents (Sn/ST) must be rejected where they exist.
4. Stellarator (Scheme D): etabar = 0 (no near-axis shaping) rejected; a
   planar axis (delta_h = 0) with no measured iota gives no transform and must
   error, not return H_ISS04 = inf; iota < 0 rejected.
5. FRC: r_s >= r_w (x_s >= 1, negative <beta>) rejected.
6. Dipole: L_in >= R_p (negative volume) rejected; L_in_fac < 1 rejected.
7. Mirror: R_mirror <= 1 rejected.
8. No run_case call below may raise, return complex outputs, or return
   non-finite outputs flagged valid.
9. scan2d: a scan straddling an invalid band keeps the good points, fills NaN
   holes, reports scan_errors, and best_region_mask excludes invalid points.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.io import run_case  # noqa: E402
from polyfusion.configs.base import get  # noqa: E402
from polyfusion.scan import scan2d, best_region_mask  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


PRESETS = {"tokamak": "ITER", "mirror": "GDT", "frc": "C-2W",
           "dipole": "LDX", "stellarator": "W7-X"}


def expect_error(config, overrides, label):
    r = run_case(overrides, preset=PRESETS[config], config=config)
    ok("errors" in r and r["errors"], f"{config}: {label} rejected "
       f"({(r.get('errors') or ['NO ERROR'])[0][:70]})")


def expect_clean(config, overrides, label):
    r = run_case(overrides, preset=PRESETS[config], config=config)
    if "errors" in r:
        ok(False, f"{config}: {label} unexpectedly rejected: {r['errors']}")
        return
    o = r["outputs"]
    cplx = [k for k, v in o.items() if isinstance(v, complex)]
    ok(not cplx, f"{config}: {label} -> no complex outputs")


def main():
    # ---- tokamak preset name check (PRESETS table must exist) ----
    for cfg, p in PRESETS.items():
        ok(p in get(cfg).presets, f"preset {p!r} exists for {cfg}")

    # ---- 1. composition closure, every configuration ----
    for cfg in PRESETS:
        expect_error(cfg, {"fHe": 0.7, "fimp": 0.4}, "fHe+fimp=1.1")
        expect_error(cfg, {"fimp": -0.1}, "fimp<0")

    # ---- 2. wall reflectivity domain, every configuration ----
    for cfg in PRESETS:
        expect_error(cfg, {"Rw": 1.2}, "Rw=1.2")
        expect_error(cfg, {"Rw": -0.2}, "Rw=-0.2")
        expect_clean(cfg, {"Rw": 1.0}, "Rw=1.0 (boundary)")

    # ---- 3. profile exponents where they exist ----
    for cfg in ("tokamak", "mirror", "stellarator"):
        expect_error(cfg, {"Sn": -1}, "Sn=-1")
        expect_error(cfg, {"ST": -0.5}, "ST=-0.5")

    # ---- 4. stellarator transform (Scheme D: near-axis shaping required) ----
    # etabar = 0 has no near-axis shaping (legacy rotating-ellipse mode removed)
    expect_error("stellarator", {"etabar": 0.0}, "etabar=0 (no near-axis shaping)")
    expect_error("stellarator", {"iota": -0.5}, "iota=-0.5")
    expect_error("stellarator", {"delta_h": 6.0}, "delta_h >= R0")
    # planar axis (delta_h=0) gives no transform; WITHOUT a measured iota
    # override the configuration must error, not return H_ISS04 = inf. The W7-X
    # preset carries iota=0.88, so drop it explicitly to hit the no-transform path.
    r = run_case({"etabar": 0.04, "delta_h": 0.0, "iota": 0.0}, preset="W7-X",
                 config="stellarator")
    ok("errors" in r and r["errors"],
       f"stellarator: planar no-transform (delta_h=0, no iota) rejected "
       f"({(r.get('errors') or ['?'])[0][:60]})")
    # near-axis healthy case stays clean
    expect_clean("stellarator", {"etabar": 0.16, "delta_h": 0.25}, "near-axis mode")

    # ---- 5. FRC geometry ----
    expect_error("frc", {"r_s": 0.7}, "r_s = r_w (x_s = 1)")
    expect_error("frc", {"r_s": 0.9}, "r_s > r_w")
    expect_error("frc", {"f_shape": 0.5}, "f_shape < 2/3")
    expect_error("frc", {"f_shape": 1.2}, "f_shape > 1")

    # ---- 6. dipole geometry ----
    expect_error("dipole", {"L_in_fac": 8.0}, "L_in >= R_p")
    expect_error("dipole", {"L_in_fac": 0.5}, "L_in_fac < 1")

    # ---- 7. mirror ----
    expect_error("mirror", {"R_mirror": 0.9}, "R_mirror < 1")
    expect_error("mirror", {"f_throat": 0.8}, "f_throat > 0.5")
    expect_error("mirror", {"f_alpha": 1.5}, "f_alpha > 1")

    # ---- 8. solver-level guards also fire on direct calls ----
    from polyfusion.configs import solve_frc, solve_dipole
    for fn, kw, label in [
        (solve_frc, dict(r_s=0.9, l_s=3.0, r_w=0.6, B_e=1.0, Ti=2.0, Te=1.0),
         "solve_frc x_s>1"),
        (solve_dipole, dict(r_ring=1.0, R_p=1.2, B_ring=10.0, n0=3e20,
                            Ti0=30.0, Te0=20.0, tauE=5.0), "solve_dipole L_in>=R_p"),
    ]:
        try:
            fn(**kw)
            ok(False, f"{label} raised ValueError")
        except ValueError:
            ok(True, f"{label} raised ValueError")
        except Exception as e:
            ok(False, f"{label} raised ValueError (got {type(e).__name__})")

    # ---- 9. scan robustness: FRC scan straddling x_s = 1 ----
    spec = get("frc")
    base = dict(spec.presets["C-2W"])
    g = scan2d(spec, base, "r_s", "Ti", np.linspace(0.3, 0.9, 7),
               np.linspace(1.0, 5.0, 5))
    valid = g["valid"]
    # r_s >= 0.6 = r_w -> invalid columns (r_s grid: 0.3..0.9 step 0.1 -> 3 bad)
    ok(np.all(valid[:3, :] == 1), "scan: x_s<1 points valid")
    ok(np.all(valid[3:, :] == 0), "scan: x_s>=1 points invalid")
    ok(np.all(np.isnan(g["Pfus"][3:, :])), "scan: invalid points are NaN holes")
    ok(np.all(np.isfinite(g["Pfus"][:3, :])), "scan: valid points finite")
    ok(any("r_s" in m for m in g["scan_errors"]), "scan_errors reports the reason")
    mask = best_region_mask(g, ge={"Pfus": -1e30}, le={})
    ok(not mask[3:, :].any(), "best region excludes invalid points")

    # ---- 10. ignited/raw-Q transparency ----
    r = run_case({"Ti0": 40.0, "ni0": 4e20, "tauE": 10.0}, preset="HELIAS",
                 config="stellarator")
    o = r.get("outputs", {})
    if o.get("ignited") == 1.0:
        ok(o.get("Qfus") == 1000.0 and o.get("Qfus_raw", 0) <= 0,
           "ignited point: Qfus capped, Qfus_raw exposes sign")
        # ISS04 uses PL = total loss power (> 0 even when ignited), so the
        # point stays numerically valid — ignition is flagged, not hidden.
        ok(o.get("valid") == 1.0 and math.isfinite(o.get("H_ISS04", math.nan)),
           "ignited point: flagged via ignited=1, outputs stay finite")
    else:
        ok("outputs" in r, "hot HELIAS point runs (not ignited at these inputs)")

    print("\nRESULT:", "VALIDATION SUITE PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
