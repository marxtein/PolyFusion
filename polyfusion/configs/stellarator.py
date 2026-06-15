"""0-D stellarator power balance — v4 (Scheme D: single near-axis geometry).

Tokamak-parity treatment (docs/27 + docs/28, mirroring docs/01 section by
section).  ONE analytic geometry: FIRST-ORDER NEAR-AXIS EXPANSION (Garren-
Boozer / Mercier, in the Landreman-Sengupta-Plunk form used by pyQSC) — the
standard analytic representation of modern optimized stellarators.  ``etabar``
(!= 0, REQUIRED) is the single shaping parameter; the cross-section elongation
is a DERIVED OUTPUT, not an input.  The axis is the 3-D Fourier curve
R = R0 + delta_h cos(N_fp phi), Z = -delta_h sin(N_fp phi) by default, or an
explicit ``rc``/``zs`` Fourier list for a custom axis.  The periodic sigma
equation is solved for the self-consistent on-axis transform, INCLUDING the
axis-torsion contribution and the full elongation profile e(phi) (see
polyfusion/nearaxis.py; validated to machine precision against pyQSC).  Volume
follows Pappus with the flux-conserving section area pi*a^2; surface areas use
the arclength-weighted elongation profile.

(The legacy rotating-ellipse / ``kappa_s`` mode was removed in Scheme D: it
left ``kappa_s`` inert in near-axis mode and ``delta_h`` blind to iota in
legacy mode.  See docs/superpowers/plans/2026-06-14-stellarator-scheme-d.md.)

Measured-machine overrides (D1): a real device that single-harmonic near-axis
cannot represent (W7-X quasi-isodynamic, LHD heliotron) supplies an explicit
``iota`` (> 0) used in the ISS04/Sudo closure, and optionally ``Vp_override`` /
``Sw_override`` (m^3 / m^2, > 0) to anchor the power account to the real
plasma geometry instead of the near-axis estimate.

* PROFILES / REACTIVITY / RADIATION: identical to the tokamak core (already
  L3-verified); confinement closure stays ISS04 + Sudo (docs/23).

Input-domain guards (audit P0): composition, Rw, profile exponents and the
rotational transform are validated here even when the solver is called
directly, so no complex/inf/divide-by-zero "results" can escape.

References: Yamada NF 45 (2005) 1684 (ISS04); Sudo NF 30 (1990); Helander,
Rep. Prog. Phys. 77, 087001 (2014); Garren & Boozer, Phys. Fluids B 3 (1991)
2805; Landreman, Sengupta & Plunk, J. Plasma Phys. 85 (2019) 905850103.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from dataclasses import replace as _dc_replace

from ..constants import QE, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS, twotemp_diagnostics, line_radiation_profile
from ..twotemp import solve_channel_balance
from ..nearaxis import solve_near_axis

_KEV_J = 1e3 * QE
_BETA_SOFT_LIMIT = 0.05   # ~5% soft stellarator beta limit (Mercier; can be exceeded)
_IOTA_MIN = 1e-6          # below this the configuration has no effective transform
_R2_DISPLAY_CAP = 0.5     # shape view: cap r^2 displacement at this fraction of r^1
_N_PHASE_FRAMES = 24      # fine toroidal cuts over one period for the phase slider
# Unified nested-surface display (cosmetic; the rho=1 boundary — the only surface
# the power account integrates — is identical for any fade).  Surfaces nest as
#   S(rho) = axis + rho*round + rho^_SHAPE_FADE * shape
# round = low-order body (m<=1 / r1 ellipse), shape = high-order shaping
# (m>=2 / r2 bean).  Fading the SHAPE one exponent above linear (rho^1.5, not the
# raw near-axis rho^2) keeps the surfaces strictly nested — at rho^2 the W7-X
# phi=0 bean tip let the rho=0.85 surface poke OUTSIDE the boundary — while still
# rounding the bean smoothly toward the axis.  Sampled at uniform rho for even
# visual spacing (sqrt/clustered sampling bunched the outer shells).
_SHAPE_FADE = 1.5
_NEST_RHOS = (0.18, 0.344, 0.508, 0.672, 0.836, 1.0)


def axis_length(R0: float, N_fp: float, delta_h: float, n: int = 720) -> float:
    """Arc length of the (possibly helical) magnetic axis, numerically exact
    for the model R = R0 + delta_h cos(N_fp phi), Z = delta_h sin(N_fp phi)."""
    if delta_h <= 0:
        return 2 * math.pi * R0
    phi = np.linspace(0.0, 2 * math.pi, n)
    R = R0 + delta_h * np.cos(N_fp * phi)
    dR = -delta_h * N_fp * np.sin(N_fp * phi)
    dZ = delta_h * N_fp * np.cos(N_fp * phi)
    return float(np.trapezoid(np.sqrt(dR**2 + R**2 + dZ**2), phi))


def boundary_metrics(boundary_fn, nfp, g=0.0, n_phi=120):
    """Exact toroidal plasma volume and wall surface area of a boundary.

    ``boundary_fn(phi) -> (R[n_theta], Z[n_theta])`` on a uniform theta grid in
    [0, 2pi).  The boundary is ``nfp``-periodic in phi, so we integrate ONE field
    period [0, 2pi/nfp) and multiply by ``nfp`` (validated to <1e-13 against full
    [0,2pi] integration; see tests/test_geometry_integral.py).

    Volume: dV = R dR dZ dphi, with the cross-section integral
    ``∬_S R dR dZ = ∮ (1/2) R^2 dZ`` (Green's theorem).  Surface: the area of the
    WALL boundary (section centroid + (1 + g/max_radius)*(boundary - centroid)),
    ``∬ |∂theta P × ∂phi P| dtheta dphi`` with P = (R cos phi, R sin phi, Z),
    using central differences.  Matches the analytic torus V=2*pi^2*R0*a^2,
    S=4*pi^2*R0*a to 0.004%.
    """
    nfp = int(nfp)
    phs = np.linspace(0.0, 2 * math.pi / nfp, n_phi, endpoint=False)
    dph = (2 * math.pi / nfp) / n_phi
    R0arr, _ = boundary_fn(phs[0])
    n_theta = len(R0arr)
    Rg = np.empty((n_phi, n_theta)); Zg = np.empty((n_phi, n_theta))
    for i, p in enumerate(phs):
        R, Z = boundary_fn(p)
        Rg[i] = R; Zg[i] = Z

    # volume from the plasma boundary (no wall gap)
    V = 0.0
    for i in range(n_phi):
        R, Z = Rg[i], Zg[i]
        V += np.sum(0.5 * R * R * (np.roll(Z, -1) - Z)) * dph
    V = abs(V) * nfp

    # wall boundary = each section offset outward from its centroid by g
    Wr = np.empty_like(Rg); Wz = np.empty_like(Zg)
    for i in range(n_phi):
        R, Z = Rg[i], Zg[i]; cR = R.mean(); cZ = Z.mean()
        sc = 1.0 + g / max(np.hypot(R - cR, Z - cZ).max(), 1e-12)
        Wr[i] = cR + (R - cR) * sc; Wz[i] = cZ + (Z - cZ) * sc

    # wall surface area: |dP/dtheta x dP/dphi| (differences encode dtheta, dphi)
    S = 0.0
    for i in range(n_phi):
        ip = (i + 1) % n_phi; im = (i - 1) % n_phi
        R = Wr[i]; Z = Wz[i]; c = math.cos(phs[i]); s = math.sin(phs[i])
        Pth_R = (np.roll(R, -1) - np.roll(R, 1)) * 0.5
        Pth_Z = (np.roll(Z, -1) - np.roll(Z, 1)) * 0.5
        dRdp = (Wr[ip] - Wr[im]) * 0.5; dZdp = (Wz[ip] - Wz[im]) * 0.5
        ax, ay, az = Pth_R * c, Pth_R * s, Pth_Z
        bx, by, bz = dRdp * c - R * s * dph, dRdp * s + R * c * dph, dZdp
        cx = ay * bz - az * by; cy = az * bx - ax * bz; cz = ax * by - ay * bx
        S += np.sum(np.sqrt(cx * cx + cy * cy + cz * cz))
    S = S * nfp
    return float(V), float(S)


def _shape_boundary_fn(R0, a, shape, n_theta=200):
    """Return ``(boundary_fn, nfp)`` for an explicit Fourier ``shape`` descriptor.

    ``boundary_fn(phi) -> (R[n_theta], Z[n_theta])`` evaluates the DESC
    double-Fourier product basis (same as the display), so the integrated
    volume/area come from the exact boundary the UI draws.
    """
    nfp = int(shape.get("nfp"))
    R_modes = [(int(m), int(n), float(c)) for m, n, c in shape["R"]]
    Z_modes = [(int(m), int(n), float(c)) for m, n, c in shape["Z"]]
    th = np.linspace(0.0, 2 * math.pi, n_theta, endpoint=False)
    cos_m = {}
    for m, _, _ in R_modes + Z_modes:
        if m not in cos_m:
            cos_m[m] = np.cos(m * th) if m >= 0 else np.sin(-m * th)

    def boundary_fn(phi):
        Rh = np.zeros(n_theta); Zh = np.zeros(n_theta)
        for m, n, c in R_modes:
            Bn = math.cos(n * nfp * phi) if n >= 0 else math.sin(-n * nfp * phi)
            Rh += c * cos_m[m] * Bn
        for m, n, c in Z_modes:
            Bn = math.cos(n * nfp * phi) if n >= 0 else math.sin(-n * nfp * phi)
            Zh += c * cos_m[m] * Bn
        return R0 + a * Rh, a * Zh

    return boundary_fn, nfp


def _machine_boundary_outlines(R0, a, N_fp, delta_h, g, shape, n_theta) -> dict:
    """Explicit Fourier boundary for a real machine (SHAPE VIEW), from a public
    equilibrium.

    Single-harmonic near-axis cannot represent W7-X (bean->triangle), LHD (l=2
    heliotron rotating ellipse), HSX (QHS) or CFQS/ESTELL (QA D-shape).  The
    ``shape`` descriptor carries truncated, NORMALIZED boundary Fourier harmonics
    taken from a public DESC equilibrium (R00 removed, divided by the native
    minor radius), evaluated here in DESC's double-Fourier product basis and
    rescaled to this preset's R0 and a = R0/A:

        R(theta, phi) = R0 + a * sum_{m,n} Rmn * A_m(theta) * B_n(phi)
        Z(theta, phi) =      a * sum_{m,n} Zmn * A_m(theta) * B_n(phi)
        A_m(theta) = cos(m theta)      (m >= 0)   or  sin(|m| theta)   (m < 0)
        B_n(phi)   = cos(n*nfp*phi)    (n >= 0)   or  sin(|n|*nfp*phi)  (n < 0)

    Truncated to |m|,|n| <= 2 so it stays a light, recognizable cartoon — NOT a
    full equilibrium.  Purely cosmetic: the 0-D power account uses the measured
    iota/Vp_override/Sw_override, never this outline.  ``delta_h`` is unused here
    (the axis excursion is already encoded in the n!=0 R harmonics).
    """
    nfp = int(shape.get("nfp", round(N_fp)))
    R_modes = [(int(m), int(n), float(c)) for m, n, c in shape["R"]]
    Z_modes = [(int(m), int(n), float(c)) for m, n, c in shape["Z"]]
    th = np.linspace(0.0, 2 * math.pi, n_theta)
    cos_m = {}; sin_m = {}
    for m, _, _ in R_modes + Z_modes:
        if m not in cos_m:
            cos_m[m] = np.cos(m * th) if m >= 0 else np.sin(-m * th)
    rhos = _NEST_RHOS
    cuts = [(0.0, "φ=0"), (0.25, "φ=T/4"), (0.5, "φ=T/2")]

    def _fade(m, rho):
        # m=0 (axis position) fixed; m=1 (ellipse body) scales with size (rho);
        # m>=2 (bean/triangle shaping) fades one order above linear (rho^1.5) so
        # surfaces stay strictly nested and round smoothly toward the axis.  At
        # rho=1 every term is unscaled -> the boundary is unchanged.
        am = abs(m)
        if am == 0:
            return 1.0
        if am == 1:
            return rho
        return rho ** _SHAPE_FADE

    def _shape_RZ(phi, rho=1.0):
        Rh = np.zeros_like(th); Zh = np.zeros_like(th)
        for m, n, c in R_modes:
            Bn = math.cos(n * nfp * phi) if n >= 0 else math.sin(-n * nfp * phi)
            Rh += c * _fade(m, rho) * cos_m[m] * Bn
        for m, n, c in Z_modes:
            Bn = math.cos(n * nfp * phi) if n >= 0 else math.sin(-n * nfp * phi)
            Zh += c * _fade(m, rho) * cos_m[m] * Bn
        return R0 + a * Rh, a * Zh

    def _build_cut(frac, label):
        phi = frac * 2 * math.pi / nfp
        Rb, Zb = _shape_RZ(phi, 1.0)              # boundary at this cut
        surfaces = []
        for rho in rhos:
            Rr, Zr = _shape_RZ(phi, rho)
            surfaces.append({"rho": float(rho), "R": Rr.tolist(), "Z": Zr.tolist()})
        elong = float((Zb.max() - Zb.min()) / (Rb.max() - Rb.min()))
        cR = float(Rb.mean()); cZ = float(Zb.mean())
        scale = 1.0 + g / max(np.hypot(Rb - cR, Zb - cZ).max(), 1e-9)
        return {"label": label, "elong": elong, "frac": float(frac),
                "R": Rb.tolist(), "Z": Zb.tolist(), "surfaces": surfaces,
                "wall": {"R": (cR + (Rb - cR) * scale).tolist(),
                         "Z": (cZ + (Zb - cZ) * scale).tolist()}}

    sections = [_build_cut(frac, label) for frac, label in cuts]
    # fine phi frames over one field period for the phase slider (UI scrub)
    frames = [_build_cut(k / _N_PHASE_FRAMES,
                         "φ=%.2fT" % (k / _N_PHASE_FRAMES))
              for k in range(_N_PHASE_FRAMES)]

    # display axis ring (mean major radius; harmonic excursion is small)
    phi_axis = np.linspace(0.0, 2 * math.pi, 60)
    R00n = next((c for m, n, c in R_modes if m == 0 and n == 0), 0.0)
    axis = {"R": (R0 + a * R00n + 0.0 * phi_axis).tolist(),
            "Z": (0.0 * phi_axis).tolist()}
    return {"mode": "machine-boundary", "metric_mode": "machine-boundary",
            "a": a, "a_disp": a, "g": g, "sections": sections, "frames": frames,
            "axis": axis, "shape_source": shape.get("source", "")}


def _nearaxis_reconstruct(na, nfp, a, th):
    """Shared near-axis cross-section reconstructor (display AND power integral).

    Returns ``rz(phi, rho) -> (R[len(th)], Z[len(th)])``, the SAME analytic
    surface the UI draws and the backend integrates, so frontend shape and
    backend power geometry are one boundary.  Full-size first-order body (radius
    ``rho*a``, correct size) plus a BOUNDED second-order bean/crescent wobble
    (radius ``rho*r2r(phi)``, with ``r2r`` capped so the r^2 displacement never
    exceeds ``_R2_DISPLAY_CAP`` of the r^1 one).  The cap is essential: the raw
    near-axis expansion is only valid for small r, and at the full minor radius a
    the unbounded r^2 surface self-intersects (volume blows up) — the capped
    surface stays a simple, correctly-sized bean.  Periodic in phi over one field
    period; ``rho`` in [0, 1].  If ``na`` has no second order, the pure r^1
    ellipse is returned (``r2r`` then unused).  ``rz.r2r(phi)`` exposes the per-
    phi cap for the display radius.
    """
    period = 2 * math.pi / int(nfp)
    cos_th, sin_th = np.cos(th), np.sin(th)
    cos_2th, sin_2th = np.cos(2 * th), np.sin(2 * th)
    so = na.second_order

    # pre-append the wrap point ONCE per array (periodic interp) so per-phi
    # evaluation is a bare np.interp — the frames/sections rho-loops would
    # otherwise re-append and re-interpolate every call (the slow path).
    xp = np.append(na.phi, na.phi[0] + period)

    def _mk(arr):
        return np.append(arr, arr[0])

    nR, nZ = _mk(na.normal[0]), _mk(na.normal[2])
    bR, bZ = _mk(na.binormal[0]), _mk(na.binormal[2])
    tR, tZ = _mk(na.tangent[0]), _mk(na.tangent[2])
    X1cA, Y1sA, Y1cA = _mk(na.X1c), _mk(na.Y1s), _mk(na.Y1c)
    R0A, Z0A = _mk(na.R0_arr), _mk(na.Z0_arr)
    if so is not None:
        X20A, X2cA, X2sA = _mk(so.X20), _mk(so.X2c), _mk(so.X2s)
        Y20A, Y2cA, Y2sA = _mk(so.Y20), _mk(so.Y2c), _mk(so.Y2s)
        Z20A, Z2cA, Z2sA = _mk(so.Z20), _mk(so.Z2c), _mk(so.Z2s)

    def cut(phi):
        """Precompute everything phi-dependent ONCE, return ``surf(rho)`` and a
        ``.cap`` attribute (the per-phi r^2 display radius)."""
        p = math.fmod(phi, period)

        def iv(fp):
            return float(np.interp(p, xp, fp))

        nh0, nh2 = iv(nR), iv(nZ)
        bh0, bh2 = iv(bR), iv(bZ)
        X1c, Y1s, Y1c = iv(X1cA), iv(Y1sA), iv(Y1cA)
        R0p, Z0p = iv(R0A), iv(Z0A)
        body_R = X1c * cos_th * nh0 + (Y1s * sin_th + Y1c * cos_th) * bh0
        body_Z = X1c * cos_th * nh2 + (Y1s * sin_th + Y1c * cos_th) * bh2
        if so is None:
            def surf(rho):
                return (R0p + rho * a * body_R, Z0p + rho * a * body_Z)
            surf.cap = a
            return surf
        th0, th2 = iv(tR), iv(tZ)
        x2 = iv(X20A) + iv(X2cA) * cos_2th + iv(X2sA) * sin_2th
        y2 = iv(Y20A) + iv(Y2cA) * cos_2th + iv(Y2sA) * sin_2th
        z2 = iv(Z20A) + iv(Z2cA) * cos_2th + iv(Z2sA) * sin_2th
        wob_R = x2 * nh0 + y2 * bh0 + z2 * th0
        wob_Z = x2 * nh2 + y2 * bh2 + z2 * th2
        s1 = float(np.max(np.hypot(body_R, body_Z)))
        s2 = float(np.max(np.hypot(wob_R, wob_Z)))
        cap = min(a, _R2_DISPLAY_CAP * s1 / s2) if s2 > 0 else a

        def surf(rho):
            # body (r1 ellipse) scales with size (rho); bean wobble (r2) is
            # bounded by cap and fades as rho^_SHAPE_FADE for strictly-nested,
            # evenly rounding surfaces (rho=1 -> cap^2, the unchanged boundary).
            wob = (rho ** _SHAPE_FADE) * cap * cap
            R = R0p + rho * a * body_R + wob * wob_R
            Z = Z0p + rho * a * body_Z + wob * wob_Z
            return R, Z
        surf.cap = cap
        return surf

    def rz(phi, rho):
        return cut(phi)(rho)

    rz.cut = cut
    rz.r2r = lambda phi: cut(phi).cap
    return rz


def _nearaxis_boundary_fn(R0, A, N_fp, delta_h=0.0, etabar=0.05,
                          rc=None, zs=None, B2c=0.0, n_theta=200):
    """``(boundary_fn, nfp)`` for a CONCEPT (near-axis, no explicit shape).

    ``boundary_fn(phi) -> (R[n_theta], Z[n_theta])`` is the rho=1 outline of the
    SAME capped-r2 near-axis surface the UI draws (see ``_nearaxis_reconstruct``),
    on a uniform theta grid in [0, 2pi).  Feeding it to ``boundary_metrics`` gives
    the concept plasma volume / wall area by exact integration of the drawn
    boundary — frontend shape == backend power geometry for concepts too.
    """
    a = R0 / A
    nfp_i = int(round(N_fp))
    axis_rc = list(rc) if rc is not None else [R0, delta_h]
    axis_zs = list(zs) if zs is not None else [0.0, -delta_h]
    try:
        na = solve_near_axis(axis_rc, axis_zs, nfp_i, etabar, nphi=121,
                             order="r2", B2c=B2c)
    except (RuntimeError, ValueError):
        na = solve_near_axis(axis_rc, axis_zs, nfp_i, etabar, nphi=121)
    th = np.linspace(0.0, 2 * math.pi, n_theta, endpoint=False)
    rz = _nearaxis_reconstruct(na, nfp_i, a, th)
    return (lambda phi: rz(phi, 1.0)), nfp_i


def section_outlines(R0, A, N_fp, delta_h=0.0, etabar=0.0, g=0.1,
                     rc=None, zs=None, n_theta=121, B2c=0.0, shape=None,
                     **_ignored) -> dict:
    """Flux-surface cross-section outlines for the UI shape view (Scheme D + r2).

    Single near-axis (Garren-Boozer) geometry — the same analytic model the
    0-D power account uses.  Returns ``{"mode", "metric_mode", "a", "g",
    "a_disp", "sections": [...], "axis": {...}}`` with cuts at phi = 0, quarter
    period and half period.  Each section carries:

        ``label``, ``elong``, ``R``/``Z`` (boundary polygon),
        ``surfaces`` (nested near-axis surfaces, last = boundary),
        ``wall`` (``{"R", "Z"}``, the boundary offset outward by the wall gap g).

    SECOND-ORDER (r^2) shape (Landreman-Sengupta-Plunk Part 2): each surface at
    near-axis radius r and Boozer angle theta is

        P(theta) = axis + X n_hat + Y b_hat + Z t_hat,
        X = r X1c cos(theta) + r^2 (X20 + X2c cos2theta + X2s sin2theta),
        Y = r (Y1s sin(theta) + Y1c cos(theta))
            + r^2 (Y20 + Y2c cos2theta + Y2s sin2theta),
        Z = r^2 (Z20 + Z2c cos2theta + Z2s sin2theta),

    projected onto the (R, Z) display plane.  The r^2 terms bend the first-order
    ellipse into the bean / crescent cross-sections of real machines.

    DISPLAY RADIUS: the near-axis expansion is only valid for r small enough
    that the r^2 term stays a sub-dominant correction.  At a reactor minor
    radius the r^2 coefficients can exceed the r^1 ones, so the SHAPE VIEW is
    drawn at a bounded display radius ``a_disp`` <= a chosen so the second-order
    contribution never exceeds ``_R2_DISPLAY_CAP`` of the first-order one (no
    self-intersecting cartoons).  This is purely cosmetic: the 0-D power account
    (volume/area) is unchanged — see ``stellarator_geometry_metrics`` (still
    first-order area-preserving pi a^2).  If the r^2 solve fails, the view falls
    back to the first-order ellipse (``metric_mode = "near-axis"``).

    The magnetic axis is the Fourier curve ``rc``/``zs`` when given, else the
    default helical curve rc=[R0, delta_h], zs=[0, -delta_h].  ``etabar`` (!= 0)
    is REQUIRED.  ``B2c`` is the second-order field-strength shaping input.
    Extra keyword arguments (the full parameter dict) are ignored so the caller
    can pass ``**params`` directly.
    """
    a = R0 / A
    # real-machine presets carry an explicit literature-calibrated boundary that
    # single-harmonic near-axis cannot represent (W7-X bean, LHD rotating
    # ellipse, ...).  Cosmetic only — the power account uses measured overrides.
    if shape is not None:
        return _machine_boundary_outlines(R0, a, N_fp, delta_h, g, shape, n_theta)
    if etabar == 0.0:
        raise ValueError("etabar must be != 0 for section outlines "
                         "(legacy mode removed)")
    th = np.linspace(0.0, 2 * math.pi, n_theta)
    rhos = _NEST_RHOS
    cuts = [(0.0, "φ=0"), (0.25, "φ=T/4"), (0.5, "φ=T/2")]
    sections = []

    def _wall_offset(boundary_R, boundary_Z, center_R, center_Z, gap):
        """Offset a closed boundary polygon outward by ``gap`` along its own
        outward normal.  The polygon is closed (last point == first); we work
        on the unique vertices, build per-vertex normals by averaging the two
        adjacent edge normals, orient each outward relative to the section
        centroid, then re-close.  This is the literal "boundary + g * outward
        normal" offset, so the wall layer shows the same uniform gap the 0-D Sw
        convention applies (+g on the section perimeter)."""
        R = np.asarray(boundary_R, dtype=float)[:-1]
        Z = np.asarray(boundary_Z, dtype=float)[:-1]
        n = R.size
        # tangents from neighbouring vertices (central difference, periodic)
        tR = np.roll(R, -1) - np.roll(R, 1)
        tZ = np.roll(Z, -1) - np.roll(Z, 1)
        # 2-D normal candidates (rotate tangent by -90 deg): (tZ, -tR)
        nR, nZ = tZ.copy(), -tR.copy()
        norm = np.hypot(nR, nZ)
        norm[norm == 0.0] = 1.0
        nR, nZ = nR / norm, nZ / norm
        # orient outward: flip where the normal points toward the centroid
        outR, outZ = R - center_R, Z - center_Z
        flip = (nR * outR + nZ * outZ) < 0.0
        nR[flip] = -nR[flip]
        nZ[flip] = -nZ[flip]
        wR = (R + gap * nR).tolist()
        wZ = (Z + gap * nZ).tolist()
        wR.append(wR[0]); wZ.append(wZ[0])   # re-close
        return {"R": wR, "Z": wZ}

    axis_rc = list(rc) if rc is not None else [R0, delta_h]
    axis_zs = list(zs) if zs is not None else [0.0, -delta_h]
    nfp_i = int(round(N_fp))
    period = 2 * math.pi / nfp_i

    # try the second-order (bean/crescent) shape; fall back to first-order
    na = None
    try:
        na = solve_near_axis(axis_rc, axis_zs, nfp_i, etabar, nphi=121,
                             order="r2", B2c=B2c)
    except (RuntimeError, ValueError):
        na = None
    metric_mode = "near-axis-r2" if na is not None and na.second_order else "near-axis"

    if na is None:
        na = solve_near_axis(axis_rc, axis_zs, nfp_i, etabar, nphi=121)

    cut_j = [int(np.argmin(np.abs(na.phi - frac * period))) for frac, _ in cuts]

    # ONE reconstructor for display AND the power integral (frontend == backend).
    # r2 mode draws the full-size first-order body with a bounded second-order
    # bean wobble (capped so it never self-intersects); r1 mode the plain
    # ellipse.  See _nearaxis_reconstruct.
    rz = _nearaxis_reconstruct(na, nfp_i, a, th)
    if metric_mode == "near-axis-r2":
        a_disp = min(rz.r2r(float(na.phi[j])) for j in cut_j)
    else:
        a_disp = a

    def _cut_surfaces(surf):
        out = []
        for rho in rhos:
            Rr, Zr = surf(rho)
            out.append({"rho": float(rho), "R": Rr.tolist(), "Z": Zr.tolist()})
        return out

    for (frac, label), j in zip(cuts, cut_j):
        surf = rz.cut(float(na.phi[j]))      # ONE precompute, reused per rho
        surfaces = _cut_surfaces(surf)
        Rsec, Zsec = surfaces[-1]["R"], surfaces[-1]["Z"]
        sec = {"label": label, "elong": float(na.elongation[j]),
               "R": Rsec, "Z": Zsec, "surfaces": surfaces}
        sec["wall"] = _wall_offset(Rsec, Zsec, na.R0_arr[j], na.Z0_arr[j], g)
        sections.append(sec)

    # fine phi frames over one field period for the continuous phase slider (UI
    # scrub) — same reconstructor, evaluated at EXACT phi for a smooth sweep, so
    # concepts get the slider too (previously only the machine path had frames).
    xp_ax = np.append(na.phi, na.phi[0] + period)
    R0_ax, Z0_ax = np.append(na.R0_arr, na.R0_arr[0]), np.append(na.Z0_arr, na.Z0_arr[0])

    def _axis_at(phi):
        return (float(np.interp(phi % period, xp_ax, R0_ax)),
                float(np.interp(phi % period, xp_ax, Z0_ax)))

    frames = []
    for k in range(_N_PHASE_FRAMES):
        frac = k / _N_PHASE_FRAMES
        phi = frac * period
        surfs = _cut_surfaces(rz.cut(phi))   # ONE precompute, reused per rho
        Rb, Zb = surfs[-1]["R"], surfs[-1]["Z"]
        aR, aZ = _axis_at(phi)
        elong = float((np.max(Zb) - np.min(Zb)) / (np.max(Rb) - np.min(Rb)))
        frames.append({"label": "φ=%.2fT" % frac, "frac": float(frac),
                       "elong": elong, "R": Rb, "Z": Zb, "surfaces": surfs,
                       "wall": _wall_offset(Rb, Zb, aR, aZ, g)})

    axis = {"R": na.R0_arr[::6].tolist(), "Z": na.Z0_arr[::6].tolist()}
    return {"mode": "near-axis", "metric_mode": metric_mode,
            "a": a, "a_disp": float(a_disp), "g": g,
            "sections": sections, "frames": frames, "axis": axis}


def _ellipse_perimeter(amaj, amin):
    """Ramanujan's approximation (works elementwise on numpy arrays)."""
    h = ((amaj - amin) / (amaj + amin)) ** 2
    return math.pi * (amaj + amin) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h)))


