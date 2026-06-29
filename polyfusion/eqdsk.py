"""G-EQDSK (EFIT/VEQ/CHEASE) equilibrium reader + flux-surface extraction.

Pure numpy. The reader handles the fixed-width ``%16.9E`` layout including
run-together negative exponents (e.g. ``...E-01-0.33...``). Only the fields the
0-D geometry needs are returned; profiles other than psi(R,Z) are skipped.
"""

from __future__ import annotations

import math
import re

import numpy as np


def parse_geqdsk(text: str) -> dict:
    """Parse G-EQDSK text into a dict.

    Keys: nw, nh, rdim, zdim, rcentr, rleft, zmid, rmaxis, zmaxis, simag,
    sibry, bcentr, psirz (nh x nw), rbbbs, zbbbs.

    Raises ValueError on a truncated/malformed file.
    """
    lines = text.splitlines()
    if not lines:
        raise ValueError("empty EQDSK text")
    ints = re.findall(r"\d+", lines[0])
    if len(ints) < 2:
        raise ValueError("EQDSK header missing nw/nh")
    nw, nh = int(ints[-2]), int(ints[-1])
    rest = lines[1:]

    def floats_of(line: str):
        return [
            float(line[i : i + 16])
            for i in range(0, len(line.rstrip()), 16)
            if line[i : i + 16].strip()
        ]

    need = 20 + 4 * nw + nw * nh + nw
    flat = []
    li = 0
    while len(flat) < need and li < len(rest):
        flat += floats_of(rest[li])
        li += 1
    if len(flat) < need:
        raise ValueError(f"EQDSK truncated: need {need} floats, got {len(flat)}")

    it = iter(flat)

    def take(n):
        return [next(it) for _ in range(n)]

    rdim, zdim, rcentr, rleft, zmid = take(5)
    rmaxis, zmaxis, simag, sibry, bcentr = take(5)
    current = take(5)[0]  # current, simag(dup), xdum, rmaxis(dup), xdum
    take(5)  # zmaxis(dup), xdum, sibry(dup), xdum, xdum
    fpol = np.array(take(nw))  # F(psi) = R*B_T on the uniform psi grid (kept for |B|)
    take(nw)  # pres
    take(nw)  # ffprim
    take(nw)  # pprime
    psirz = np.array(take(nw * nh)).reshape(nh, nw)
    take(nw)  # qpsi

    while li < len(rest) and not re.search(r"\d", rest[li]):
        li += 1
    if li >= len(rest):
        raise ValueError("EQDSK missing nbbbs/limitr line")
    nb_lim = re.findall(r"\d+", rest[li])
    if len(nb_lim) < 2:
        raise ValueError("EQDSK malformed nbbbs/limitr line")
    nbbbs, limitr = int(nb_lim[0]), int(nb_lim[1])
    li += 1
    bvals = []
    while len(bvals) < 2 * (nbbbs + limitr) and li < len(rest):
        bvals += floats_of(rest[li])
        li += 1
    if len(bvals) < 2 * nbbbs:
        raise ValueError("EQDSK truncated boundary coordinates")
    bnd = bvals[: 2 * nbbbs]
    return {
        "nw": nw,
        "nh": nh,
        "rdim": rdim,
        "zdim": zdim,
        "rcentr": rcentr,
        "rleft": rleft,
        "zmid": zmid,
        "rmaxis": rmaxis,
        "zmaxis": zmaxis,
        "simag": simag,
        "sibry": sibry,
        "bcentr": bcentr,
        "current": current,
        "psirz": psirz,
        "fpol": fpol,
        "rbbbs": np.array(bnd[0::2]),
        "zbbbs": np.array(bnd[1::2]),
    }


