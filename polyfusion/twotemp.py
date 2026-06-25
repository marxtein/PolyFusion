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


def solve_channel_balance(evaluate, residual, lo: float, hi: float,
                          n_scan: int = 8, iters: int = 22,
                          monotone: bool = False, tol: float = 0.0):
    """Generic 1-D self-consistency solver for the electron channel.

    ``evaluate(v)`` runs the full configuration solver at parameter value
    ``v`` (e.g. fT or Te0) and returns its result; ``residual(v, res)``
    returns the electron-channel power imbalance [MW] (heating - losses,
    positive when electrons would heat up).  The root is bracketed by a
    coarse scan (the mirror residual is not guaranteed monotone: tau_m
    itself grows with Te), then refined by bisection.

    ``monotone=True`` tells the solver the residual is monotone-decreasing in
    ``v`` (e.g. the H_fac - H_scaling(tauE) residual for the tauE-predictive
    branch: every H factor strictly increases in tauE because the numerator
    is linear in tauE and the scaling denominator only grows like
    P_L^{-alpha}, alpha < 1). The solver then SKIPS the n_scan geometric
    pre-scan and bisects directly between (lo, hi), saving ``n_scan``
    funsc evaluations per outer call. About a 30%-40% wallclock cut on the
    nested ``fT=0`` + ``tauE=0`` mode where the saving multiplies.

    ``tol`` (in residual units, MW for power-channel residuals) early-exits
    the bisection once ``|r_m|<=tol``. Default 0 retains legacy precision.

    Returns (v, result, residual_MW, converged_flag).  If no sign change
    exists in [lo, hi] the closest endpoint is returned with flag 0 —
    callers expose the flag so a pinned solution is never mistaken for a
    converged one (audit honesty rule).
    """
    import numpy as _np

    if monotone:
        res_lo = evaluate(float(lo))
        r_lo = residual(float(lo), res_lo)
        res_hi = evaluate(float(hi))
        r_hi = residual(float(hi), res_hi)
        if r_lo <= 0:
            return float(lo), res_lo, r_lo, 0.0
        if r_hi >= 0:
            return float(hi), res_hi, r_hi, 0.0
        a, b = float(lo), float(hi)
        res_m, r_m = res_hi, r_hi
    else:
        grid = _np.geomspace(lo, hi, n_scan)
        prev_v, prev_res, prev_r = None, None, None
        bracket = None
        for v in grid:
            res = evaluate(float(v))
            r = residual(float(v), res)
            if prev_r is not None and prev_r > 0 >= r:
                bracket = (prev_v, float(v))
                break
            prev_v, prev_res, prev_r = float(v), res, r
        else:
            # no sign change: electrons pinned at an endpoint
            if prev_r is not None and prev_r > 0:
                return prev_v, prev_res, prev_r, 0.0          # even hottest: net heating
            res = evaluate(lo)
            return lo, res, residual(lo, res), 0.0            # even coldest: net cooling

        a, b = bracket
        res_m, r_m = res, r

    mid = b
    for _ in range(iters):
        mid = 0.5 * (a + b)
        res_m = evaluate(mid)
        r_m = residual(mid, res_m)
        if tol > 0 and abs(r_m) <= tol:
            break
        if r_m > 0:
            a = mid
        else:
            b = mid
    return mid, res_m, r_m, 1.0