def stellarator_geometry_metrics(R0, A, N_fp, rc, zs, etabar, g=0.1,
                                 n_rho=101) -> dict:
    """Analytic stellarator geometry metrics shared by solver and UI.

    Single near-axis (Garren-Boozer) path (Scheme D): the axis is the custom
    Fourier curve ``rc``/``zs`` and ``etabar`` is the sole shaping knob — the
    transform AND elongation profile come from the self-consistent sigma
    equation.  ``A_flux`` is the first-order flux-section area used by the 0-D
    account.  The R-Z outlines returned by ``section_outlines`` are display
    projections; their projected polygon area is diagnostic, not the volume
    integral.
    """
    a = R0 / A
    A_flux = math.pi * a**2
    na = solve_near_axis(rc, zs, int(round(N_fp)), etabar)
    L_ax = na.axis_length
    iota_geom = abs(na.iota)
    helicity = float(na.helicity)
    kappa_eff = na.mean_elongation
    elong_max = na.max_elongation
    e = na.elongation
    w_axis = na.d_l_d_phi
    per_p = float(np.sum(_ellipse_perimeter(a * np.sqrt(e), a / np.sqrt(e)) * w_axis)
                  / np.sum(w_axis))
    per_w = float(np.sum(_ellipse_perimeter(a * np.sqrt(e) + g, a / np.sqrt(e) + g) * w_axis)
                  / np.sum(w_axis))
    mode = "near-axis"

    rho = np.linspace(0.0, 1.0, n_rho)
    profile_weight = 2.0 * rho
    return {
        "mode": mode,
        "A_flux": A_flux,
        "C_sec_mean": per_p,
        "C_wall_mean": per_w,
        "L_ax": L_ax,
        "Vp_geom": A_flux * L_ax,
        "Sp_geom": per_p * L_ax,
        "Sw_geom": per_w * L_ax,
        "profile_rho": rho.tolist(),
        "profile_weight": profile_weight.tolist(),
        "iota_geom": iota_geom,
        "helicity": helicity,
        "kappa_eff": kappa_eff,
        "elong_max": elong_max,
    }


