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
    take(5)            # current, simag(dup), xdum, rmaxis(dup), xdum
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
        "simag": simag, "sibry": sibry, "bcentr": bcentr, "psirz": psirz,
        "rbbbs": np.array(bnd[0::2]), "zbbbs": np.array(bnd[1::2]),
    }