def _psi_to_wbrad_scale(g) -> float:
    """Detect the EQDSK ``psi`` unit convention by matching Ampere's law.

    Standard G-EQDSK stores ``psi`` in Wb/rad, so the poloidal field is
    ``B_p = |grad psi|/R``. Some files (notably ITER samples shipped with
    fixed-boundary codes) store ``psi`` in Wb (poloidal flux including the
    ``2*pi`` toroidal-angle factor), and there ``B_p = |grad psi|/(2*pi*R)``.
    Without correction the Wb-convention files inflate ``|grad psi|`` by
    ``2*pi``, so ``B_p`` and any moment of ``|B|`` it feeds (e.g. cyclotron
    ``<(|B|/B0)^2.5>``) blow up.

    Detect by closing Ampere's law along the LCFS:

        mu0 * |Ip| = oint B_p dl = oint (|grad psi|/R) dl  /  scale

    so ``scale = oint(|grad psi|/R) dl / (mu0 |Ip|)`` — should come out near
    ``1`` (Wb/rad) or near ``2*pi`` (Wb). The ratio is returned directly,
    clamped to ``[0.5, 20]`` so a garbage equilibrium falls back to the
    standard convention rather than crashing downstream code.
    """
    Ip = float(g["current"])
    if Ip == 0.0:
        return 1.0
    psirz = np.asarray(g["psirz"], float)
    nh, nw = psirz.shape
    Rg = np.linspace(g["rleft"], g["rleft"] + g["rdim"], nw)
    Zg = np.linspace(g["zmid"] - g["zdim"] / 2.0, g["zmid"] + g["zdim"] / 2.0, nh)
    dR = Rg[1] - Rg[0]
    dZ = Zg[1] - Zg[0]
    dpsi_dZ, dpsi_dR = np.gradient(psirz, dZ, dR)
    Rb = np.asarray(g["rbbbs"], float)
    Zb = np.asarray(g["zbbbs"], float)
    if Rb.size < 3:
        return 1.0

    def samp(arr, R, Z):
        i = int(np.clip(np.searchsorted(Rg, R) - 1, 0, nw - 2))
        j = int(np.clip(np.searchsorted(Zg, Z) - 1, 0, nh - 2))
        tr = (R - Rg[i]) / (Rg[i + 1] - Rg[i])
        tz = (Z - Zg[j]) / (Zg[j + 1] - Zg[j])
        return (
            arr[j, i] * (1 - tr) * (1 - tz)
            + arr[j, i + 1] * tr * (1 - tz)
            + arr[j + 1, i] * (1 - tr) * tz
            + arr[j + 1, i + 1] * tr * tz
        )

    gR = np.array([samp(dpsi_dR, r, z) for r, z in zip(Rb, Zb)])
    gZ = np.array([samp(dpsi_dZ, r, z) for r, z in zip(Rb, Zb)])
    Bp_grad = np.hypot(gR, gZ) / Rb
    dl = np.hypot(np.diff(Rb, append=Rb[0]), np.diff(Zb, append=Zb[0]))
    line_int = float(np.sum(Bp_grad * dl))
    mu0 = 4 * math.pi * 1e-7
    scale = line_int / (mu0 * abs(Ip))
    if not math.isfinite(scale) or scale <= 0:
        return 1.0
    return float(min(max(scale, 0.5), 20.0))


def _points_in_polygon(R, Z, polyR, polyZ):
    """Vectorized even-odd ray-cast point-in-polygon test.

    ``polyR``/``polyZ`` define a closed polygon (last vertex need not equal the
    first). For each ``(R, Z)`` returns True if inside. Uses horizontal rays to
    +infinity; ties on a vertex are resolved by ``polyZ[i] > Z`` strict
    inequality, the standard W. R. Franklin convention.
    """
    R = np.asarray(R, float)
    Z = np.asarray(Z, float)
    polyR = np.asarray(polyR, float)
    polyZ = np.asarray(polyZ, float)
    n = polyR.size
    inside = np.zeros(R.shape, bool)
    j = n - 1
    for i in range(n):
        zi, zj = polyZ[i], polyZ[j]
        ri, rj = polyR[i], polyR[j]
        cond = (zi > Z) != (zj > Z)
        if zj == zi:
            j = i
            continue
        x_cross = (rj - ri) * (Z - zi) / (zj - zi) + ri
        inside ^= cond & (R < x_cross)
        j = i
    return inside


