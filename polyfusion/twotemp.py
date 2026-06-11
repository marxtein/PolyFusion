"""Two-temperature physics primitives (docs/30 P1-1).

Three standard pieces of fast-particle / electron-ion energy-channel physics,
used by every configuration as *diagnostic* outputs in this batch (the full
self-consistent Te solve is the next batch — these functions are its bricks):

* :func:`critical_energy` — Stix critical energy E_c: a fast ion slowing down
  in a plasma gives its energy mostly to ELECTRONS while E >> E_c and mostly
  to IONS once E ~< E_c.   E_c = 14.8 A_f Te [ sum(n_i Z_i^2/A_i)/n_e ]^(2/3).
* :func:`ion_deposition_fraction` — fraction of the fast particle's energy
  deposited on ions over the whole slowing-down history,
      f_i = (E_c/E_0) * Int_0^{E_0/E_c} du / (1 + u^{3/2}),
  (Stix 1972).  Limits: f_i -> 1 for E_0 << E_c, -> 0 for E_0 >> E_c.
  For a D-T alpha (3.5 MeV) at Te = 10 keV, f_i ~ 0.2: alpha heating is
  mostly ELECTRON heating — the physical reason Te tracks Ti in burning
  plasmas unless something heats ions selectively.
* :func:`equilibration_time` / :func:`p_ei_exchange` — NRL-formulary ion-
  electron temperature equilibration: the only bridge between the two
  channels.  tau_eq ~ 0.36 s for D at n = 1e20 m^-3, Te = 10 keV (textbook
  anchor, verified in tests).  If tau_eq << tauE a hot-ion mode (Ti >> Te)
  cannot be sustained — comparing the two is the honesty check this batch
  adds to every configuration.

References: Stix, Plasma Phys. 14 (1972) 367; NRL Plasma Formulary (2019),
relaxation rates; Wesson, Tokamaks, §2.14/5.4.
"""

from __future__ import annotations

import math

import numpy as np

from .constants import QE, MP, ME

_KEV_J = 1e3 * QE


def critical_energy(Te_keV: float, A_fast: float, species) -> float:
    """Stix critical energy [keV] for a fast ion of mass number ``A_fast``.

    ``species`` is an iterable of (n_i [m^-3], Z_i, A_i) describing the
    background ion mix; electron density follows from quasineutrality.
    """
    n_e = sum(n * Z for n, Z, A in species)
    if n_e <= 0:
        raise ValueError("species list gives non-positive electron density")
    s = sum(n * Z * Z / A for n, Z, A in species) / n_e
    return 14.8 * A_fast * Te_keV * s ** (2.0 / 3.0)


def ion_deposition_fraction(E0_keV: float, Ecrit_keV: float, n: int = 400) -> float:
    """Fraction of a fast particle's energy deposited on ions (Stix).

    f_i = (Ec/E0) * Int_0^{E0/Ec} du/(1+u^{3/2}), evaluated numerically
    (the closed form involves logs/arctans; quadrature on a smooth bounded
    integrand is simpler and exact to ~1e-10 at n=400 via Simpson).
    """
    if E0_keV <= 0 or Ecrit_keV <= 0:
        raise ValueError("energies must be positive")
    x = E0_keV / Ecrit_keV
    u = np.linspace(0.0, x, 2 * n + 1)
    f = 1.0 / (1.0 + u ** 1.5)
    # composite Simpson
    h = x / (2 * n)
    integral = h / 3.0 * (f[0] + f[-1] + 4 * f[1:-1:2].sum() + 2 * f[2:-2:2].sum())
    return float(integral / x)


def equilibration_time(n_i: float, Te_keV: float, Z: float, A: float,
                       lnLambda: float = 17.0) -> float:
    """Ion-electron temperature equilibration time [s] (NRL formulary).

    nu_eq = 1.8e-19 sqrt(m_e m_i) Z^2 n_i lnLambda / (m_i Te + m_e Ti)^{3/2}
    in cgs units (masses in g, T in eV, n in cm^-3); for Te >> (m_e/m_i) Ti
    the m_e Ti term is negligible and is dropped here (validity: any fusion-
    relevant regime).  Returns 1/nu_eq.
    """
    if n_i <= 0 or Te_keV <= 0:
        raise ValueError("n_i and Te must be positive")
    m_e = ME * 1e3                       # g
    m_i = A * MP * 1e3                   # g
    Te_eV = Te_keV * 1e3
    n_cm3 = n_i * 1e-6
    nu = (1.8e-19 * math.sqrt(m_e * m_i) * Z * Z * n_cm3 * lnLambda
          / (m_i * Te_eV) ** 1.5)
    return 1.0 / nu


def p_ei_exchange(n_i: float, Ti_keV: float, Te_keV: float, Z: float, A: float,
                  lnLambda: float = 17.0) -> float:
    """Net ion->electron collisional heat-exchange power density [W/m^3].

    P_ei = (3/2) n_i (Ti - Te) e*10^3 / tau_eq.  Positive when ions are
    hotter (energy flows ion -> electron); zero at equal temperatures.
    """
    tau = equilibration_time(n_i, Te_keV, Z, A, lnLambda)
    return 1.5 * n_i * (Ti_keV - Te_keV) * _KEV_J / tau
