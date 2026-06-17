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


# --- Cerfon-Freidberg analytic Grad-Shafranov (Phys. Plasmas 17, 032502) ---
# Normalized coordinates x = R/R0, y = Z/R0. psi = psi_p + sum_i c_i psi_i.
_CF_A = -0.155   # FF'/p' weighting (ITER-like reference; LCFS weakly depends on it)


def _cf_homogeneous(x, y):
    """Return (7, 5) array: rows = psi_1..psi_7, cols = [val, d/dx, d/dy, d2/dx2, d2/dy2]."""
    L = np.log(x)
    return np.array([
        [1.0, 0.0, 0.0, 0.0, 0.0],
        [x**2, 2 * x, 0.0, 2.0, 0.0],
        [y**2 - x**2 * L, -2 * x * L - x, 2 * y, -2 * L - 3, 2.0],
        [x**4 - 4 * x**2 * y**2, 4 * x**3 - 8 * x * y**2, -8 * x**2 * y,
         12 * x**2 - 8 * y**2, -8 * x**2],
        [2 * y**4 - 9 * y**2 * x**2 + 3 * x**4 * L - 12 * x**2 * y**2 * L,
         12 * x**3 * L + 3 * x**3 - 24 * x * y**2 * L - 30 * x * y**2,
         -24 * x**2 * y * L - 18 * x**2 * y + 8 * y**3,
         36 * x**2 * L + 21 * x**2 - 24 * y**2 * L - 54 * y**2,
         -24 * x**2 * L - 18 * x**2 + 24 * y**2],
        [x**6 - 12 * x**4 * y**2 + 8 * x**2 * y**4,
         6 * x**5 - 48 * x**3 * y**2 + 16 * x * y**4,
         -24 * x**4 * y + 32 * x**2 * y**3,
         30 * x**4 - 144 * x**2 * y**2 + 16 * y**4,
         -24 * x**4 + 96 * x**2 * y**2],
        [8 * y**6 - 140 * y**4 * x**2 + 75 * y**2 * x**4 - 15 * x**6 * L
         + 180 * x**4 * y**2 * L - 120 * x**2 * y**4 * L,
         -90 * x**5 * L - 15 * x**5 + 720 * x**3 * y**2 * L + 480 * x**3 * y**2
         - 240 * x * y**4 * L - 400 * x * y**4,
         360 * x**4 * y * L + 150 * x**4 * y - 480 * x**2 * y**3 * L
         - 560 * x**2 * y**3 + 48 * y**5,
         -450 * x**4 * L - 165 * x**4 + 2160 * x**2 * y**2 * L
         + 2160 * x**2 * y**2 - 240 * y**4 * L - 640 * y**4,
         360 * x**4 * L + 150 * x**4 - 1440 * x**2 * y**2 * L
         - 1680 * x**2 * y**2 + 240 * y**4],
    ], dtype=float)


def _cf_particular(x, y, A):
    """Particular solution row [val, d/dx, d/dy, d2/dx2, d2/dy2] at (x, y)."""
    L = np.log(x)
    return np.array([
        x**4 / 8 + A * (0.5 * x**2 * L - x**4 / 8),
        x**3 / 2 + A * (x * L + 0.5 * x - 0.5 * x**3),
        0.0,
        1.5 * x**2 + A * (L + 1.5 - 1.5 * x**2),
        0.0,
    ], dtype=float)