@dataclass
class StellaratorResult:
    Eth: float        # stored thermal energy [MJ]
    H_ISS04: float    # ISS04 confinement quality factor
    Pheat: float      # net external heating power [MW]
    Pn: float         # neutron power [MW]
    Pfus: float       # fusion power [MW]
    Pwall: float      # first-wall load [MW/m^2]
    Qfus: float       # fusion gain (capped at 1000; see Qfus_raw/ignited)
    Qfus_raw: float   # uncapped Pfus/Pheat (negative => ignited/over-driven)
    ignited: float    # 1 if Pheat <= 0 (alpha heating alone exceeds losses)
    betaT: float      # toroidal beta
    beta_o_limit: float   # betaT / 0.05 (soft-limit margin)
    nbar_o_Sudo: float    # line-avg density / Sudo limit
    Pbrem: float
    Pcycl: float
    Ptrans: float
    Vp: float
    iota: float       # rotational transform actually used in the closure
    iota_geom: float  # transform from the analytic geometry
    helicity: float   # near-axis helicity (0 in rotating-ellipse mode)
    L_ax: float       # magnetic-axis length [m]
    kappa_eff: float  # effective section elongation used for areas
    elong_max: float  # maximum section elongation along the axis
    tau_ISS04: float  # ISS04 predicted confinement time [s]
    Sp: float
    Sw: float
    A_flux: float     # analytic flux-section area [m^2]
    C_sec_mean: float # arclength-weighted plasma section perimeter [m]
    C_wall_mean: float # arclength-weighted wall section perimeter [m]
    Vp_geom: float    # plasma volume used [m^3] (= override for measured machines)
    Sp_geom: float    # geometry-helper plasma surface area [m^2]
    Sw_geom: float    # wall surface area used [m^2] (= override for measured machines)
    geom_is_measured: float  # 1 if Vp & Sw are measured overrides (near-axis
                             # iota_geom/kappa_eff/elong_max are then estimates only)
    ne0: float
    nbar: float
    M: float
    Zeff: float
    N_fp: float       # field periods (echo)
    etabar: float     # near-axis shaping parameter (echo; required != 0)
    P_line: float     # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float      # Stix critical energy of the fast product [keV]
    f_fast_ion: float # fraction of fast-product energy deposited on ions
    tau_eq_ie: float  # ion-electron equilibration time [s]
    P_ei: float       # ion->electron exchange power [MW] (diagnostic)
    Te0: float        # central electron temperature actually used [keV]
    fT_used: float    # Te0/Ti0 actually used (input, or solved when fT=0)
    te_mode: float    # 0 = fT input, 1 = solved, 0.5 = pinned (not converged)
    te_resid: float   # electron-channel residual at solution [MW]
    tauE_used: float  # confinement time actually used [s]
    taue_mode: float  # 0 = tauE input, 1 = solved from ISS04 (tauE=0)
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


