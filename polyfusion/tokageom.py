"""Tokamak geometry backends (three selectable models).

Model selector ``geom_model``:
  0  legacy  — original closed-form D-shape fits (funsc, verbatim); backward
               compatible default, ``kappa**0.65`` surface fudge internal.
  1  miller  — Miller parametric LCFS, exact axisymmetric revolution integrals.
  2  equilib — Cerfon-Freidberg analytic Grad-Shafranov equilibrium boundary
               (Phys. Plasmas 17, 032502 (2010)); ``divertor`` selects
               limiter (0) or double-null X-point (1); reports Shafranov shift.

Boundary metrics for models 1/2 use the exact axisymmetric identities for the
surface of revolution of a closed poloidal contour (R,Z):
    Vp = | pi * oint R^2 dZ |          (Pappus / divergence)
    Sp = oint 2 pi R ds                (ds = sqrt(dR^2 + dZ^2))
the same machinery the stellarator/FRC configs use for their drawn boundaries.
"""

from __future__ import annotations

import math

import numpy as np


def revolution_metrics(R, Z):
    """Plasma volume [m^3] and surface area [m^2] of the surface of revolution
    of the closed poloidal contour (R, Z) about the Z axis.

    Inputs may be open (first point != last); the contour is closed internally.
    """
    R = np.asarray(R, dtype=float)
    Z = np.asarray(Z, dtype=float)
    if R.shape != Z.shape or R.ndim != 1 or R.size < 3:
        raise ValueError("R and Z must be 1-D arrays of equal length >= 3")
    if not (math.isclose(R[0], R[-1]) and math.isclose(Z[0], Z[-1])):
        R = np.append(R, R[0])
        Z = np.append(Z, Z[0])
    Rmid = 0.5 * (R[:-1] + R[1:])
    dZ = np.diff(Z)
    Vp = abs(math.pi * float(np.sum(Rmid**2 * dZ)))
    ds = np.hypot(np.diff(R), np.diff(Z))
    Sp = float(np.sum(2 * math.pi * Rmid * ds))
    return Vp, Sp


def offset_outward(R, Z, gap):
    """Offset a closed contour outward by ``gap`` along averaged vertex normals.

    Returns (Rw, Zw). ``gap <= 0`` returns a copy unchanged. Used to build the
    first-wall surface a uniform standoff outside the LCFS.
    """
    R = np.asarray(R, dtype=float)
    Z = np.asarray(Z, dtype=float)
    if R.size != Z.size:
        raise ValueError("R/Z must have equal length")
    if R.size < 3 or gap <= 0:
        return R.copy(), Z.copy()
    closed = bool(np.hypot(R[0] - R[-1], Z[0] - Z[-1]) < 1e-12)
    Rc = R[:-1] if closed else R
    Zc = Z[:-1] if closed else Z
    tR = np.roll(Rc, -1) - np.roll(Rc, 1)
    tZ = np.roll(Zc, -1) - np.roll(Zc, 1)
    nR, nZ = tZ.copy(), -tR.copy()              # outward normal = tangent rotated -90 deg
    norm = np.hypot(nR, nZ)
    norm[norm == 0.0] = 1.0
    Rw = Rc + gap * nR / norm
    Zw = Zc + gap * nZ / norm
    if closed:
        Rw = np.append(Rw, Rw[0])
        Zw = np.append(Zw, Zw[0])
    return Rw, Zw


def miller_boundary(R0, a, kappa, delta, n_theta=360):
    """Miller D-shape LCFS contour (R, Z) [m], open (endpoint excluded).

        R(t) = R0 + a cos(t + arcsin(delta) sin t)
        Z(t) = kappa a sin t
    """
    if R0 <= 0 or a <= 0 or kappa <= 0:
        raise ValueError(f"R0, a, kappa must be > 0 (got {R0}, {a}, {kappa})")
    if not -1.0 < delta < 1.0:
        raise ValueError(f"triangularity delta must be in (-1, 1) (got {delta})")
    t = np.linspace(0.0, 2 * math.pi, int(n_theta), endpoint=False)
    R = R0 + a * np.cos(t + math.asin(delta) * np.sin(t))
    Z = kappa * a * np.sin(t)
    return R, Z
