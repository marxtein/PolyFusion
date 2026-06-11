"""Config-agnostic 2-D POPCON scan.

Replaces the ``eval``-based loop of ``scan2d_sc.m``: vary two named parameters
over value vectors and collect every numeric output on the grid, for *any*
configuration described by a :class:`~polyfusion.configs.base.ConfigSpec`.

Robustness (audit Phase 2): every grid point is validated and solved
independently — an unphysical or crashing point fills NaN in all output grids
instead of aborting the whole scan, the ``valid`` grid marks usable points
(input-valid AND finite outputs), and :func:`best_region_mask` automatically
excludes invalid/non-finite points so they can never appear as part of a
feasible operating window.
"""

from __future__ import annotations

import numpy as np

from .configs.base import ConfigSpec


def scan2d(spec: ConfigSpec, base: dict, xkey: str, ykey: str, xvals, yvals) -> dict:
    """Scan ``xkey`` × ``ykey`` over ``xvals`` × ``yvals`` for ``spec``.

    Returns ``{"xx","yy"}`` meshgrids (indexing 'ij') plus one ``(nx,ny)`` array
    per numeric output field of the configuration, a ``valid`` (nx,ny) array
    (1 = physical point, 0 = invalid input / failed solve / non-finite output)
    and ``scan_errors`` — a {message: count} summary of why points dropped out.
    """
    for k in (xkey, ykey):
        if k not in spec.params:
            raise KeyError(f"{k!r} not a parameter of config {spec.name!r}")
    xvals = np.asarray(xvals, dtype=float)
    yvals = np.asarray(yvals, dtype=float)
    xx, yy = np.meshgrid(xvals, yvals, indexing="ij")
    nx, ny = xx.shape

    outs: list[list[dict | None]] = [[None] * ny for _ in range(nx)]
    errors: dict[str, int] = {}
    params = dict(base)
    for i in range(nx):
        for j in range(ny):
            params[xkey] = xx[i, j]
            params[ykey] = yy[i, j]
            errs = spec.validate(params)
            if errs:
                for e in errs:
                    errors[e] = errors.get(e, 0) + 1
                continue
            try:
                outs[i][j] = spec.solve(params)
            except Exception as e:  # solver-level domain guard tripped
                msg = f"{type(e).__name__}: {e}"
                errors[msg] = errors.get(msg, 0) + 1

    first = next((o for row in outs for o in row if o is not None), None)
    if first is None:
        summary = "; ".join(f"{m} (x{c})" for m, c in list(errors.items())[:3])
        raise ValueError(f"all {nx * ny} scan points are invalid — {summary}")

    keys = [k for k, v in first.items() if isinstance(v, (int, float))]
    grids = {k: np.full((nx, ny), np.nan) for k in keys}
    for i in range(nx):
        for j in range(ny):
            out = outs[i][j]
            if out is None:
                continue
            for k in keys:
                v = out.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    grids[k][i, j] = v
    if "valid" not in grids:        # pragma: no cover (solve always sets it)
        grids["valid"] = np.ones((nx, ny))
    # points that failed validation/solve are invalid by definition
    solved = np.array([[outs[i][j] is not None for j in range(ny)]
                       for i in range(nx)])
    grids["valid"] = np.where(solved, grids["valid"], 0.0)

    grids["xx"] = xx
    grids["yy"] = yy
    grids["scan_errors"] = errors
    return grids


def best_region_mask(grids: dict, ge: dict | None = None, le: dict | None = None) -> np.ndarray:
    """Boolean operating-window mask.

    ``ge``/``le`` map output field -> threshold (>= / <=).  Criteria whose field
    is absent from ``grids`` are skipped, so the same call works across configs.
    Invalid points (``valid`` grid == 0) and points where any criterion field
    is NaN/inf are always excluded (audit P0: no fake feasible windows).
    """
    mask = np.ones(grids["xx"].shape, dtype=bool)
    if "valid" in grids:
        mask &= np.asarray(grids["valid"]) > 0.5
    for k, thr in (ge or {}).items():
        if k in grids:
            v = np.real(grids[k])
            mask &= np.isfinite(v) & (v >= thr)
    for k, thr in (le or {}).items():
        if k in grids:
            v = np.real(grids[k])
            mask &= np.isfinite(v) & (v <= thr)
    return mask
