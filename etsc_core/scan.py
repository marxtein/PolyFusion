"""Config-agnostic 2-D POPCON scan.

Replaces the ``eval``-based loop of ``scan2d_sc.m``: vary two named parameters
over value vectors and collect every numeric output on the grid, for *any*
configuration described by a :class:`~etsc_core.configs.base.ConfigSpec`.
"""

from __future__ import annotations

import numpy as np

from .configs.base import ConfigSpec


def scan2d(spec: ConfigSpec, base: dict, xkey: str, ykey: str, xvals, yvals) -> dict:
    """Scan ``xkey`` × ``ykey`` over ``xvals`` × ``yvals`` for ``spec``.

    Returns ``{"xx","yy"}`` meshgrids (indexing 'ij') plus one ``(nx,ny)`` array
    per numeric output field of the configuration.
    """
    for k in (xkey, ykey):
        if k not in spec.params:
            raise KeyError(f"{k!r} not a parameter of config {spec.name!r}")
    xvals = np.asarray(xvals, dtype=float)
    yvals = np.asarray(yvals, dtype=float)
    xx, yy = np.meshgrid(xvals, yvals, indexing="ij")
    nx, ny = xx.shape

    grids: dict | None = None
    params = dict(base)
    for i in range(nx):
        for j in range(ny):
            params[xkey] = xx[i, j]
            params[ykey] = yy[i, j]
            out = spec.solve(params)
            if grids is None:
                keys = [k for k, v in out.items() if isinstance(v, (int, float))]
                grids = {k: np.full((nx, ny), np.nan) for k in keys}
            for k in grids:
                grids[k][i, j] = out[k]

    grids["xx"] = xx
    grids["yy"] = yy
    return grids


def best_region_mask(grids: dict, ge: dict | None = None, le: dict | None = None) -> np.ndarray:
    """Boolean operating-window mask.

    ``ge``/``le`` map output field -> threshold (>= / <=).  Criteria whose field
    is absent from ``grids`` are skipped, so the same call works across configs.
    """
    mask = np.ones(grids["xx"].shape, dtype=bool)
    for k, thr in (ge or {}).items():
        if k in grids:
            mask &= np.real(grids[k]) >= thr
    for k, thr in (le or {}).items():
        if k in grids:
            mask &= np.real(grids[k]) <= thr
    return mask
