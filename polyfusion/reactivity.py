"""Fusion cross-sections sigma(E) and Maxwellian reactivity <sigma*v>(T).

Port of ``fsgm*.m`` / ``fsgmv.m`` (and the validated JS version in
``etsc.html``).  Energies in keV, cross-sections in m^2, reactivity in m^3/s.

Cross-section fits use the Bosch-Hale astrophysical S-factor form
    sigma(E) = S(E) / [E * exp(BG / sqrt(E))]
except p-B11 (case 5) which interpolates the Weller/Duke data table.
"""

from __future__ import annotations

import numpy as np

from .constants import QE, M_D, M_T, M_HE3, M_B11, MP

# Energy grid shared by every reactivity integral: 10^(-1 .. 3.6) keV,
# matching MATLAB ``10.^(-1:0.0005:3.6)`` (9201 points, inclusive endpoint).
_E_GRID = np.power(10.0, np.linspace(-1.0, 3.6, 9201))


def sigma_dt(E):
    """D + T -> n + 4He, two-segment rational fit (0.5-4700 keV)."""
    E = np.asarray(E, dtype=float)
    BG = 34.3827
    S = np.full_like(E, np.nan)
    lo = E < 550
    hi = (E >= 550) & (E <= 4700)
    El = E[lo]
    S[lo] = (6.927e4 + 7.454e8 * El + 2.05e6 * El**2 + 5.2002e4 * El**3) / (
        1.0 + 6.38e1 * El - 9.95e-1 * El**2 + 6.981e-5 * El**3 + 1.728e-4 * El**4
    )
    Eh = E[hi]
    S[hi] = -1.4714e6 / (
        1.0
        - 8.4127e-3 * Eh
        + 4.7983e-6 * Eh**2
        - 1.0748e-9 * Eh**3
        + 8.85184e-14 * Eh**4
    )
    return S / (E * np.exp(BG / np.sqrt(E))) * 1e-31


def sigma_dd_total(E):
    """D + D, sum of both branches (p+T and n+3He), 0.5-4900 keV."""
    E = np.asarray(E, dtype=float)
    BG = 31.3970
    out = np.full_like(E, np.nan)
    ok = (E > 0) & (E <= 4900)
    Eo = E[ok]
    Sdd1 = (
        5.5576e4
        + 2.1054e2 * Eo
        - 3.2638e-2 * Eo**2
        + 1.4987e-6 * Eo**3
        + 1.8181e-10 * Eo**4
    )
    Sdd2 = (
        5.3701e4
        + 3.3027e2 * Eo
        - 1.2706e-1 * Eo**2
        + 2.9327e-5 * Eo**3
        - 2.5151e-9 * Eo**4
    )
    out[ok] = (Sdd1 + Sdd2) / (Eo * np.exp(BG / np.sqrt(Eo))) * 1e-31
    return out


def sigma_dhe(E):
    """D + 3He -> p + 4He, two-segment rational fit (0.3-4800 keV)."""
    E = np.asarray(E, dtype=float)
    BG = 68.7508
    S = np.full_like(E, np.nan)
    lo = E < 900
    hi = (E >= 900) & (E <= 4800)
    El = E[lo]
    S[lo] = (5.7501e6 + 2.5226e3 * El + 4.5566e1 * El**2) / (
        1.0 - 3.1995e-3 * El - 8.5530e-6 * El**2 + 5.9014e-8 * El**3
    )
    Eh = E[hi]
    S[hi] = -8.3993e5 / (
        1.0
        - 2.6830e-3 * Eh
        + 1.1633e-6 * Eh**2
        - 2.1332e-10 * Eh**3
        + 1.4250e-14 * Eh**4
    )
    return S / (E * np.exp(BG / np.sqrt(E))) * 1e-31


def sigma_pb(E):
    """p + 11B -> 3 4He, resonance model (Nevins & Swain 2000), 0.5-3500 keV."""
    E = np.asarray(E, dtype=float)
    BG = 148.9596  # sqrt(22.589e3)
    S = np.zeros_like(E)
    seg1 = E <= 400
    seg2 = (E > 400) & (E <= 642)
    seg3 = E > 642
    E1 = E[seg1]
    S[seg1] = (
        1.97e5 + 0.24e3 * E1 + 2.31e-1 * E1**2 + 1.82e7 / ((E1 - 148) ** 2 + 2.35**2)
    )
    E2 = E[seg2] / 100.0 - 4.0
    S[seg2] = 3.30e5 + 66.1e3 * E2 - 20.3e3 * E2**2 - 1.58e3 * E2**5
    E3 = E[seg3]
    S[seg3] = (
        4.38e3
        + 2.57e9 / ((E3 - 581.3) ** 2 + 85.7**2)
        + 5.67e8 / ((E3 - 1083) ** 2 + 234**2)
        + 1.34e8 / ((E3 - 2405) ** 2 + 138**2)
        + 5.68e8 / ((E3 - 3344) ** 2 + 309**2)
    )
    out = S / E * np.exp(-BG / np.sqrt(E)) * 1e-28
    out[(E < 0.5) | (E > 3500)] = np.nan
    return out


