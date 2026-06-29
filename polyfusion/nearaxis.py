"""First-order near-axis stellarator geometry (Garren-Boozer / Mercier).

The standard *analytic* representation of a stellarator: the magnetic axis is
a closed 3-D Fourier curve

    R(phi) = sum_n rc[n] cos(n*nfp*phi),   Z(phi) = sum_n zs[n] sin(n*nfp*phi)

(stellarator-symmetric), and the flux surfaces near the axis are ellipses
whose shape/orientation follow from the quasisymmetric first-order expansion
of Garren & Boozer (1991) in the form of Landreman, Sengupta & Plunk,
J. Plasma Phys. 85 (2019) 905850103 ("r1 construction").  Given the axis and
the single shaping parameter ``etabar`` (B = B0 [1 + r*etabar*cos(theta)]),
the periodic Riccati-type "sigma equation"

    d(sigma)/dvarphi + (iota + N_hel*nfp) [ etabar^4/kappa^4 + 1 + sigma^2 ]
        - 2 (etabar^2/kappa^2) (-tau) G0/B0 = 0,        sigma(0) = 0,

is solved by Newton iteration with the on-axis rotational transform ``iota``
as the extra unknown (vacuum case: I2 = 0).  kappa/tau are the axis curvature
and torsion, varphi the Boozer toroidal angle, and N_hel the integer counting
poloidal rotations of the Frenet normal (quasi-helical symmetry number).

This reproduces pyQSC (https://github.com/landreman/pyQSC) to machine
precision and is validated against its published reference values in
``tests/test_nearaxis_benchmark.py``.  Unlike the legacy rotating-ellipse
closed form, this representation captures the *axis torsion* contribution to
iota (the classical-stellarator / heliac mechanism) self-consistently with
the elongation contribution, plus the elongation profile e(phi) used for the
surface-area estimate of the 0-D model.

Only numpy is required.  Everything is O(nphi^3) with nphi ~ 61: microseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def spectral_diff_matrix(n: int, period: float) -> np.ndarray:
    """Fourier spectral differentiation matrix for n grid points on [0, period).

    Standard collocation formula (Trefethen, "Spectral Methods in MATLAB"):
    exact for trigonometric polynomials resolvable on the grid.
    """
    D = np.zeros((n, n))
    idx = np.arange(n)
    for off in range(1, n):
        if n % 2 == 1:
            v = 0.5 * (-1.0) ** off / math.sin(off * math.pi / n)
        else:
            v = 0.5 * (-1.0) ** off / math.tan(off * math.pi / n)
        D[idx, (idx + off) % n] = -v
        D[(idx + off) % n, idx] = v
    return D * (2 * math.pi / period)


@dataclass
class SecondOrderResult:
    """O(r^2) Frenet-frame shape coefficients (Landreman-Sengupta-Plunk Part 2).

    The near-axis surface at finite minor radius ``r`` and Boozer poloidal angle
    ``theta`` is, to second order,

        X(theta) = r X1c cos(theta)
                 + r^2 [X20 + X2c cos(2 theta) + X2s sin(2 theta)]
        Y(theta) = r [Y1s sin(theta) + Y1c cos(theta)]
                 + r^2 [Y20 + Y2c cos(2 theta) + Y2s sin(2 theta)]
        Z(theta) = r^2 [Z20 + Z2c cos(2 theta) + Z2s sin(2 theta)]

    with the position P = axis + X n_hat + Y b_hat + Z t_hat in the Frenet
    frame.  The second-order (r^2) terms are what bend the pure first-order
    ellipse into the bean / crescent / triangular cross-sections of real
    stellarators.  All arrays are one field period, ``nphi`` points.

    Restricted to the VACUUM, STELLARATOR-SYMMETRIC case used by this 0-D model:
    I2 = 0, p2 = 0, B2s = 0, sigma0 = 0, sG = spsi = +1, B0 = 1.  ``B2c`` is the
    single second-order field-strength shaping input.
    """

    B2c: float
    X20: np.ndarray
    X2c: np.ndarray
    X2s: np.ndarray
    Y20: np.ndarray
    Y2c: np.ndarray
    Y2s: np.ndarray
    Z20: np.ndarray
    Z2c: np.ndarray
    Z2s: np.ndarray


@dataclass
class NearAxisResult:
    iota: float  # on-axis rotational transform (signed)
    iotaN: float  # iota + helicity*nfp (helical-frame transform)
    helicity: int  # poloidal turns of the Frenet normal per field period
    axis_length: float  # total magnetic-axis length [m]
    mean_elongation: float  # arclength-weighted mean of the surface elongation
    max_elongation: float  # max elongation along the axis
    rms_curvature: float  # rms axis curvature [1/m]
    # per-grid-point arrays (one field period, nphi points):
    phi: np.ndarray
    curvature: np.ndarray
    torsion: np.ndarray
    sigma: np.ndarray
    elongation: np.ndarray
    d_l_d_phi: np.ndarray
    # axis position and Frenet frame in cylindrical (R, phi, Z) components,
    # used to reconstruct first-order surface cross-sections for display:
    R0_arr: np.ndarray  # axis R(phi)
    Z0_arr: np.ndarray  # axis Z(phi)
    normal: np.ndarray  # (3, nphi) Frenet normal
    binormal: np.ndarray  # (3, nphi) Frenet binormal
    tangent: np.ndarray  # (3, nphi) Frenet tangent (for Z2*t reconstruction)
    etabar: float
    # first-order Frenet-frame shape coefficients (X1s = 0 by convention):
    X1c: np.ndarray
    Y1s: np.ndarray
    Y1c: np.ndarray
    d_d_varphi: np.ndarray  # (nphi, nphi) Boozer d/dvarphi spectral matrix
    second_order: "SecondOrderResult | None" = None


def _solve_second_order(
    curvature,
    torsion,
    sigma,
    iotaN,
    etabar,
    X1c,
    Y1s,
    Y1c,
    d_d_varphi,
    abs_G0_over_B0,
    B2c,
) -> SecondOrderResult:
    """O(r^2) near-axis solve, vacuum + stellarator-symmetric case.

    Direct port of pyQSC ``calculate_r2`` (Landreman-Sengupta-Plunk, Part 2)
    specialized to I2 = 0, p2 = 0, B2s = 0, sigma0 = 0, sG = spsi = +1, B0 = 1.
    Those choices kill the ``beta_1s`` (pressure) and all ``I2_over_B0``
    (current) terms, leaving a numpy-only linear solve for X20, Y20.  Validated
    to < 1e-9 against pyQSC in tests/test_nearaxis_r2_benchmark.py.
    """
    nphi = curvature.size
    agob = abs_G0_over_B0  # |G0| / B0  (B0 = 1)
    bogo = 1.0 / agob  # B0 / |G0|
    dd = d_d_varphi

    V1 = X1c * X1c + Y1c * Y1c + Y1s * Y1s
    V2 = 2 * Y1s * Y1c
    V3 = X1c * X1c + Y1c * Y1c - Y1s * Y1s

    factor = -bogo / 8.0
    Z20 = factor * (dd @ V1)
    Z2s = factor * (dd @ V2 - 2 * iotaN * V3)
    Z2c = factor * (dd @ V3 + 2 * iotaN * V2)

    qs = -iotaN * X1c - Y1s * torsion * agob
    qc = dd @ X1c - Y1c * torsion * agob
    rs = dd @ Y1s - iotaN * Y1c
    rc_ = dd @ Y1c + iotaN * Y1s + X1c * torsion * agob

    X2s = (
        bogo
        * (dd @ Z2s - 2 * iotaN * Z2c + bogo * ((qc * qs + rc_ * rs) / 2))
        / curvature
    )
    X2c = (
        bogo
        * (
            dd @ Z2c
            + 2 * iotaN * Z2s
            - bogo
            * (
                -agob * agob * B2c
                + agob * agob * etabar * etabar / 2
                - (qc * qc - qs * qs + rc_ * rc_ - rs * rs) / 4
            )
        )
        / curvature
    )

    # sG = spsi = +1
    Y2s_from_X20 = -curvature * curvature / (etabar * etabar)
    Y2s_inhom = -curvature / 2 + curvature * curvature / (etabar * etabar) * (
        -X2c + X2s * sigma
    )
    Y2c_from_X20 = -curvature * curvature * sigma / (etabar * etabar)
    Y2c_inhom = curvature * curvature / (etabar * etabar) * (X2s + X2c * sigma)

    # f-terms (beta_1s = 0, I2_over_B0 = 0):
    fX0_from_X20 = -4 * agob * (Y2c_from_X20 * Z2s - Y2s_from_X20 * Z2c)
    fX0_from_Y20 = -torsion * agob - 4 * agob * Z2s
    fX0_inhom = curvature * agob * Z20 - 4 * agob * (Y2c_inhom * Z2s - Y2s_inhom * Z2c)

    fXs_from_X20 = -torsion * agob * Y2s_from_X20 - 4 * agob * (Y2c_from_X20 * Z20)
    fXs_from_Y20 = -4 * agob * (-Z2c + Z20)
    fXs_inhom = (
        dd @ X2s
        - 2 * iotaN * X2c
        - torsion * agob * Y2s_inhom
        + curvature * agob * Z2s
        - 4 * agob * (Y2c_inhom * Z20)
    )

    fXc_from_X20 = -torsion * agob * Y2c_from_X20 - 4 * agob * (-Y2s_from_X20 * Z20)
    fXc_from_Y20 = -torsion * agob - 4 * agob * Z2s
    fXc_inhom = (
        dd @ X2c
        + 2 * iotaN * X2s
        - torsion * agob * Y2c_inhom
        + curvature * agob * Z2c
        - 4 * agob * (-Y2s_inhom * Z20)
    )

    fY0_from_X20 = torsion * agob
    fY0_from_Y20 = np.zeros(nphi)
    fY0_inhom = -4 * agob * (X2s * Z2c - X2c * Z2s)

    fYs_from_X20 = -2 * iotaN * Y2c_from_X20 - 4 * agob * Z2c
    fYs_from_Y20 = np.full(nphi, -2 * iotaN)
    fYs_inhom = (
        dd @ Y2s_inhom
        - 2 * iotaN * Y2c_inhom
        + torsion * agob * X2s
        - 4 * agob * (-X2c * Z20)
    )

    fYc_from_X20 = 2 * iotaN * Y2s_from_X20 - 4 * agob * (-Z2s)
    fYc_from_Y20 = np.zeros(nphi)
    fYc_inhom = (
        dd @ Y2c_inhom
        + 2 * iotaN * Y2s_inhom
        + torsion * agob * X2c
        - 4 * agob * (X2s * Z20)
    )

    matrix = np.zeros((2 * nphi, 2 * nphi))
    rhs = np.zeros(2 * nphi)
    for j in range(nphi):
        matrix[j, 0:nphi] = (
            Y1c[j] * dd[j, :] * Y2s_from_X20 - Y1s[j] * dd[j, :] * Y2c_from_X20
        )
        matrix[j, nphi : 2 * nphi] = -2 * Y1s[j] * dd[j, :]
        matrix[j + nphi, 0:nphi] = (
            -X1c[j] * dd[j, :]
            + Y1s[j] * dd[j, :] * Y2s_from_X20
            + Y1c[j] * dd[j, :] * Y2c_from_X20
        )

        matrix[j, j] += (
            X1c[j] * fXs_from_X20[j]
            - Y1s[j] * fY0_from_X20[j]
            + Y1c[j] * fYs_from_X20[j]
            - Y1s[j] * fYc_from_X20[j]
        )
        matrix[j, j + nphi] += (
            X1c[j] * fXs_from_Y20[j]
            - Y1s[j] * fY0_from_Y20[j]
            + Y1c[j] * fYs_from_Y20[j]
            - Y1s[j] * fYc_from_Y20[j]
        )
        matrix[j + nphi, j] += (
            -X1c[j] * fX0_from_X20[j]
            + X1c[j] * fXc_from_X20[j]
            - Y1c[j] * fY0_from_X20[j]
            + Y1s[j] * fYs_from_X20[j]
            + Y1c[j] * fYc_from_X20[j]
        )
        matrix[j + nphi, j + nphi] += (
            -X1c[j] * fX0_from_Y20[j]
            + X1c[j] * fXc_from_Y20[j]
            - Y1c[j] * fY0_from_Y20[j]
            + Y1s[j] * fYs_from_Y20[j]
            + Y1c[j] * fYc_from_Y20[j]
        )

    rhs[0:nphi] = -(
        X1c * fXs_inhom - Y1s * fY0_inhom + Y1c * fYs_inhom - Y1s * fYc_inhom
    )
    rhs[nphi : 2 * nphi] = -(
        -X1c * fX0_inhom
        + X1c * fXc_inhom
        - Y1c * fY0_inhom
        + Y1s * fYs_inhom
        + Y1c * fYc_inhom
    )

    solution = np.linalg.solve(matrix, rhs)
    X20 = solution[0:nphi]
    Y20 = solution[nphi : 2 * nphi]
    Y2s = Y2s_inhom + Y2s_from_X20 * X20
    Y2c = Y2c_inhom + Y2c_from_X20 * X20 + Y20

    return SecondOrderResult(
        B2c=B2c,
        X20=X20,
        X2c=X2c,
        X2s=X2s,
        Y20=Y20,
        Y2c=Y2c,
        Y2s=Y2s,
        Z20=Z20,
        Z2c=Z2c,
        Z2s=Z2s,
    )


def solve_near_axis(
    rc,
    zs,
    nfp: int,
    etabar: float,
    nphi: int = 61,
    newton_tol: float = 1e-12,
    newton_maxit: int = 30,
    order: str = "r1",
    B2c: float = 0.0,
) -> NearAxisResult:
    """Solve the near-axis problem for one configuration.

    Parameters
    ----------
    rc, zs : sequences of axis Fourier amplitudes (cos for R, sin for Z),
             index n multiplies angle n*nfp*phi; rc[0] is the mean major radius.
    nfp    : number of field periods (>= 1).
    etabar : Garren-Boozer shaping parameter [1/m]; |etabar| sets the surface
             elongation (sign is irrelevant here: it enters squared).
    nphi   : grid points per field period (odd; raised to next odd if even).
    order  : "r1" (default) for the first-order ellipse model, or "r2" to also
             compute the second-order bean/crescent shape coefficients
             (vacuum, stellarator-symmetric).
    B2c    : second-order field-strength shaping input (used only for order="r2").
    """
    rc = np.asarray(rc, dtype=float)
    zs = np.asarray(zs, dtype=float)
    nfp = int(nfp)
    if nfp < 1:
        raise ValueError(f"nfp must be >= 1 (got {nfp})")
    if etabar == 0.0:
        raise ValueError("etabar must be nonzero for the near-axis model")
    if rc.size == 0 or rc[0] <= 0:
        raise ValueError("rc[0] (mean major radius) must be > 0")
    if nphi % 2 == 0:
        nphi += 1

    # ---- axis curve and analytic Fourier derivatives on one field period ----
    phi = np.linspace(0.0, 2 * math.pi / nfp, nphi, endpoint=False)
    n_mode = np.arange(rc.size) * nfp  # rc and zs may differ in length
    nz_mode = np.arange(zs.size) * nfp

    def fsum(coef, modes, deriv, kind):
        """d^deriv/dphi^deriv of sum coef[n]*cos/sin(modes[n]*phi)."""
        ang = np.outer(modes, phi)  # (nmodes, nphi)
        if kind == "cos":
            base = [np.cos(ang), -np.sin(ang), -np.cos(ang), np.sin(ang)]
        else:
            base = [np.sin(ang), np.cos(ang), -np.sin(ang), -np.cos(ang)]
        return np.einsum(
            "m,m,mp->p", coef, np.asarray(modes, float) ** deriv, base[deriv % 4]
        )

    R0 = fsum(rc, n_mode, 0, "cos")
    R0p = fsum(rc, n_mode, 1, "cos")
    R0pp = fsum(rc, n_mode, 2, "cos")
    R0ppp = fsum(rc, n_mode, 3, "cos")
    Z0 = fsum(zs, nz_mode, 0, "sin")
    Z0p = fsum(zs, nz_mode, 1, "sin")
    Z0pp = fsum(zs, nz_mode, 2, "sin")
    Z0ppp = fsum(zs, nz_mode, 3, "sin")

    if np.any(R0 <= 0):
        raise ValueError("axis has R <= 0: helical excursion too large for rc[0]")

    # derivatives of position w.r.t. phi, components in the local (R, phi, Z) frame
    d1 = np.stack([R0p, R0, Z0p])
    d2 = np.stack([R0pp - R0, 2 * R0p, Z0pp])
    d3 = np.stack([R0ppp - 3 * R0p, 3 * R0pp - R0, Z0ppp])

    d_l_d_phi = np.sqrt(R0**2 + R0p**2 + Z0p**2)
    d2_l_d_phi2 = (R0 * R0p + R0p * R0pp + Z0p * Z0pp) / d_l_d_phi
    axis_length = float(np.sum(d_l_d_phi)) * (phi[1] - phi[0]) * nfp

    tangent = d1 / d_l_d_phi
    d_tangent_d_l = (d2 - tangent * d2_l_d_phi2) / d_l_d_phi**2
    curvature = np.sqrt(np.sum(d_tangent_d_l**2, axis=0))
    if np.min(curvature) < 1e-12:
        raise ValueError(
            "axis curvature vanishes somewhere: first-order "
            "near-axis model is singular for this axis shape"
        )
    normal = d_tangent_d_l / curvature  # (R, phi, Z) components
    binormal = np.cross(tangent.T, normal.T).T

    cross12 = np.cross(d1.T, d2.T).T
    torsion = np.einsum("ip,ip->p", d1, np.cross(d2.T, d3.T).T) / np.sum(
        cross12**2, axis=0
    )

    # ---- helicity: poloidal winding of the normal per field period ----
    n_R, n_Z = normal[0], normal[2]
    quadrant = np.empty(nphi + 1, dtype=int)
    for j in range(nphi):
        if n_R[j] >= 0:
            quadrant[j] = 1 if n_Z[j] >= 0 else 4
        else:
            quadrant[j] = 2 if n_Z[j] >= 0 else 3
    quadrant[nphi] = quadrant[0]
    counter = 0
    for j in range(nphi):
        if quadrant[j] == 4 and quadrant[j + 1] == 1:
            counter += 1
        elif quadrant[j] == 1 and quadrant[j + 1] == 4:
            counter -= 1
        else:
            counter += quadrant[j + 1] - quadrant[j]
    helicity = counter // 4

    # ---- Boozer angle grid and d/dvarphi (vacuum: varphi ~ arclength) ----
    d_varphi_d_phi = d_l_d_phi * (2 * math.pi / axis_length)
    D = spectral_diff_matrix(nphi, 2 * math.pi / nfp) / d_varphi_d_phi[:, None]

    # ---- sigma equation: Newton on x = [iota, sigma_1 .. sigma_{n-1}] ----
    eta_sq = etabar**2 / curvature**2
    G0_over_B0 = axis_length / (2 * math.pi)
    iotaN_off = helicity * nfp

    def residual(x):
        sigma = x.copy()
        sigma[0] = 0.0
        iota = x[0]
        return (
            D @ sigma
            + (iota + iotaN_off) * (eta_sq**2 + 1 + sigma**2)
            - 2 * eta_sq * (-torsion) * G0_over_B0
        )

    def jacobian(x):
        sigma = x.copy()
        sigma[0] = 0.0
        iota = x[0]
        J = D.copy()
        J[np.arange(nphi), np.arange(nphi)] += (iota + iotaN_off) * 2 * sigma
        J[:, 0] = eta_sq**2 + 1 + sigma**2
        return J

    x = np.zeros(nphi)
    for _ in range(newton_maxit):
        r = residual(x)
        if np.max(np.abs(r)) < newton_tol:
            break
        x = x - np.linalg.solve(jacobian(x), r)
    else:
        raise RuntimeError("sigma-equation Newton iteration did not converge")

    iota = float(x[0])
    iotaN = iota + iotaN_off
    sigma = x.copy()
    sigma[0] = 0.0

    # ---- first-order surface shape: elongation in the plane normal to axis ----
    X1c = etabar / curvature
    Y1s = curvature / etabar
    Y1c = curvature * sigma / etabar
    p = X1c**2 + Y1s**2 + Y1c**2
    q = -X1c * Y1s  # = -1 (area-preserving)
    elongation = (p + np.sqrt(p * p - 4 * q * q)) / (2 * np.abs(q))
    w = d_l_d_phi
    mean_elong = float(np.sum(elongation * w) / np.sum(w))

    second_order = None
    if order == "r2":
        abs_G0_over_B0 = axis_length / (2 * math.pi)  # = |G0|/B0 with B0 = 1
        second_order = _solve_second_order(
            curvature,
            torsion,
            sigma,
            iotaN,
            etabar,
            X1c,
            Y1s,
            Y1c,
            D,
            abs_G0_over_B0,
            B2c,
        )
    elif order != "r1":
        raise ValueError(f"order must be 'r1' or 'r2' (got {order!r})")

    return NearAxisResult(
        iota=iota,
        iotaN=iotaN,
        helicity=int(helicity),
        axis_length=axis_length,
        mean_elongation=mean_elong,
        max_elongation=float(np.max(elongation)),
        rms_curvature=float(np.sqrt(np.sum(curvature**2 * w) / np.sum(w))),
        phi=phi,
        curvature=curvature,
        torsion=torsion,
        sigma=sigma,
        elongation=elongation,
        d_l_d_phi=d_l_d_phi,
        R0_arr=R0,
        Z0_arr=Z0,
        normal=normal,
        binormal=binormal,
        tangent=tangent,
        etabar=etabar,
        X1c=X1c,
        Y1s=Y1s,
        Y1c=Y1c,
        d_d_varphi=D,
        second_order=second_order,
    )