_GEOM_CACHE: dict = {}


def _stellarator_geometry(R0, A, N_fp, delta_h, etabar, g, rc, zs, shape,
                          B2c=0.0):
    """Scan-invariant stellarator geometry (near-axis solves + exact boundary
    integral), MEMOIZED.

    A POPCON scan sweeps Ti0/ni0/B0/density/temperature — none of which change
    the geometry — yet ``solve_stellarator`` was recomputing the (expensive)
    near-axis r1+r2 solves and the boundary integral at every one of the
    ~nx*ny grid points (and at every step of the tauE/Te self-consistency
    recursion).  Keyed by the geometry parameters ONLY, this is computed once
    and reused across the whole grid.  If a scan key IS geometric (R0, A, N_fp,
    delta_h, etabar, g, or the axis/shape), the key changes and it recomputes —
    so the cache is always correct, never stale.

    Returns the ``stellarator_geometry_metrics`` dict plus ``Vp_integ`` /
    ``Sw_integ`` (the exact toroidal volume / wall area of the drawn boundary).
    """
    rc_key = tuple(rc) if rc is not None else None
    zs_key = tuple(zs) if zs is not None else None
    shape_key = None if shape is None else (
        int(shape.get("nfp", round(N_fp))),
        tuple(tuple(t) for t in shape["R"]),
        tuple(tuple(t) for t in shape["Z"]))
    key = (R0, A, int(round(N_fp)), delta_h, etabar, g,
           rc_key, zs_key, shape_key, B2c)
    cached = _GEOM_CACHE.get(key)
    if cached is not None:
        return cached

    a = R0 / A
    axis_rc = list(rc) if rc is not None else [R0, delta_h]
    axis_zs = list(zs) if zs is not None else [0.0, -delta_h]
    geom = stellarator_geometry_metrics(R0, A, N_fp, axis_rc, axis_zs, etabar, g)
    if shape is not None:
        bfn, nfp = _shape_boundary_fn(R0, a, shape)
    else:
        bfn, nfp = _nearaxis_boundary_fn(R0, A, N_fp, delta_h, etabar,
                                         rc=rc, zs=zs, B2c=B2c)
    Vp_geom, Sw_geom = boundary_metrics(bfn, nfp, g)
    res = dict(geom)
    res["Vp_integ"] = Vp_geom
    res["Sw_integ"] = Sw_geom
    if len(_GEOM_CACHE) >= 256:        # bound memory; geometry sets are tiny
        _GEOM_CACHE.clear()
    _GEOM_CACHE[key] = res
    return res


