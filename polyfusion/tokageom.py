"""Tokamak geometry backends (three selectable models).

Model selector ``geom_model``:
  0  legacy  — original closed-form D-shape fits (funsc, verbatim); backward
               compatible default, ``kappa**0.65`` surface fudge internal.
  1  miller  — Miller parametric LCFS, exact axisymmetric revolution integrals.
  2  equilib — Cerfon-Freidberg analytic Grad-Shafranov equilibrium boundary
               (limiter). (Phys. Plasmas 17, 032502 (2010)); reports Shafranov shift.

Boundary metrics for models 1/2 use the exact axisymmetric identities for the
surface of revolution of a closed poloidal contour (R,Z):
    Vp = | pi * oint R^2 dZ |          (Pappus / divergence)
    Sp = oint 2 pi R ds                (ds = sqrt(dR^2 + dZ^2))
the same machinery the stellarator/FRC configs use for their drawn boundaries.
"""

from __future__ import annotations

import math
from functools import lru_cache

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


def _cf_coeffs(eps, kappa, delta, A=_CF_A):
    """Solve the 7x7 linear system for the homogeneous coefficients c_1..c_7 (limiter)."""
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
    ph = (1 - delta * eps, kappa * eps)                 # limiter: smooth high point
    N3 = -kappa / (eps * math.cos(alpha)**2)
    add(2, ph, lambda r: r[0])                          # psi = 0 high point
    add(3, ph, lambda r: r[1])                          # d/dx = 0 (maximum)
    add(6, ph, lambda r: r[3] + N3 * r[2])              # curvature high
    return np.linalg.solve(M, b)


def _cf_psi(x, y, coeffs, A=_CF_A):
    H = _cf_homogeneous(x, y)
    P = _cf_particular(x, y, A)
    return P[0] + float(np.dot(coeffs, H[:, 0]))


