"""Impurity coronal radiative cooling rates (docs/30 P1-2).

Mavrin (2018) piecewise-polynomial fits of the coronal-equilibrium cooling
rate L_z(Te) for 11 elements, 0.1--100 keV:

    log10 L_z [W m^3] = sum_k c_k (log10 Te[keV])^k     per Te bin,
    P_imp = n_e * n_imp * L_z(Te).

L_z is the TOTAL cooling rate: line radiation + recombination +
bremsstrahlung of that ion.  Our solvers already count the impurity
*bremsstrahlung* inside P_brem with the Xie 2024 species-resolved kernel, so
the net new channel is

    L_line = max( L_z - C_B * Z^2 * sqrt(Te) * g_ei(Te/511, Z) , 0 )

(:func:`lz_line_net`), which avoids double counting and vanishes for
fully-stripped low-Z species at high Te — e.g. helium, where Mavrin's fit
agrees with the pure-bremsstrahlung constant to ~10% (cross-validated in
tests/test_impurity_benchmark.py: two completely independent sources).

Coefficients transcribed from A.A. Mavrin, "Improved fits of coronal
radiative cooling rates for high-temperature plasmas", Radiation Effects
and Defects in Solids 173 (2018) 388 (table as distributed with cfspopcon,
MIT licence; note the upstream file mislabels its variables — the math here
follows the paper: bins and polynomial argument are both in Te).
"""

from __future__ import annotations


import numpy as np

from .bremsstrahlung import brems_ei_cooling_xie2024

# name -> (Z, Te bin borders [keV], coefficient rows c0..c4 per bin)
_MAVRIN = {
    "He": (
        2,
        [0.0, 100.0],
        [[-3.5551e01, 3.1469e-01, 1.0156e-01, -9.3730e-02, 2.5020e-02]],
    ),
    "Li": (
        3,
        [0.0, 100.0],
        [[-3.5115e01, 1.9475e-01, 2.5082e-01, -1.6070e-01, 3.5190e-02]],
    ),
    "Be": (
        4,
        [0.0, 100.0],
        [[-3.4765e01, 3.7270e-02, 3.8363e-01, -2.1384e-01, 4.1690e-02]],
    ),
    "C": (
        6,
        [0.0, 0.5, 100.0],
        [
            [-3.4738e01, -5.0085e00, -1.2788e01, -1.6637e01, -7.2904e00],
            [-3.4174e01, -3.6687e-01, 6.8856e-01, -2.9191e-01, 4.4470e-02],
        ],
    ),
    "N": (
        7,
        [0.0, 0.5, 2.0, 100.0],
        [
            [-3.4065e01, -2.3614e00, -6.0605e00, -1.1570e01, -6.9621e00],
            [-3.3899e01, -5.9668e-01, 7.6272e-01, -1.7160e-01, 5.8770e-02],
            [-3.3913e01, -5.2628e-01, 7.0047e-01, -2.2790e-01, 2.8350e-02],
        ],
    ),
    "O": (
        8,
        [0.0, 0.3, 100.0],
        [
            [-3.7257e01, -1.5635e01, -1.7141e01, -5.3765e00, 0.0000e00],
            [-3.3640e01, -7.6211e-01, 7.9655e-01, -2.0850e-01, 1.4360e-02],
        ],
    ),
    "Ne": (
        10,
        [0.0, 0.7, 5.0, 100.0],
        [
            [-3.3132e01, 1.7309e00, 1.5230e01, 2.8939e01, 1.5648e01],
            [-3.3290e01, -8.7750e-01, 8.6842e-01, -3.9544e-01, 1.7244e-01],
            [-3.3410e01, -4.5345e-01, 2.9731e-01, 4.3960e-02, -2.6930e-02],
        ],
    ),
    "Ar": (
        18,
        [0.0, 0.6, 3.0, 100.0],
        [
            [-3.2155e01, 6.5221e00, 3.0769e01, 3.9161e01, 1.5353e01],
            [-3.2530e01, 5.4490e-01, 1.5389e00, -7.6887e00, 4.9806e00],
            [-3.1853e01, -1.6674e00, 6.1339e-01, 1.7480e-01, -8.2260e-02],
        ],
    ),
    "Kr": (
        36,
        [0.0, 0.447, 2.364, 100.0],
        [
            [-3.4512e01, -2.1484e01, -4.4723e01, -4.0133e01, -1.3564e01],
            [-3.1399e01, -5.0091e-01, 1.9148e00, -2.5865e00, -5.2704e00],
            [-2.9954e01, -6.3683e00, 6.6831e00, -2.9674e00, 4.8356e-01],
        ],
    ),
    "Xe": (
        54,
        [0.0, 0.5, 2.5, 10.0, 100.0],
        [
            [-2.9303e01, 1.4351e01, 4.7081e01, 5.9580e01, 2.5615e01],
            [-3.1113e01, 5.9339e-01, 1.2808e00, -1.1628e01, 1.0748e01],
            [-2.5813e01, -2.7526e01, 4.8614e01, -3.6885e01, 1.0069e01],
            [-2.2138e01, -2.2592e01, 1.9619e01, -7.5181e00, 1.0858e00],
        ],
    ),
    "W": (
        74,
        [0.0, 1.5, 4.0, 100.0],
        [
            [-3.0374e01, 3.8304e-01, -9.5126e-01, -1.0311e00, -1.0103e-01],
            [-3.0238e01, -2.9208e00, 2.2824e01, -6.3303e01, 5.1849e01],
            [-3.2153e01, 5.2499e00, -6.2740e00, 2.6627e00, -3.6759e-01],
        ],
    ),
}

SPECIES = tuple(_MAVRIN)


def atomic_number(name: str) -> int:
    return _MAVRIN[name][0]


def lz_total(name: str, Te_keV) -> np.ndarray:
    """Mavrin total cooling rate L_z(Te) [W m^3]; Te clamped to [0.1, 100] keV."""
    if name not in _MAVRIN:
        raise ValueError(f"unknown impurity {name!r}; have {SPECIES}")
    _, borders, rows = _MAVRIN[name]
    Te = np.clip(np.asarray(Te_keV, dtype=float), 0.1, 100.0)
    x = np.log10(Te)
    out = np.zeros_like(Te)
    for i, c in enumerate(rows):
        sel = (Te >= borders[i]) & (
            Te <= borders[i + 1] if i == len(rows) - 1 else Te < borders[i + 1]
        )
        if np.any(sel):
            out[sel] = 10.0 ** np.polyval(list(reversed(c)), x[sel])
    return out


def lz_line_net(name: str, Te_keV) -> np.ndarray:
    """Cooling rate NET of the bremsstrahlung already counted in P_brem.

    Subtracts the species-resolved Xie 2024 electron-ion bremsstrahlung share
    and clamps at zero, so adding this channel never double-counts.
    """
    Z = _MAVRIN[name][0]
    Te = np.clip(np.asarray(Te_keV, dtype=float), 0.1, 100.0)
    return np.maximum(lz_total(name, Te) - brems_ei_cooling_xie2024(Te, Z), 0.0)