def _check_inputs(R0, A, N_fp, delta_h, Sn, ST, fT, B0, tauE,
                  f1, fHe, fimp, Zimp, Rw, g, fsig, etabar):
    """Domain guards (audit P0).  Raise ValueError on unphysical inputs so
    that no complex/inf/NaN value can masquerade as a result."""
    if R0 <= 0 or A <= 0:
        raise ValueError(f"R0 and A must be > 0 (got R0={R0}, A={A})")
    if etabar == 0.0:
        raise ValueError("etabar must be != 0: near-axis shaping is required "
                         "(legacy rotating-ellipse mode was removed in Scheme D)")
    if N_fp < 1:
        raise ValueError(f"N_fp must be >= 1 (got {N_fp})")
    if delta_h < 0 or delta_h >= R0:
        raise ValueError(f"delta_h must satisfy 0 <= delta_h < R0 (got {delta_h})")
    if Sn < 0 or ST < 0:
        raise ValueError(f"profile exponents must be >= 0 (got Sn={Sn}, ST={ST})")
    if fT < 0:
        raise ValueError(f"fT must be >= 0 (got {fT}; 0 = solve Te self-consistently)")
    if B0 <= 0 or tauE < 0:
        raise ValueError(f"B0 must be > 0 and tauE >= 0 "
                         f"(got B0={B0}, tauE={tauE}; tauE=0 = solve from ISS04)")
    if not 0.0 <= f1 <= 1.0:
        raise ValueError(f"f1 must be in [0, 1] (got {f1})")
    if fHe < 0 or fimp < 0 or fHe + fimp >= 1.0:
        raise ValueError(f"need fHe,fimp >= 0 and fHe+fimp < 1 (got {fHe}, {fimp})")
    if Zimp <= 0:
        raise ValueError(f"Zimp must be > 0 (got {Zimp})")
    if not 0.0 <= Rw <= 1.0:
        raise ValueError(f"wall reflectivity Rw must be in [0, 1] (got {Rw})")
    if g < 0:
        raise ValueError(f"wall gap g must be >= 0 (got {g})")
    if fsig < 0:
        raise ValueError(f"fsig must be >= 0 (got {fsig})")


