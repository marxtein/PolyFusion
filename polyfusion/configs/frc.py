"""0-D field-reversed configuration power balance — v2 (R2 rebuild).

Tokamak-parity treatment (docs/25, mirroring docs/01 section by section):

* PROFILE: the rigid-rotor equilibrium — the standard FRC radial profile —
      n(r)/n_m = sech^2(K u),   B(r)/B_e = tanh(K u),   u = 2(r/r_s)^2 - 1,
  which satisfies radial pressure balance exactly with peak pressure
  p_m = B_e^2/2mu0 at the field null (beta=1 there, the defining FRC fact).
  The profile parameter K is NOT free: the average-beta theorem
  <beta> = 1 - x_s^2/2 fixes it through tanh(K)/K = 1 - x_s^2/2.
  All volume averages are analytic in K:
      <n>/n_m  = tanh(K)/K                       (G1)
      <n^2>/n_m^2 = (tanh K - tanh^3 K/3)/K      (G2, fusion & bremsstrahlung)
      <|B|>/B_e = ln(cosh K)/K                   (synchrotron estimate)
      trapped poloidal flux  phi_p = pi r_s^2 B_e ln(cosh K)/(2K).
* GEOMETRY: prolate separatrix, V = f_shape * pi r_s^2 l_s with
  f_shape in [2/3 (ellipse), 1 (racetrack)].
* TEMPERATURE: uniform on closed field lines (fast parallel transport),
  T_i and T_e independent inputs.
* CONFINEMENT: LSX empirical scaling tau_N = 3.2e-15 eps^0.5 x_s^2 r_s^2.1
  n^0.6 (SI), benchmarked against the LSX device itself (docs/25 §5).

References: Steinhauer PoP 18, 070501 (2011) review; Hoffman & Slough,
NF 33 (1993); patent US9082516 (scaling quoted verbatim).  See docs/25.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from ..constants import QE, MP, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS

_KEV_J = 1e3 * QE


@dataclass
class FRCResult:
    # power balance
    Pfus: float; Pheat: float; Qfus: float
    Pbrem: float; Pcycl: float; Ptrans: float; Pn: float; Pwall: float
    Eth: float
    # confinement
    tau_E: float      # energy ~ particle confinement (LSX scaling) [s]
    ntau: float       # <n_i> * tau_E
    # profile / stability
    K_rr: float       # rigid-rotor profile parameter (from average-beta theorem)
    beta: float       # volume-averaged beta = 1 - x_s^2/2
    beta_null: float  # beta at the field null (=1 by pressure balance)
    x_s: float; elongation: float; s_param: float
    flux_p: float     # trapped poloidal flux [Wb] (THE FRC retention metric)
    # fields / densities
    B_int: float      # <|B|> inside separatrix [T]
    ni0: float        # peak (null) ion density from pressure balance [m^-3]
    ne0: float        # peak electron density [m^-3]
    nbar: float       # line-averaged electron density [m^-3]
    # geometry
    Vp: float; Sp: float; Sw: float
    Zeff: float; M: float
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def _solve_K(beta_avg: float) -> float:
    """Solve tanh(K)/K = beta_avg for the rigid-rotor parameter K (>0)."""
    lo, hi = 1e-4, 25.0
    f = lambda k: math.tanh(k) / k - beta_avg
    if f(lo) < 0:        # beta_avg ~ 1 -> K -> 0
        return lo
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def solve_frc(r_s, l_s, r_w, B_e, Ti, Te, f_shape=0.85, fsig=1.0,
              Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10) -> FRCResult:
    """Evaluate the 0-D FRC power balance at one operating point.

    Parameters (SI / keV); see docs/25 §3.  ``f_shape`` interpolates the
    separatrix volume between ellipse (2/3) and racetrack (1).
    """
    rx = _REACTIONS[icase]

    # ---------- geometry ----------
    x_s = r_s / r_w
    elongation = l_s / (2 * r_s)
    Vp = f_shape * math.pi * r_s**2 * l_s
    Sp = 2 * math.pi * r_s * l_s * (0.5 + 0.5 * f_shape)   # ellipse<->racetrack side area
    Sw = 2 * math.pi * r_w * l_s + 2 * math.pi * r_w**2

    # ---------- rigid-rotor profile from the average-beta theorem ----------
    beta_avg = 1.0 - x_s**2 / 2.0
    K = _solve_K(beta_avg)
    tK = math.tanh(K)
    G1 = tK / K                          # <n>/n_m   (== beta_avg by construction)
    G2 = (tK - tK**3 / 3.0) / K          # <n^2>/n_m^2
    GB = math.log(math.cosh(K)) / K      # <|B|>/B_e

    # ---------- composition (tokamak block) at the field null ----------
    d12 = rx["d12"]
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    Z1, Z2, ZHe = rx["Z1"], rx["Z2"], 2
    f12 = 1.0 - fHe - fimp
    # charge ratio zeta = n_e/n_i for this composition
    zeta = f12 * (x1 * Z1 + x2 * Z2) / (1 + d12) + fHe * ZHe + fimp * Zimp
    # pressure balance at the null: (n_i T_i + n_e T_e)_m = B_e^2/2mu0
    p_m = B_e**2 / (2 * MU0)
    ni_m = p_m / ((Ti + zeta * Te) * _KEV_J)
    ne_m = zeta * ni_m
    n120 = f12 * ni_m
    n10, n20 = x1 * n120, x2 * n120
    nHe0, nimp0 = fHe * ni_m, fimp * ni_m
    Zeff = ((n10 * Z1**2 + n20 * Z2**2) / (1 + d12)
            + nHe0 * ZHe**2 + nimp0 * Zimp**2) / ne_m
    M = (x1 * rx["A1"] + x2 * rx["A2"]) / (1 + d12)
    mi = M * MP

    # line-averaged density along a diameter (numeric, sech^2 chord integral)
    xx = np.linspace(0.0, 1.0, 201)
    nbar = ne_m * float(np.trapezoid(1.0 / np.cosh(K * (2 * xx**2 - 1))**2, xx))

    # ---------- fusion power: analytic <n^2> average, uniform T ----------
    sgv = reactivity(Ti, icase)
    Pfus = rx["Y"] / (1 + d12) * n10 * n20 * G2 * fsig * sgv * Vp * 1e-6
    Pn = Pfus * (1 - rx["fion"])

    # ---------- radiation ----------
    t = Te / MEC2
    Pbrem = (5.34e-37 * ne_m**2 * G2 * math.sqrt(Te)
             * (Zeff * (1 + 0.7936 * t + 1.874 * t**2) + 3 / math.sqrt(2) * t)
             * 1e-6 * Vp)
    B_int = B_e * GB
    Pcycl = (4.14e-7 * (ne_m * G1 / 1e20)**0.5 * Te**2.5 * B_int**2.5
             * (1 - Rw)**0.5 * r_s**-0.5 * (1 + 2.5 * Te / 511) * Vp)

    # ---------- confinement: LSX empirical scaling (SI; docs/25 §5) ----------
    tau_E = 3.2e-15 * elongation**0.5 * x_s**2 * r_s**2.1 * ne_m**0.6

    # ---------- stored energy & balance ----------
    Eth = 1.5 * (ni_m * Ti + ne_m * Te) * _KEV_J * G1 * Vp * 1e-6   # MJ
    Ptrans = Eth / tau_E
    Pheat = Pbrem + Pcycl + Ptrans - rx["fion"] * Pfus
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0
    Pwall = (Pfus + Pheat) / Sw

    # ---------- FRC-specific engineering quantities ----------
    flux_p = math.pi * r_s**2 * B_e * GB / 2.0       # trapped poloidal flux [Wb]
    v_th = math.sqrt(Ti * _KEV_J / mi)
    rho_ie = mi * v_th / (Z1 * QE * B_e)
    s_param = r_s / rho_ie

    return FRCResult(
        Pfus=Pfus, Pheat=Pheat, Qfus=Qfus, Pbrem=Pbrem, Pcycl=Pcycl,
        Ptrans=Ptrans, Pn=Pn, Pwall=Pwall, Eth=Eth,
        tau_E=tau_E, ntau=ni_m * G1 * tau_E,
        K_rr=K, beta=beta_avg, beta_null=1.0, x_s=x_s, elongation=elongation,
        s_param=s_param, flux_p=flux_p,
        B_int=B_int, ni0=ni_m, ne0=ne_m, nbar=nbar,
        Vp=Vp, Sp=Sp, Sw=Sw, Zeff=Zeff, M=M, strcase=rx["name"],
    )
