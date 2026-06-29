"""Exact current-loop (finite-ring) dipole geometry (docs/30 P1-3).

The legacy dipole module uses the POINT-dipole far field, but the plasma
inner boundary sits at L ~ 1.5 ring radii — not remotely far field.  This
module provides the exact axisymmetric vacuum field of a circular current
loop and the derived flux-shell quantities, as universal dimensionless
tables in lambda = L/a (loop radius a = 1, mu0*I = 1):

* poloidal flux function  psi(rho, z) = sqrt(rho) [ (2 - k^2)K - 2E ] / k,
      k^2 = 4 rho / ((1+rho)^2 + z^2)
  (Jackson eq. 5.37 rewritten; K, E by vectorised AGM, no scipy);
* equatorial field        B(lam) = (1/2*pi*rho) d(psi)/d(rho) |_{z=0};
* enclosed volume         V(lam) = volume of the region psi >= psi(lam,0)
  (all field lines crossing the equator inside lam), by sorting a 2-D grid
  of cells by psi and cumulative-summing their volumes;
* flux-tube specific volume  U = dV/dpsi  — an EXACT identity for
  axisymmetric poloidal fields, which replaces any field-line tracing.

Far-field checks (tests/test_ringfield_benchmark.py): B -> mu0 m/(4 pi L^3)
with m = pi (I a^2), U proportional to lam^4, V -> 64 pi lam^3/105 — the
three point-dipole laws must be recovered, which pins the normalisation.

Physical calibration used by configs/dipole.py: the input B_ring keeps its
legacy meaning of the DIPOLE-EQUIVALENT field scale at L = a, i.e.
mu0 I = 4 a B_ring, so presets keep their semantics and the loop mode is a
pure geometry correction.

Tables are built once on first use (~1 s) and cached at module level.
"""

from __future__ import annotations

import math

import numpy as np

_LAM_MIN, _LAM_MAX = 1.05, 16.0


def ellipk_e(k2):
    """Complete elliptic integrals K(k), E(k) by AGM, vectorised.

    Accepts k^2 in [0, 1); machine precision in ~8 iterations.
    """
    k2 = np.asarray(k2, dtype=float)
    a = np.ones_like(k2)
    b = np.sqrt(1.0 - k2)
    # E = K (1 - sum_{n>=0} 2^{n-1} c_n^2), c_0 = k
    s = 0.5 * k2
    pow2 = 0.5
    for _ in range(12):
        c = 0.5 * (a - b)
        an = 0.5 * (a + b)
        b = np.sqrt(a * b)
        a = an
        pow2 *= 2.0
        s = s + pow2 * c * c
    K = math.pi / (2.0 * a)
    E = K * (1.0 - s)
    return K, E


def psi_norm(rho, z):
    """Dimensionless flux function of the unit loop (a=1, mu0*I=1)."""
    rho = np.asarray(rho, dtype=float)
    z = np.asarray(z, dtype=float)
    denom = (1.0 + rho) ** 2 + z**2
    k2 = np.clip(4.0 * rho / denom, 0.0, 1.0 - 1e-14)
    K, E = ellipk_e(k2)
    k = np.sqrt(k2)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.sqrt(rho) * ((2.0 - k2) * K - 2.0 * E) / k
    return np.where(rho <= 0, 0.0, out)


class _LoopTables:
    """Universal dimensionless tables B(lam), V(lam), U(lam)."""

    def __init__(self, n_lam=240, n_rho=1000, n_z=500, rho_max=18.0, z_max=9.0):
        self.lam = np.geomspace(_LAM_MIN, _LAM_MAX, n_lam)

        # equatorial |B| from the flux function: Bz = (1/2 pi rho) dpsi/drho
        h = 1e-5
        dpsi = psi_norm(self.lam + h, 0.0) - psi_norm(self.lam - h, 0.0)
        self.B = np.abs(dpsi / (2 * h)) / (2 * math.pi * self.lam)

        # enclosed volume V(psi_level) by cell sort + cumulative sum
        rho = np.linspace(rho_max / n_rho, rho_max, n_rho)
        zz = np.linspace(z_max / n_z / 2, z_max, n_z)  # upper half plane
        R, Z = np.meshgrid(rho, zz, indexing="ij")
        psi_cells = psi_norm(R, Z).ravel()
        vol_cells = (
            2.0 * 2 * math.pi * R * (rho[1] - rho[0]) * (zz[1] - zz[0])
        ).ravel()
        order = np.argsort(psi_cells)[::-1]  # descending psi
        psi_sorted = psi_cells[order]
        v_cum = np.cumsum(vol_cells[order])

        psi_L = psi_norm(self.lam, 0.0)
        # V at each level: interpolate cumulative volume on the sorted curve
        idx = np.searchsorted(-psi_sorted, -psi_L)  # first cell with psi < level
        idx = np.clip(idx, 1, len(v_cum) - 1)
        self.V = v_cum[idx - 1]
        self.psi_L = psi_L

        # U = |dV/dpsi| along the equatorial family (exact flux-tube volume)
        dV = np.gradient(self.V, self.lam)
        dpsi_dlam = np.gradient(self.psi_L, self.lam)
        self.U = np.abs(dV / dpsi_dlam)
        self.dV_dlam = dV

    def interp(self, lam, arr):
        lam = np.asarray(lam, dtype=float)
        if np.any(lam < _LAM_MIN) or np.any(lam > _LAM_MAX):
            raise ValueError(
                f"lambda = L/r_ring must be in [{_LAM_MIN}, {_LAM_MAX}] "
                f"for the finite-ring tables (got {lam.min():.3g}..{lam.max():.3g})"
            )
        return np.interp(lam, self.lam, arr)


_TABLES: _LoopTables | None = None


def loop_tables() -> _LoopTables:
    global _TABLES
    if _TABLES is None:
        _TABLES = _LoopTables()
    return _TABLES


def b_eq(lam):
    """Equatorial |B| of the unit loop at L/a = lam (units mu0*I/a)."""
    t = loop_tables()
    return t.interp(lam, t.B)


def u_spec(lam):
    """Flux-tube specific volume U(lam) (arbitrary consistent units)."""
    t = loop_tables()
    return t.interp(lam, t.U)


def v_enc(lam):
    """Enclosed volume V(lam) (units a^3)."""
    t = loop_tables()
    return t.interp(lam, t.V)


def dv_dlam(lam):
    """dV/dlam (units a^3)."""
    t = loop_tables()
    return t.interp(lam, t.dV_dlam)