def cyclotron_b25_from_eqdsk(g: dict) -> float:
    """Volume average ``<(|B|/B0_axis)**2.5>`` from the REAL equilibrium field.

    The non-uniform-field cyclotron correction computed from the actual field
    modulus rather than the Miller ``1/R`` proxy::

        |B| = sqrt(B_T**2 + B_p**2),   B_T = F(psi)/R,   B_p = |grad psi|/R,

    with ``F(psi)`` the G-EQDSK ``fpol`` profile and ``psi(R,Z)`` the ``psirz``
    grid.  ``B0_axis = |F(psi_axis)|/Rmaxis`` is the on-axis toroidal field
    (``B_p = 0`` there), the same reference role ``B0`` plays in the Miller
    proxy ``<(B_T/B0)**2.5>``.

    The integration domain is the interior of the LCFS polygon
    ``rbbbs``/``zbbbs``; in diverted equilibria a plain ``psi in [simag, sibry]``
    test (the previous gate) wrongly admits the private-flux region below the
    X-point and parts of the SOL where ``psi`` falls back into the bound, both
    of which carry spurious ``|grad psi|`` from grid noise near the X-point and
    inflate the moment by factors of 2-10 (ITER: 1.15 → 2.27, CHEASE: 1.66 →
    3.40 before the fix). Cells must be inside the polygon AND have
    ``psi_n in [0, 1]`` (belt-and-suspenders against polygon noise).

    Volume element ``dV = 2*pi*R dR dZ``; the constant ``2*pi dR dZ`` cancels
    in the ratio so only the ``R`` weight is kept.
    """
    psirz = np.asarray(g["psirz"], float)  # (nh, nw), indexed [Z, R]
    fpol = np.asarray(g["fpol"], float)  # F(psi) on uniform psi simag->sibry
    nh, nw = psirz.shape
    Rg = np.linspace(g["rleft"], g["rleft"] + g["rdim"], nw)
    Zg = np.linspace(g["zmid"] - g["zdim"] / 2.0, g["zmid"] + g["zdim"] / 2.0, nh)
    RR = np.broadcast_to(Rg[None, :], (nh, nw))
    ZZ = np.broadcast_to(Zg[:, None], (nh, nw))
    dR = Rg[1] - Rg[0]
    dZ = Zg[1] - Zg[0]
    dpsi_dZ, dpsi_dR = np.gradient(psirz, dZ, dR)
    psi_scale = _psi_to_wbrad_scale(g)
    Bp = np.hypot(dpsi_dR, dpsi_dZ) / (RR * psi_scale)
    simag, sibry = float(g["simag"]), float(g["sibry"])
    dpsi = sibry - simag
    if dpsi == 0.0:
        raise ValueError("degenerate equilibrium: simag == sibry")
    psin = (psirz - simag) / dpsi  # 0 at axis, 1 at boundary
    F = np.interp(np.clip(psin, 0.0, 1.0), np.linspace(0.0, 1.0, nw), fpol)
    Bt = F / RR
    Bmod = np.hypot(Bt, Bp)
    B0_axis = abs(float(fpol[0])) / float(g["rmaxis"])
    if not (B0_axis > 0.0):
        raise ValueError("non-positive on-axis toroidal field")
    Rb = np.asarray(g["rbbbs"], float)
    Zb = np.asarray(g["zbbbs"], float)
    if Rb.size < 3:
        raise ValueError("LCFS polygon needs >= 3 vertices for an interior mask")
    in_poly = _points_in_polygon(RR, ZZ, Rb, Zb)
    inside = in_poly & (psin >= 0.0) & (psin <= 1.0) & np.isfinite(Bmod)
    if not np.any(inside):
        raise ValueError("no grid cells inside the LCFS polygon")
    w = RR[inside]  # dV proportional to R dR dZ
    ratio = (Bmod[inside] / B0_axis) ** 2.5
    return float(np.sum(w * ratio) / np.sum(w))


# nested flux surfaces for display; psi_n ~ rho^2, so these map to roughly
# evenly-spaced volume radii rho ~ 0.15..0.92 — the innermost hugs the magnetic
# axis so the dashed surfaces visibly emanate from it (not a hollow core).
_PSI_N_LEVELS = (0.02, 0.1, 0.25, 0.45, 0.65, 0.85)


def _revolution_metrics(R, Z):
    """Vp, Sp of the surface of revolution of a closed (R, Z) contour."""
    R = np.asarray(R, float)
    Z = np.asarray(Z, float)
    if not (math.isclose(R[0], R[-1]) and math.isclose(Z[0], Z[-1])):
        R = np.append(R, R[0])
        Z = np.append(Z, Z[0])
    Rmid = 0.5 * (R[:-1] + R[1:])
    Vp = abs(math.pi * float(np.sum(Rmid**2 * np.diff(Z))))
    Sp = float(np.sum(2 * math.pi * Rmid * np.hypot(np.diff(R), np.diff(Z))))
    return Vp, Sp


def _psi_interpolator(g):
    """Return a bilinear psi(R, Z) sampler over the EQDSK grid."""
    Rg = np.linspace(g["rleft"], g["rleft"] + g["rdim"], g["nw"])
    Zg = np.linspace(g["zmid"] - g["zdim"] / 2, g["zmid"] + g["zdim"] / 2, g["nh"])
    psirz = g["psirz"]

    def psi(R, Z):
        R = min(max(R, Rg[0]), Rg[-1])
        Z = min(max(Z, Zg[0]), Zg[-1])
        i = min(max(np.searchsorted(Rg, R) - 1, 0), g["nw"] - 2)
        j = min(max(np.searchsorted(Zg, Z) - 1, 0), g["nh"] - 2)
        tr = (R - Rg[i]) / (Rg[i + 1] - Rg[i])
        tz = (Z - Zg[j]) / (Zg[j + 1] - Zg[j])
        return (
            psirz[j, i] * (1 - tr) * (1 - tz)
            + psirz[j, i + 1] * tr * (1 - tz)
            + psirz[j + 1, i] * (1 - tr) * tz
            + psirz[j + 1, i + 1] * tr * tz
        )

    return psi, Rg, Zg


