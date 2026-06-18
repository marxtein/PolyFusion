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
        return [float(line[i:i + 16]) for i in range(0, len(line.rstrip()), 16)
                if line[i:i + 16].strip()]

    need = 20 + 4 * nw + nw * nh + nw
    flat = []
    li = 0
    while len(flat) < need and li < len(rest):
        flat += floats_of(rest[li])
        li += 1
    if len(flat) < need:
        raise ValueError(f"EQDSK truncated: need {need} floats, got {len(flat)}")

    it = iter(flat)
    take = lambda n: [next(it) for _ in range(n)]
    rdim, zdim, rcentr, rleft, zmid = take(5)
    rmaxis, zmaxis, simag, sibry, bcentr = take(5)
    current = take(5)[0]   # current, simag(dup), xdum, rmaxis(dup), xdum
    take(5)            # zmaxis(dup), xdum, sibry(dup), xdum, xdum
    take(nw)           # fpol
    take(nw)           # pres
    take(nw)           # ffprim
    take(nw)           # pprime
    psirz = np.array(take(nw * nh)).reshape(nh, nw)
    take(nw)           # qpsi

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
    bnd = bvals[:2 * nbbbs]
    return {
        "nw": nw, "nh": nh, "rdim": rdim, "zdim": zdim, "rcentr": rcentr,
        "rleft": rleft, "zmid": zmid, "rmaxis": rmaxis, "zmaxis": zmaxis,
        "simag": simag, "sibry": sibry, "bcentr": bcentr, "current": current,
        "psirz": psirz,
        "rbbbs": np.array(bnd[0::2]), "zbbbs": np.array(bnd[1::2]),
    }


_PSI_N_LEVELS = (0.2, 0.4, 0.6, 0.8, 0.9)   # nested flux surfaces for display


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
        return (psirz[j, i] * (1 - tr) * (1 - tz) + psirz[j, i + 1] * tr * (1 - tz)
                + psirz[j + 1, i] * (1 - tr) * tz + psirz[j + 1, i + 1] * tr * tz)

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

    psi, Rg, Zg = _psi_interpolator(g)
    sign = math.copysign(1.0, g["sibry"] - g["simag"])
    s_cap = 0.95 * min(g["rmaxis"] - Rg[0], Rg[-1] - g["rmaxis"],
                       g["zmaxis"] - Zg[0], Zg[-1] - g["zmaxis"]) + a
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
        "R0": R0, "a": a, "kappa": kappa, "delta": delta,
        "shaf_shift": shaf_shift, "Vp": Vp, "Sp": Sp,
        "bt0": abs(float(g["bcentr"])),          # vacuum toroidal field [T]
        "ip": abs(float(g["current"])) / 1e6,    # plasma current [MA]
    }
