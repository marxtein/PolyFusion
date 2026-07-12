"""Xie 2024 thermal bremsstrahlung fits.

The kernel follows H.-S. Xie, "Bremsstrahlung Radiation Power in Fusion
Plasmas Revisited: Towards Accurate Analytical Fitting" (PPCF, 2024) and the
reference implementation in ``hsxie/brem``.  It keeps the electron-ion Gaunt
factor species-resolved instead of collapsing the ion mix into a scalar Zeff.
"""

from __future__ import annotations

import math

import numpy as np

MEC2_KEV = 511.0
CB_XIE2024 = 4.86e-37  # W m^3 keV^-1/2, fgfit.m comment / Eq. 38 convention


def gaunt_ei_xie2024(t, Z):
    """Electron-ion Gaunt factor ``gei(t, Z)`` from Xie 2024 ``fgfit.m``."""
    t = np.asarray(t, dtype=float)
    Z = np.asarray(Z, dtype=float)
    t_safe = np.maximum(t, 1.0e-12)
    z_safe = np.maximum(Z, 1.0e-12)

    ceff = 2.0 * math.sqrt(3.0) / math.pi
    x = [0.4365, 2.3857, 0.7952, 0.5305, 0.3257]
    tau_z = t_safe / (z_safe * z_safe)
    fnr = (
        1.0
        + x[0] * (1.0 - np.exp(-((x[1] * 1.0e-4 / tau_z) ** x[3])))
        - (x[0] + (1.0 - 1.0 / ceff))
        * np.exp(-((tau_z / (x[2] * 1.0e-5)) ** x[4]))
    )

    xx = np.sqrt(t_safe / (t_safe + 1.0))
    cc = 9.0 / 8.0 * math.sqrt(6.0 / math.pi)
    cr = [1.4502, -2.6772, 2.9998, -0.9198]
    fr = (
        cr[0] * xx
        + cr[1] * xx**2
        + cc
        * (1.0 + cr[2] * (xx - 1.0) + cr[3] * (xx**3 - 1.0))
        * np.sqrt(t_safe)
        * (np.log(2.0 * t_safe + 1.0) + 1.5 - 0.5772)
    )

    x0 = [57601.4561174080, 3.44046808898792, 16.8063152455324, 0.133254253876019]
    scaled = t_safe / np.sqrt(z_safe / 10.0) / 1.0e-2
    fz = (z_safe / 10.0) * x0[0] * scaled ** x0[1] / (
        np.exp(x0[2] * scaled ** x0[3]) - 1.0
    )
    return ceff * (fnr - fz) + fr


def gaunt_ee_xie2024(t):
    """Electron-electron Gaunt factor ``gee(t)`` from Xie 2024 ``fgfit.m``."""
    t = np.asarray(t, dtype=float)
    t_safe = np.maximum(t, 1.0e-12)
    gnr0 = 2.0 * math.sqrt(3.0) / math.pi * (3.0 / math.sqrt(2.0) * t_safe)
    fee = 0.5 * (np.tanh(0.602 * (np.log10(t_safe) + 5.06)) + 1.0)
    xx = np.sqrt(t_safe / (t_safe + 0.7))
    x = [-0.106, 3.347, -2.642]
    cc = 3.0 / 4.0 * math.sqrt(math.pi)
    return (
        1.0
        / np.sqrt(t_safe + 1.0)
        * (
            1.0
            + x[0] * xx**2
            + cc * (0.295 + x[1] * xx**2 + x[2] * xx**3) * np.log(2.0 * t_safe + 1.0)
        )
        * fee
        * gnr0
    )


def ion_species_from_mix(rx, ni0, f1, fHe, fimp, Zimp):
    """Return central ion species ``[(n_i, Z_i), ...]`` for a PolyFusion mix."""
    d12 = rx["d12"]
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    f12 = 1.0 - fHe - fimp
    n120 = f12 * ni0
    species = [
        (x1 * n120 / (1.0 + d12), rx["Z1"]),
        (x2 * n120 / (1.0 + d12), rx["Z2"]),
        (fHe * ni0, 2),
        (fimp * ni0, Zimp),
    ]
    return [(n, Z) for n, Z in species if np.any(np.asarray(n) > 0.0)]


def brems_gaunt_total_xie2024(ne, Te_keV, species):
    """Return ``sum Zi^2 ni/ne gei(t,Zi) + gee(t)`` for local plasma state."""
    ne_arr = np.asarray(ne, dtype=float)
    Te = np.asarray(Te_keV, dtype=float)
    t = np.maximum(Te, 1.0e-12) / MEC2_KEV
    g = np.asarray(gaunt_ee_xie2024(t), dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        for n_i, Z in species:
            ni_arr = np.asarray(n_i, dtype=float)
            g = g + (Z * Z) * (ni_arr / ne_arr) * gaunt_ei_xie2024(t, Z)
    return np.where(ne_arr > 0.0, g, 0.0)


def brems_power_density_xie2024(ne, Te_keV, species):
    """Thermal bremsstrahlung power density [W m^-3]."""
    ne_arr = np.asarray(ne, dtype=float)
    Te = np.asarray(Te_keV, dtype=float)
    g = brems_gaunt_total_xie2024(ne_arr, Te, species)
    return CB_XIE2024 * ne_arr**2 * np.sqrt(np.maximum(Te, 0.0)) * g


def brems_ei_cooling_xie2024(Te_keV, Z):
    """Electron-ion brems coefficient [W m^3] for one impurity charge state.

    This is the per-``n_e n_i`` term subtracted from Mavrin total cooling to
    keep impurity line radiation net of the bremsstrahlung already in P_brem.
    """
    Te = np.asarray(Te_keV, dtype=float)
    t = np.maximum(Te, 1.0e-12) / MEC2_KEV
    return CB_XIE2024 * Z * Z * np.sqrt(np.maximum(Te, 0.0)) * gaunt_ei_xie2024(t, Z)


def brems_power_profile_xie2024(ne0, Te0, species0, Sn, ST, Vp, x, dx):
    """Profile-integrated bremsstrahlung power [MW] for ``(1-rho^2)^S`` profiles."""
    shape_n = (1.0 - x**2) ** Sn
    shape_T = (1.0 - x**2) ** ST
    ne = ne0 * shape_n
    Te = Te0 * shape_T
    species = [(n0 * shape_n, Z) for n0, Z in species0]
    density = brems_power_density_xie2024(ne, Te, species)
    return 2.0 * float(np.sum(density * x * dx)) * Vp * 1.0e-6


def brems_power_uniform_xie2024(ne0, Te0, species0, density_moment, Vp):
    """Uniform-temperature, analytic-density-moment brems power [MW]."""
    density = brems_power_density_xie2024(ne0, Te0, species0)
    return float(density) * density_moment * Vp * 1.0e-6


def brems_power_shell_xie2024(ne, Te, species, weights, coord):
    """Shell-integrated bremsstrahlung power [MW]."""
    density = brems_power_density_xie2024(ne, Te, species)
    return float(np.trapezoid(density * weights, coord)) * 1.0e-6