def solve_stellarator(R0, A, N_fp, Sn, ST, ni0, Ti0, fT, fsig, f1,
                      B0, tauE, fHe, fimp, Zimp, Rw, g, icase,
                      delta_h=0.0, iota=None, f_ren=1.0,
                      etabar=0.05, imp_name=None, f_aux_e=0.5,
                      H_fac=1.0, use_tauE=1.0,
                      rc=None, zs=None, Vp_override=0.0,
                      Sw_override=0.0, shape=None) -> StellaratorResult:
    """Evaluate the 0-D stellarator power balance at one operating point.

    Single near-axis (Garren-Boozer) geometry (Scheme D).  ``etabar`` [1/m] is
    the sole shaping knob; elongation is a derived OUTPUT.  The magnetic axis is
    the Fourier curve ``rc``/``zs`` (default rc=[R0, delta_h], zs=[0, -delta_h]
    built from the helical excursion ``delta_h``); iota and the elongation
    profile come from the self-consistent sigma equation.

    ``N_fp`` = number of field periods (5 for W7-X/HELIAS, 4 for HSX, 10 for
    LHD, 2 for CFQS).  ``iota`` (optional, > 0) overrides the geometric
    transform for machines with a measured value; ``Vp_override`` /
    ``Sw_override`` (> 0) override the geometric plasma volume / wall surface
    for measured machines.
    """
    rx = _REACTIONS[icase]
    _check_inputs(R0, A, N_fp, delta_h, Sn, ST, fT, B0, tauE,
                  f1, fHe, fimp, Zimp, Rw, g, fsig, etabar)
    if iota is not None and iota != 0 and iota < 0:
        raise ValueError(f"explicit iota must be > 0 (got {iota})")
    if not 0.0 <= f_aux_e <= 1.0:
        raise ValueError(f"f_aux_e must be in [0, 1] (got {f_aux_e})")
    if H_fac <= 0:
        raise ValueError(f"H_fac must be > 0 (got {H_fac})")
    manual_tauE = bool(use_tauE)
    if manual_tauE and tauE <= 0:
        raise ValueError(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    if not manual_tauE:
        tauE = 0.0

    # tauE = 0: solve the confinement time PREDICTIVELY from ISS04 — find
    # tauE such that H_ISS04 = H_fac (implicit: tau_ISS04 depends on P_L)
    if tauE == 0:
        def _eval_t(t):
            return solve_stellarator(R0, A, N_fp, Sn, ST, ni0, Ti0,
                                     fT, fsig, f1, B0, t, fHe, fimp, Zimp,
                                     Rw, g, icase, delta_h=delta_h, iota=iota,
                                     f_ren=f_ren, etabar=etabar,
                                     imp_name=imp_name, f_aux_e=f_aux_e,
                                     H_fac=H_fac, use_tauE=1.0,
                                     rc=rc, zs=zs, Vp_override=Vp_override,
                                     Sw_override=Sw_override, shape=shape)

        def _resid_t(t, res):
            return H_fac - res.H_ISS04

        t, res, r, conv = solve_channel_balance(_eval_t, _resid_t, 1e-3, 50.0)
        return _dc_replace(res, taue_mode=1.0 if conv else 0.5, tauE_used=t)

    # fT = 0: solve Te self-consistently from the electron-channel balance
    # (docs/30 batch 2; same closure as the tokamak — shared loss structure)
    if fT == 0:
        def _eval(ft):
            return solve_stellarator(R0, A, N_fp, Sn, ST, ni0, Ti0,
                                     ft, fsig, f1, B0, tauE, fHe, fimp, Zimp,
                                     Rw, g, icase, delta_h=delta_h, iota=iota,
                                     f_ren=f_ren, etabar=etabar,
                                     imp_name=imp_name, f_aux_e=f_aux_e,
                                     H_fac=H_fac, use_tauE=1.0,
                                     rc=rc, zs=zs, Vp_override=Vp_override,
                                     Sw_override=Sw_override, shape=shape)

        def _resid(ft, res):
            Eth_e = 1.5 * res.ne0 * ft * Ti0 * 1e3 * QE / (1 + Sn + ST) * res.Vp * 1e-6
            heat = ((1 - res.f_fast_ion) * (res.Pfus - res.Pn) + res.P_ei
                    + f_aux_e * max(res.Pheat, 0.0))
            return heat - (res.Pbrem + res.Pcycl + res.P_line + Eth_e / tauE)

        ft, res, r, conv = solve_channel_balance(_eval, _resid, 0.03, 2.5)
        return _dc_replace(res, te_mode=1.0 if conv else 0.5, te_resid=r,
                           fT_used=ft, Te0=ft * Ti0)

    a = R0 / A
    # scan-invariant geometry (near-axis solves + exact boundary integral),
    # memoized so a POPCON scan / the tauE recursion computes it ONCE.  The
    # boundary volume/wall is ALWAYS the exact integral of the EXACT boundary the
    # UI draws (shape Fourier for machines, near-axis capped-r2 bean for
    # concepts), so frontend shape and backend power geometry are identical.
    geom = _stellarator_geometry(R0, A, N_fp, delta_h, etabar, g, rc, zs, shape)
    L_ax = geom["L_ax"]; iota_geom = geom["iota_geom"]
    helicity = geom["helicity"]; kappa_eff = geom["kappa_eff"]; elong_max = geom["elong_max"]
    Vp_geom = geom["Vp_integ"]; Sw_geom = geom["Sw_integ"]
    Vp = Vp_override if (Vp_override and Vp_override > 0) else Vp_geom
    Sp = geom["Sp_geom"]
    Sw = Sw_override if (Sw_override and Sw_override > 0) else Sw_geom
    # measured machine: Vp AND Sw are measured overrides, so the near-axis
    # diagnostics (iota_geom/kappa_eff/elong_max) are estimates only; flag it.
    # Vp_geom/Sw_geom are reported as the (exact-integral or near-axis) geometry
    # estimate so the user can compare measured vs computed geometry.
    geom_is_measured = 1.0 if (Vp_override and Vp_override > 0
                               and Sw_override and Sw_override > 0) else 0.0
    Vp_geom_report = Vp_geom
    Sw_geom_report = Sw_geom
    iota_used = iota if (iota is not None and iota > 0) else iota_geom
    if iota_used <= _IOTA_MIN:
        raise ValueError("rotational transform is ~0: give an explicit iota "
                         "override (measured machine) or shaping that produces "
                         "transform (etabar + helical/multi-harmonic axis)")

    # --- composition (identical to funsc) ---
    Te0 = fT * Ti0
    d12 = rx["d12"]
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    Z1, Z2, ZHe = rx["Z1"], rx["Z2"], 2
    f12 = 1.0 - fHe - fimp
    n120 = f12 * ni0
    n10, n20 = x1 * n120, x2 * n120
    nHe0, nimp0 = fHe * ni0, fimp * ni0
    ne0 = (n10 * Z1 + n20 * Z2) / (1 + d12) + nHe0 * ZHe + nimp0 * Zimp
    Zeff = ((n10 * Z1**2 + n20 * Z2**2) / (1 + d12)
            + nHe0 * ZHe**2 + nimp0 * Zimp**2) / ne0
    M = (x1 * rx["A1"] + x2 * rx["A2"]) / (1 + d12)

    # --- profiles + reactivity integral (identical to funsc) ---
    x = np.linspace(0.0, 1.0, 101)
    dx = x[1] - x[0]
    Tx = Ti0 * (1 - x**2) ** ST
    sgv = reactivity(Tx, icase)
    Phi = fsig * 2 * float(np.sum((1 - x**2) ** (2 * Sn) * sgv * x * dx))
    Pfus = rx["Y"] / (1 + d12) * n10 * n20 * Phi * Vp * 1e-6
    Pn = Pfus * (1 - rx["fion"])

    # --- radiation (identical to funsc; a = area-equivalent radius) ---
    # NB grouping follows the JS/golden reference (tokamak.py): Zeff multiplies
    # only the leading e-i term; MATLAB groups the relativistic corrections
    # inside Zeff (~1% at Zeff~2) — documented in docs/27.
    Pbrem = (5.34e-37 * ne0**2 * math.sqrt(Te0)
             * (Zeff * (1 / (1 + 2 * Sn + 0.5 * ST))
                + 0.7936 / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2)
                + 1.874 / (1 + 2 * Sn + 2.5 * ST) * (Te0 / MEC2) ** 2
                + 3 / math.sqrt(2) / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2))
             * 1e-6 * Vp)
    neff = ne0 / 1e20 / (1 + Sn)
    Teff = Te0 * float(np.sum((1 - x**2) ** ST)) * dx
    Pcycl = (4.14e-7 * neff**0.5 * Teff**2.5 * B0**2.5 * (1 - Rw)**0.5
             * a**-0.5 * (1 + 2.5 * Teff / 511) * Vp)

    # --- impurity line radiation (Mavrin; opt-in, docs/30 P1-2) ---
    P_line = line_radiation_profile(imp_name, ne0, nimp0, Te0, Sn, ST, Vp, x, dx)

    # --- stored energy, heating, gain (identical structure) ---
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / (1 + Sn + ST) * Vp * 1e-6
    Pth = Eth / tauE
    Pheat = Pcycl + Pbrem + P_line + Pth - rx["fion"] * Pfus
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0

    betaT = 2 * MU0 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / B0**2 / (1 + Sn + ST)
    nbar = ne0 * math.sqrt(math.pi) / 2 * math.gamma(Sn + 1) / math.gamma(Sn + 1.5)
    Pwall = (Pfus + Pheat) / Sw

    # --- stellarator closure: ISS04 + Sudo (verified docs/23) ---
    PL = rx["fion"] * Pfus + Pheat
    if PL > 0:
        tau_ISS04 = (0.134 * f_ren * a**2.28 * R0**0.64 * PL**-0.61
                     * (nbar / 1e19)**0.54 * B0**0.84 * iota_used**0.41)
        H_ISS04 = tauE / tau_ISS04
        n_Sudo = 0.25 * math.sqrt(PL * B0 / (a**2 * R0)) * 1e20
        nbar_o_Sudo = nbar / n_Sudo
    else:
        # losses fully covered without external+alpha heating: outside the
        # ISS04 database domain — flag with NaN rather than inf (audit P0)
        tau_ISS04 = float("nan")
        H_ISS04 = float("nan")
        nbar_o_Sudo = float("nan")

    # --- two-temperature channel diagnostics (docs/30 P1-1) ---
    Ecrit, f_fast, tau_eq, pei = twotemp_diagnostics(
        rx, ni0, Te0, Ti0, n10, n20, nHe0, nimp0, Zimp, M)
    P_ei = pei * Vp / (1 + 2 * Sn + ST) * 1e-6

    return StellaratorResult(
        Eth=Eth, H_ISS04=H_ISS04, Pheat=Pheat, Pn=Pn, Pfus=Pfus, Pwall=Pwall,
        Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        betaT=betaT, beta_o_limit=betaT / _BETA_SOFT_LIMIT,
        nbar_o_Sudo=nbar_o_Sudo, Pbrem=Pbrem, Pcycl=Pcycl, Ptrans=Pth, Vp=Vp,
        iota=iota_used, iota_geom=iota_geom, helicity=helicity, L_ax=L_ax,
        kappa_eff=kappa_eff, elong_max=elong_max, tau_ISS04=tau_ISS04,
        Sp=Sp, Sw=Sw, A_flux=geom["A_flux"], C_sec_mean=geom["C_sec_mean"],
        C_wall_mean=geom["C_wall_mean"], Vp_geom=Vp_geom_report,
        Sp_geom=geom["Sp_geom"], Sw_geom=Sw_geom_report,
        geom_is_measured=geom_is_measured,
        ne0=ne0, nbar=nbar, M=M, Zeff=Zeff,
        N_fp=N_fp, etabar=etabar,
        P_line=P_line, Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq,
        P_ei=P_ei, Te0=Te0, fT_used=fT, te_mode=0.0, te_resid=0.0,
        tauE_used=tauE, taue_mode=0.0, strcase=rx["name"],
    )
