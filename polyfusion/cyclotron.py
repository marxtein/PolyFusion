"""Shared fast cyclotron corrections and user-supplied tauC selection."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np


_RHO_NODES, _RHO_WEIGHTS = np.polynomial.legendre.leggauss(24)
_THETA_NODES, _THETA_WEIGHTS = np.polynomial.legendre.leggauss(64)


def resolve_cyclotron_power(formula_power: float, electron_energy: float,
                             use_tauC: float, tauC: float | None) -> tuple[float, float]:
    """Return ``(Pcycl [MW], tauC_eff [s])`` for the selected closure."""
    if bool(use_tauC):
        if tauC is None or tauC <= 0:
            raise ValueError(f"tauC must be > 0 when use_tauC is enabled (got {tauC})")
        return electron_energy / tauC, tauC
    return formula_power, electron_energy / formula_power if formula_power > 0 else 1e300


@lru_cache(maxsize=256)
def tokamak_B25_factor(R0: float, a: float, kappa: float, delta: float) -> float:
    """Miller-volume average of ``(B_T/B0)**2.5``, with ``B_T~1/R``."""
    rho = 0.5 * (_RHO_NODES + 1.0)
    wr = 0.5 * _RHO_WEIGHTS
    theta = math.pi * (_THETA_NODES + 1.0)
    wt = math.pi * _THETA_WEIGHTS
    rr, tt = np.meshgrid(rho, theta, indexing="ij")
    alpha = math.asin(delta)
    phase = tt + alpha * np.sin(tt)
    R = R0 + a * rr * np.cos(phase)
    jac = (kappa * a**2 * rr
           * (np.cos(phase) * np.cos(tt)
              + np.sin(phase) * (1 + alpha * np.cos(tt)) * np.sin(tt)))
    volume_weight = R * np.abs(jac)
    quad = wr[:, None] * wt[None, :]
    return float(np.sum(quad * volume_weight * (R0 / R) ** 2.5)
                 / np.sum(quad * volume_weight))


@lru_cache(maxsize=256)
def stellarator_B25_factor(etabar_a: float) -> float:
    """First-order near-axis average of ``|B/B0|**2.5``."""
    rho = 0.5 * (_RHO_NODES + 1.0)
    wr = 0.5 * _RHO_WEIGHTS
    theta = math.pi * (_THETA_NODES + 1.0)
    wt = math.pi * _THETA_WEIGHTS
    rr, tt = np.meshgrid(rho, theta, indexing="ij")
    quad = wr[:, None] * wt[None, :]
    bnorm = np.abs(1.0 + etabar_a * rr * np.cos(tt))
    return float(np.sum(quad * rr * bnorm**2.5) / np.sum(quad * rr))
