"""Exact toroidal volume / wall-area integrator for the boundary.

Validates boundary_metrics against the analytic circular torus
(V = 2 pi^2 R0 a^2, S = 4 pi^2 R0 a) and checks the field-period shortcut
(integrate one period x N_fp == integrate the full torus).

Run: python polyfusion/tests/test_geometry_integral.py
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.stellarator import boundary_metrics  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    R0, a = 5.0, 0.5
    th = np.linspace(0.0, 2 * math.pi, 400, endpoint=False)

    def torus(phi):  # circular cross-section, no phi dep
        return R0 + a * np.cos(th), a * np.sin(th)

    Vp, Sw, Sp = boundary_metrics(torus, nfp=1, g=0.0, n_phi=200)
    Vref = 2 * math.pi**2 * R0 * a**2
    Sref = 4 * math.pi**2 * R0 * a
    ok(abs(Vp - Vref) / Vref < 1e-3, f"torus volume {Vp:.5f} ~ {Vref:.5f}")
    ok(abs(Sw - Sref) / Sref < 1e-3, f"torus surface {Sw:.4f} ~ {Sref:.4f}")

    # field-period shortcut: a 5-periodic boundary integrated one period x5
    # equals the full-torus integral
    def helical(phi):
        return R0 + a * np.cos(th) + 0.1 * np.cos(th - 5 * phi), a * np.sin(th)

    Vfull, Sfull, _ = boundary_metrics(helical, nfp=5, g=0.0, n_phi=200)
    # boundary_metrics already uses the one-period x nfp shortcut internally;
    # cross-check it against a brute full-[0,2pi] integration
    phs = np.linspace(0.0, 2 * math.pi, 200, endpoint=False)
    dph = 2 * math.pi / 200
    Vbrute = 0.0
    for p in phs:
        R, Z = helical(p)
        Vbrute += np.sum(0.5 * R * R * (np.roll(Z, -1) - Z)) * dph
    ok(
        abs(Vfull - abs(Vbrute)) / abs(Vbrute) < 1e-6,
        f"one-period x nfp volume {Vfull:.5f} == full-torus {abs(Vbrute):.5f}",
    )

    # wall gap increases the surface monotonically
    _, Sw0, _ = boundary_metrics(torus, nfp=1, g=0.0)
    _, Swg, _ = boundary_metrics(torus, nfp=1, g=0.1)
    ok(Swg > Sw0, f"wall gap raises surface ({Swg:.3f} > {Sw0:.3f})")

    print("\nRESULT:", "GEOMETRY INTEGRAL PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