def _cf_coeffs(eps, kappa, delta, divertor, A=_CF_A):
    """Solve the 7x7 linear system for the homogeneous coefficients c_1..c_7."""
    alpha = math.asin(delta)
    N1 = -(1 + alpha)**2 / (eps * kappa**2)
    N2 = (1 - alpha)**2 / (eps * kappa**2)
    po = (1 + eps, 0.0)        # outer equatorial
    pin = (1 - eps, 0.0)       # inner equatorial
    M = np.zeros((7, 7))
    b = np.zeros(7)

    def add(i, point, sel):
        """sel(row5) -> scalar; row5 is [val,dx,dy,dxx,dyy]."""
        H = _cf_homogeneous(*point)        # (7,5)
        P = _cf_particular(*point, A)       # (5,)
        M[i, :] = np.array([sel(H[j]) for j in range(7)])
        b[i] = -sel(P)

    add(0, po, lambda r: r[0])                          # psi = 0 outer
    add(1, pin, lambda r: r[0])                         # psi = 0 inner
    add(4, po, lambda r: r[4] + N1 * r[1])              # curvature outer
    add(5, pin, lambda r: r[4] + N2 * r[1])             # curvature inner
    if divertor:                                        # double-null: X-point conditions
        xpt = (1 - 1.1 * delta * eps, 1.1 * kappa * eps)
        add(2, xpt, lambda r: r[0])                     # psi = 0 at X-point
        add(3, xpt, lambda r: r[1])                     # B_Z = 0 (d/dx)
        add(6, xpt, lambda r: r[2])                     # B_R = 0 (d/dy)
    else:                                               # limiter: smooth high point
        ph = (1 - delta * eps, kappa * eps)
        N3 = -kappa / (eps * math.cos(alpha)**2)
        add(2, ph, lambda r: r[0])                      # psi = 0 high point
        add(3, ph, lambda r: r[1])                      # d/dx = 0 (maximum)
        add(6, ph, lambda r: r[3] + N3 * r[2])          # curvature high
    return np.linalg.solve(M, b)


def _cf_psi(x, y, coeffs, A=_CF_A):
    H = _cf_homogeneous(x, y)
    P = _cf_particular(x, y, A)
    return P[0] + float(np.dot(coeffs, H[:, 0]))


def cf_boundary(R0, a, kappa, delta, divertor=0, n_theta=360):
    """Cerfon-Freidberg equilibrium LCFS (R, Z) [m] and Shafranov shift [m].

    The boundary is the psi = 0 contour, traced by bisection along rays from the
    normalized geometric centre (x=1, y=0). Returns (R, Z, shaf_shift) where
    shaf_shift = R(magnetic axis) - R0 (outward shift of the flux minimum).
    """
    if R0 <= 0 or a <= 0 or kappa <= 0:
        raise ValueError(f"R0, a, kappa must be > 0 (got {R0}, {a}, {kappa})")
    if not -1.0 < delta < 1.0:
        raise ValueError(f"triangularity delta must be in (-1, 1) (got {delta})")
    eps = a / R0
    coeffs = _cf_coeffs(eps, kappa, delta, int(divertor))
    xc = 1.0
    th = np.linspace(0.0, 2 * math.pi, int(n_theta), endpoint=False)
    R = np.empty_like(th)
    Z = np.empty_like(th)
    for k, ang in enumerate(th):
        dx, dy = math.cos(ang), math.sin(ang)
        s0, s1 = 1e-4, 1.2 * eps + 0.4
        if dx < 0:                       # cap inward rays so x = xc + s*dx > 0 (log domain)
            s1 = min(s1, (xc - 1e-3) / (-dx))
        f0 = _cf_psi(xc + s0 * dx, s0 * dy, coeffs)
        f1 = _cf_psi(xc + s1 * dx, s1 * dy, coeffs)
        if f0 * f1 > 0:                 # ray misses boundary (X-point notch): clamp to Miller
            s = eps
        else:
            for _ in range(60):
                sm = 0.5 * (s0 + s1)
                fm = _cf_psi(xc + sm * dx, sm * dy, coeffs)
                if f0 * fm <= 0:
                    s1 = sm
                else:
                    s0, f0 = sm, fm
            s = 0.5 * (s0 + s1)
        R[k] = (xc + s * dx) * R0
        Z[k] = s * dy * R0
    # magnetic axis = flux minimum on the midplane
    xs = np.linspace(1.0 - eps, 1.0 + eps, 2001)
    psi_mid = np.array([_cf_psi(xi, 0.0, coeffs) for xi in xs])
    x_axis = xs[int(np.argmin(psi_mid))]
    shaf_shift = (x_axis - 1.0) * R0
    return R, Z, shaf_shift