def _cf_psi_value(x, y, coeffs, A=_CF_A):
    """psi VALUE at (x, y), vectorized over numpy arrays (value column only).

    Identical to ``_cf_psi`` for scalars but evaluates the 7 basis values + the
    particular solution directly, so a whole ray bundle is one numpy expression
    instead of thousands of (7x5)-array constructions.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    L = np.log(x)
    x2, y2 = x**2, y**2
    c = coeffs
    psi = x2**2 / 8 + A * (0.5 * x2 * L - x2**2 / 8)            # particular value
    psi = psi + c[0] + c[1] * x2 + c[2] * (y2 - x2 * L)
    psi = psi + c[3] * (x2**2 - 4 * x2 * y2)
    psi = psi + c[4] * (2 * y2**2 - 9 * y2 * x2 + 3 * x2**2 * L - 12 * x2 * y2 * L)
    psi = psi + c[5] * (x2**3 - 12 * x2**2 * y2 + 8 * x2 * y2**2)
    psi = psi + c[6] * (8 * y2**3 - 140 * y2**2 * x2 + 75 * y2 * x2**2
                        - 15 * x2**3 * L + 180 * x2**2 * y2 * L - 120 * x2 * y2**2 * L)
    return psi


@lru_cache(maxsize=256)
def cf_boundary(R0, a, kappa, delta, n_theta=360):
    """Cerfon-Freidberg equilibrium LCFS (R, Z) [m] and Shafranov shift [m].

    The boundary is the psi = 0 contour, traced by bisection along rays from the
    normalized geometric centre (x=1, y=0). Returns (R, Z, shaf_shift) where
    shaf_shift = R(magnetic axis) - R0 (outward shift of the flux minimum).
    The bisection runs on the whole ray bundle at once (vectorized).

    Memoized: a POPCON scan over non-geometry axes (Ti0, ni0, ...) keeps the
    boundary fixed, so 1000s of identical calls collapse to one.  The returned
    R/Z arrays are made read-only so the shared cache entry can't be mutated by
    a caller (every consumer treats them read-only — revolution_metrics/offset
    build new arrays).
    """
    if R0 <= 0 or a <= 0 or kappa <= 0:
        raise ValueError(f"R0, a, kappa must be > 0 (got {R0}, {a}, {kappa})")
    if not -1.0 < delta < 1.0:
        raise ValueError(f"triangularity delta must be in (-1, 1) (got {delta})")
    eps = a / R0
    coeffs = _cf_coeffs(eps, kappa, delta)
    xc = 1.0
    th = np.linspace(0.0, 2 * math.pi, int(n_theta), endpoint=False)
    dx = np.cos(th)
    dy = np.sin(th)
    s0 = np.full(th.shape, 1e-4)
    s1 = np.full(th.shape, 1.2 * eps + 0.4)
    inward = dx < 0                       # cap inward rays so x = xc + s*dx > 0 (log domain)
    s1 = np.where(inward, np.minimum(s1, (xc - 1e-3) / np.where(inward, -dx, 1.0)), s1)
    f0 = _cf_psi_value(xc + s0 * dx, s0 * dy, coeffs)
    f1 = _cf_psi_value(xc + s1 * dx, s1 * dy, coeffs)
    bracketed = f0 * f1 <= 0             # rays that cross the boundary
    lo, hi, flo = s0.copy(), s1.copy(), f0.copy()
    for _ in range(60):
        sm = 0.5 * (lo + hi)
        fm = _cf_psi_value(xc + sm * dx, sm * dy, coeffs)
        left = flo * fm <= 0            # root in [lo, sm]
        hi = np.where(left, sm, hi)
        lo = np.where(left, lo, sm)
        flo = np.where(left, flo, fm)
    s = np.where(bracketed, 0.5 * (lo + hi), eps)   # missed rays (X-point notch) -> eps
    R = (xc + s * dx) * R0
    Z = s * dy * R0
    # magnetic axis = flux minimum on the midplane
    xs = np.linspace(1.0 - eps, 1.0 + eps, 401)
    psi_mid = _cf_psi_value(xs, np.zeros_like(xs), coeffs)
    x_axis = xs[int(np.argmin(psi_mid))]
    shaf_shift = (x_axis - 1.0) * R0
    R.flags.writeable = False           # shared cache entry: read-only to callers
    Z.flags.writeable = False
    return R, Z, shaf_shift


def tokamak_shape_outlines(R0, A, kappa, delta, g=0.0, geom_model=1,
                           eq=None, n_theta=181, **_ignored):
    """JSON-able cross-section outline for the UI shape view.

    Returns {lcfs:{R,Z}, wall:{R,Z}, axis:{R,Z}, flux:[{R,Z}...],
             geom_model, shaf_shift}.
    Model 0 (legacy fits have no drawn boundary) returns an empty outline so the
    UI draws its own double-ellipse; model 1 = Miller; model 2 = real EQDSK
    boundary + flux surfaces when ``eq`` given, else CF limiter.
    """
    a = R0 / A
    shaf = 0.0
    gm = int(geom_model)
    flux = []
    if gm == 0:
        return {"lcfs": {"R": [], "Z": []}, "wall": {"R": [], "Z": []},
                "axis": {"R": [], "Z": []}, "flux": [], "geom_model": 0,
                "shaf_shift": 0.0}
    if gm == 2 and isinstance(eq, dict) and eq.get("boundary"):
        R = np.asarray(eq["boundary"]["R"], float)
        Z = np.asarray(eq["boundary"]["Z"], float)
        shaf = float(eq.get("shaf_shift", 0.0))
        ax = eq.get("axis", {"R": [R0 + shaf], "Z": [0.0]})
        flux = eq.get("flux_surfaces", [])
    elif gm == 2:
        R, Z, shaf = cf_boundary(R0, a, kappa, delta, n_theta)
        ax = {"R": [R0 + shaf], "Z": [0.0]}
        flux = miller_flux_surfaces(R0, a, kappa, delta, shaf)
    else:
        R, Z = miller_boundary(R0, a, kappa, delta, n_theta)
        ax = {"R": [R0], "Z": [0.0]}
        flux = miller_flux_surfaces(R0, a, kappa, delta, 0.0)
    Rw, Zw = offset_outward(np.append(R, R[0]), np.append(Z, Z[0]), g)
    return {
        "lcfs": {"R": R.tolist(), "Z": Z.tolist()},
        "wall": {"R": Rw.tolist(), "Z": Zw.tolist()},
        "axis": {"R": list(ax["R"]), "Z": list(ax["Z"])},
        "flux": flux, "geom_model": gm, "shaf_shift": shaf,
    }


# Flux-surface shaping taper, fitted to real ITER-hybrid and MAST equilibria
# (G-EQDSK ray-cast surfaces): the EXCESS elongation (kappa-1) tapers toward the
# axis, the magnetic axis keeping ~0.44 of the edge excess (so for ITER
# kappa_e=1.88 the axis kappa~1.39 -- still prolate, never oblate), the core is
# nearly flat, and the elongation rises near the edge as rho^4.  The excess form
# kappa(rho)=1+(kappa_e-1)*(f+(1-f)*rho^4) keeps kappa>=1 for any kappa_e (a
# multiplicative kappa_e*(...) form would push a near-circular boundary oblate)
# and fits both machines' kappa(rho) to ~1%.  Triangularity vanishes at the axis
# (a point has no triangularity) and rises as rho^2.
_KAPPA_EXCESS_AXIS_FRAC = 0.44


def miller_flux_surfaces(R0, a, kappa, delta, shaf=0.0,
                         levels=(0.2, 0.4, 0.6, 0.8), n_theta=121):
    """Nested Miller flux surfaces with a physically-tapered shaping profile.

    Each surface at flux label ``rho`` is a Miller curve whose elongation
    follows ``kappa(rho)=1+(kappa-1)*(f+(1-f)*rho**4)``
    (f=_KAPPA_EXCESS_AXIS_FRAC: finite, always-prolate axis elongation, flat
    core, edge rise) and whose triangularity follows ``delta(rho)=delta*rho**2``
    (-> 0 at the axis).  Centres shift outward by a parabolic Shafranov term
    ``shaf*(1-rho^2)`` (shaf=0 => concentric).  At rho=1 the surface coincides
    with the Miller LCFS.  This replaces naive self-similar scaling of the
    boundary and is fitted to real ITER/MAST equilibria; mirrors the
    stellarator's rho-built nested surfaces.
    """
    f = _KAPPA_EXCESS_AXIS_FRAC
    t = np.linspace(0.0, 2 * math.pi, int(n_theta))
    out = []
    for rho in levels:
        ar = a * rho
        kr = 1.0 + (kappa - 1.0) * (f + (1.0 - f) * rho**4)
        dr = max(-0.999, min(0.999, delta * rho**2))
        cR = R0 + shaf * (1.0 - rho**2)
        R = cR + ar * np.cos(t + math.asin(dr) * np.sin(t))
        Z = kr * ar * np.sin(t)
        out.append({"R": R.tolist(), "Z": Z.tolist()})
    return out


def legacy_metrics(R0, A, kappa, delta, g):
    """Original closed-form D-shape fits (funsc verbatim) — geom model 0."""
    a = R0 / A
    Ad = R0 / (g + a)
    Vp = (2 * math.pi**2 * kappa * (A - delta) + 16 * math.pi * kappa * delta / 3) * a**3
    Sp = (4 * math.pi**2 * A * kappa**0.65 - 4 * kappa * delta) * a**2
    Sw = (4 * math.pi**2 * Ad * kappa**0.65 - 4 * kappa * delta) * (a + g)**2
    return a, Vp, Sp, Sw


def tokamak_geometry(geom_model, R0, A, kappa, delta, g, eq,
                     Vp_override, Sw_override, n_theta=360):
    """Dispatch geometry by model and return a metrics dict.

    geom_model: 0 legacy fits, 1 Miller boundary, 2 equilibrium.
    For model 2, ``eq`` (parsed G-EQDSK geometry dict from
    ``eqdsk.equilibrium_geometry``) drives Vp/Sp/Sw and R0/a/kappa/delta when
    present; otherwise the CF analytic limiter is used.

    Keys: a, Vp, Sp, Sw, Vp_geom, Sp_geom, Sw_geom, geom_volume_ratio,
    geom_wall_ratio, shaf_shift, geom_model.
    """
    a = R0 / A
    shaf = 0.0
    if geom_model == 0:
        a, Vp_g, Sp_g, Sw_g = legacy_metrics(R0, A, kappa, delta, g)
    elif geom_model == 1:
        R, Z = miller_boundary(R0, a, kappa, delta, n_theta)
        Vp_g, Sp_g = revolution_metrics(R, Z)
        Rw, Zw = offset_outward(R, Z, g)
        _, Sw_g = revolution_metrics(Rw, Zw)
    elif geom_model == 2:
        if isinstance(eq, dict) and eq.get("boundary"):
            R = np.asarray(eq["boundary"]["R"], float)
            Z = np.asarray(eq["boundary"]["Z"], float)
            a = float(eq["a"])
            shaf = float(eq.get("shaf_shift", 0.0))
        else:
            R, Z, shaf = cf_boundary(R0, a, kappa, delta, n_theta)
        Vp_g, Sp_g = revolution_metrics(R, Z)
        Rw, Zw = offset_outward(R, Z, g)
        _, Sw_g = revolution_metrics(Rw, Zw)
    else:
        raise ValueError(f"geom_model must be 0, 1 or 2 (got {geom_model})")
    Vp = Vp_override if Vp_override and Vp_override > 0 else Vp_g
    Sw = Sw_override if Sw_override and Sw_override > 0 else Sw_g
    return {
        "a": a, "Vp": Vp, "Sp": Sp_g, "Sw": Sw,
        "Vp_geom": Vp_g, "Sp_geom": Sp_g, "Sw_geom": Sw_g,
        "geom_volume_ratio": Vp_g / Vp if Vp else float("nan"),
        "geom_wall_ratio": Sw_g / Sw if Sw else float("nan"),
        "shaf_shift": shaf, "geom_model": float(geom_model),
    }