def _flux_surface(psi, rmaxis, zmaxis, target, sign, s_cap, n_theta=120):
    """Ray-cast one psi=target contour from the magnetic axis. Returns (R, Z)."""
    R, Z = [], []
    for ang in np.linspace(0.0, 2 * math.pi, n_theta, endpoint=False):
        dr, dz = math.cos(ang), math.sin(ang)
        s0, s1 = 1e-4, s_cap
        f0 = (psi(rmaxis + s0 * dr, zmaxis + s0 * dz) - target) * sign
        f1 = (psi(rmaxis + s1 * dr, zmaxis + s1 * dz) - target) * sign
        if f0 * f1 > 0:
            continue
        for _ in range(50):
            sm = 0.5 * (s0 + s1)
            fm = (psi(rmaxis + sm * dr, zmaxis + sm * dz) - target) * sign
            if f0 * fm <= 0:
                s1 = sm
            else:
                s0, f0 = sm, fm
        s = 0.5 * (s0 + s1)
        R.append(rmaxis + s * dr)
        Z.append(zmaxis + s * dz)
    return np.array(R), np.array(Z)


def equilibrium_geometry(g: dict) -> dict:
    """Derive JSON-able geometry from a parsed G-EQDSK dict.

    Returns: boundary {R,Z}, axis {R,Z}, flux_surfaces [{R,Z}...],
    R0, a, kappa, delta, shaf_shift, Vp, Sp.
    """
    Rb, Zb = g["rbbbs"], g["zbbbs"]
    if Rb.size < 3:
        raise ValueError("EQDSK has no usable plasma boundary (nbbbs < 3)")
    R0 = 0.5 * (float(Rb.max()) + float(Rb.min()))
    a = 0.5 * (float(Rb.max()) - float(Rb.min()))
    kappa = (float(Zb.max()) - float(Zb.min())) / (2 * a) if a > 0 else 1.0
    R_up = float(Rb[int(np.argmax(Zb))])
    R_lo = float(Rb[int(np.argmin(Zb))])
    delta = (R0 - 0.5 * (R_up + R_lo)) / a if a > 0 else 0.0
    delta = max(-0.999, min(0.999, delta))
    shaf_shift = float(g["rmaxis"]) - R0
    Vp, Sp = _revolution_metrics(Rb, Zb)

    try:
        b25 = cyclotron_b25_from_eqdsk(g)  # real <(|B|/B0)^2.5>
    except Exception:
        b25 = None  # fall back to Miller proxy downstream

    psi, Rg, Zg = _psi_interpolator(g)
    sign = math.copysign(1.0, g["sibry"] - g["simag"])
    s_cap = (
        0.95
        * min(
            g["rmaxis"] - Rg[0],
            Rg[-1] - g["rmaxis"],
            g["zmaxis"] - Zg[0],
            Zg[-1] - g["zmaxis"],
        )
        + a
    )
    flux = []
    for pn in _PSI_N_LEVELS:
        target = g["simag"] + (g["sibry"] - g["simag"]) * pn
        Rs, Zs = _flux_surface(psi, g["rmaxis"], g["zmaxis"], target, sign, s_cap)
        if Rs.size >= 16:
            flux.append({"R": Rs.tolist(), "Z": Zs.tolist()})

    return {
        "boundary": {"R": Rb.tolist(), "Z": Zb.tolist()},
        "axis": {"R": [float(g["rmaxis"])], "Z": [float(g["zmaxis"])]},
        "flux_surfaces": flux,
        "R0": R0,
        "a": a,
        "kappa": kappa,
        "delta": delta,
        "shaf_shift": shaf_shift,
        "Vp": Vp,
        "Sp": Sp,
        "bt0": abs(float(g["bcentr"])),  # file's vacuum toroidal field BCENTR [T]
        "ip": abs(float(g["current"])) / 1e6,  # plasma current [MA]
        "cyclotron_B25": b25,  # real <(|B|/B0)^2.5> (None if uncomputable)
    }