def tokamak_shape_outlines(R0, A, kappa, delta, g=0.0, geom_model=1,
                           divertor=0, n_theta=181, **_ignored):
    """JSON-able cross-section outline for the UI shape view.

    Returns {lcfs:{R,Z}, wall:{R,Z}, axis:{R,Z}, geom_model, shaf_shift}.
    Model 0 (legacy fits have no drawn boundary) falls back to the Miller
    outline for display only — the power account still uses the model-0 fits.
    """
    a = R0 / A
    shaf = 0.0
    gm = int(geom_model)
    if gm == 2:
        R, Z, shaf = cf_boundary(R0, a, kappa, delta, int(divertor), n_theta)
    else:
        R, Z = miller_boundary(R0, a, kappa, delta, n_theta)
    Rw, Zw = offset_outward(np.append(R, R[0]), np.append(Z, Z[0]), g)
    return {
        "lcfs": {"R": R.tolist(), "Z": Z.tolist()},
        "wall": {"R": Rw.tolist(), "Z": Zw.tolist()},
        "axis": {"R": [R0 + shaf], "Z": [0.0]},
        "geom_model": gm, "shaf_shift": shaf,
    }


def legacy_metrics(R0, A, kappa, delta, g):
    """Original closed-form D-shape fits (funsc verbatim) — geom model 0."""
    a = R0 / A
    Ad = R0 / (g + a)
    Vp = (2 * math.pi**2 * kappa * (A - delta) + 16 * math.pi * kappa * delta / 3) * a**3
    Sp = (4 * math.pi**2 * A * kappa**0.65 - 4 * kappa * delta) * a**2
    Sw = (4 * math.pi**2 * Ad * kappa**0.65 - 4 * kappa * delta) * (a + g)**2
    return a, Vp, Sp, Sw


def tokamak_geometry(geom_model, R0, A, kappa, delta, g, divertor,
                     Vp_override, Sw_override, n_theta=360):
    """Dispatch geometry by model and return a metrics dict.

    Keys: a, Vp, Sp, Sw (used by the power account) plus diagnostics
    Vp_geom, Sp_geom, Sw_geom (raw integrated/fit values before any override),
    geom_volume_ratio, geom_wall_ratio (Vp_geom/Vp, Sw_geom/Sw),
    shaf_shift (CF only; 0 otherwise), geom_model, divertor.
    """
    a = R0 / A
    shaf = 0.0
    if geom_model == 0:
        a, Vp_g, Sp_g, Sw_g = legacy_metrics(R0, A, kappa, delta, g)
    else:
        if geom_model == 1:
            R, Z = miller_boundary(R0, a, kappa, delta, n_theta)
        elif geom_model == 2:
            R, Z, shaf = cf_boundary(R0, a, kappa, delta, divertor, n_theta)
        else:
            raise ValueError(f"geom_model must be 0, 1 or 2 (got {geom_model})")
        Vp_g, Sp_g = revolution_metrics(R, Z)
        Rw, Zw = offset_outward(R, Z, g)
        _, Sw_g = revolution_metrics(Rw, Zw)
    Vp = Vp_override if Vp_override and Vp_override > 0 else Vp_g
    Sw = Sw_override if Sw_override and Sw_override > 0 else Sw_g
    return {
        "a": a, "Vp": Vp, "Sp": Sp_g, "Sw": Sw,
        "Vp_geom": Vp_g, "Sp_geom": Sp_g, "Sw_geom": Sw_g,
        "geom_volume_ratio": Vp_g / Vp if Vp else float("nan"),
        "geom_wall_ratio": Sw_g / Sw if Sw else float("nan"),
        "shaf_shift": shaf,
        "geom_model": float(geom_model), "divertor": float(divertor),
    }