# Weller/Duke measured p-B11 cross-section table [keV, mb] used by case 5.
# Rounded values matching the shipped JS reference (etsc.html) for bit-level
# agreement with its golden outputs.
_PB_WELLER = np.array(
    [
        [140.8, 0.006],
        [207.6, 0.035],
        [237.0, 0.057],
        [277.1, 0.129],
        [370.7, 0.390],
        [453.5, 0.725],
        [528.4, 1.194],
        [600.6, 1.396],
        [670.1, 1.145],
        [734.2, 0.720],
        [803.7, 0.463],
        [865.2, 0.331],
        [913.3, 0.316],
        [993.5, 0.304],
        [1103.1, 0.318],
        [1191.3, 0.329],
        [1284.9, 0.339],
        [1375.8, 0.324],
        [1466.7, 0.300],
        [1557.6, 0.273],
        [1651.1, 0.249],
        [1742.0, 0.245],
        [1832.9, 0.247],
        [1923.8, 0.269],
        [2014.7, 0.312],
        [2108.2, 0.371],
        [2199.1, 0.480],
        [2292.7, 0.596],
        [2380.9, 0.702],
        [2474.4, 0.608],
        [2565.3, 0.443],
        [2656.2, 0.341],
        [2747.1, 0.351],
        [2840.7, 0.402],
        [2931.6, 0.455],
        [3022.4, 0.535],
        [3116.0, 0.596],
        [3206.9, 0.651],
        [3297.8, 0.684],
        [3388.7, 0.686],
        [3482.2, 0.651],
    ]
)


def sigma_pb2(E):
    """p + 11B from Weller/Duke data (linear interp); <200 keV falls back to Nevins."""
    E = np.asarray(E, dtype=float)
    out = np.full_like(E, np.nan)
    xs, ys = _PB_WELLER[:, 0], _PB_WELLER[:, 1]
    in_range = (E >= xs[0]) & (E <= xs[-1])
    hi = in_range & (E >= 200)
    out[hi] = np.interp(E[hi], xs, ys) * 1e-28
    lo = E < 200
    if np.any(lo):
        out[lo] = sigma_pb(E[lo])
    return out


_SIGMA = {
    1: (sigma_dt, lambda: (M_D * M_T) / (M_D + M_T)),
    2: (sigma_dd_total, lambda: M_D / 2.0),
    3: (sigma_dhe, lambda: (M_D * M_HE3) / (M_D + M_HE3)),
    4: (sigma_pb, lambda: (MP * M_B11) / (MP + M_B11)),
    5: (sigma_pb2, lambda: (MP * M_B11) / (MP + M_B11)),
    6: (sigma_dd_total, lambda: M_D / 2.0),  # cat-DD uses D-D cross-section
}


# sigma(E) depends only on the reaction, not on temperature, so cache the
# evaluated array (and the E-weighted factors) per icase: a big speed-up for
# 2-D scans that call reactivity() tens of thousands of times.
_CACHE: dict[int, tuple] = {}


def _cached(icase: int):
    if icase not in _CACHE:
        sigma_func, mr_func = _SIGMA[icase]
        sigma = sigma_func(_E_GRID)
        E = _E_GRID
        # weight w_i = E_i * sigma_i * dE_i  (sum starts at i=1, matching ref)
        w = E[1:] * sigma[1:] * np.diff(E)
        w = np.where(np.isnan(w), 0.0, w)
        _CACHE[icase] = (w, E[1:], mr_func())
    return _CACHE[icase]


def _reactivity_exact(Teff: float, icase: int) -> float:
    """Exact Maxwellian <sigma*v>(T) [m^3/s] via the full energy integral."""
    if Teff <= 0:
        return 0.0
    w, E1, Mr = _cached(icase)
    integral = np.dot(w, np.exp(-E1 / Teff))
    return np.sqrt(QE * 1e3 * Teff * 8 / (np.pi * Mr)) / Teff**2 * integral


# Temperature lookup table: <sigma*v>(T) is smooth, so the expensive energy
# integral is evaluated once on a dense log grid per reaction and interpolated
# thereafter -- turns a 25x25 POPCON scan from ~9 s to well under 1 s while
# keeping the golden agreement (1400 pts -> interp error << 1e-4).
_LUT: dict[int, tuple] = {}


def _lut(icase: int):
    if icase not in _LUT:
        T = np.geomspace(0.05, 2000.0, 1400)
        sgv = np.array([_reactivity_exact(float(t), icase) for t in T])
        _LUT[icase] = (T, sgv)
    return _LUT[icase]


def reactivity(Teff, icase: int):
    """Maxwellian <sigma*v>(T) [m^3/s], LUT-interpolated (accepts scalar or array)."""
    Tg, Sg = _lut(icase)
    arr = np.asarray(Teff, dtype=float)
    out = np.interp(arr, Tg, Sg)
    out = np.where(arr <= 0.0, 0.0, out)
    return float(out) if arr.ndim == 0 else out
