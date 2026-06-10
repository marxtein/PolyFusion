"""0-D stellarator power balance (SP4.6).

Closest of all configurations to the tokamak core: geometry, parabolic-power
profiles, reactivity integral and radiation are identical to ``funsc``.  Only
the *confinement closure* differs — there is no plasma current, so:
  * energy confinement uses the **ISS04** stellarator scaling (not IPB98y2),
  * the density limit is **Sudo** (not Greenwald),
  * the rotational transform ``iota`` (set by the coils) replaces the safety
    factor ``q``, and the beta limit is a soft ~5%.

Formulas verified against Yamada et al. ISS04 (Nucl. Fusion 45 (2005) 1684) and
Sudo et al. (Nucl. Fusion 30 (1990) 11); see ``docs/12_仿星器0D物理调研.md``.
NOTE: uncalibrated against a specific machine; ``f_ren`` (configuration factor)
and ``iota`` are user inputs — see ``docs/14`` module review.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from ..constants import QE, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS

_KEV_J = 1e3 * QE
_BETA_SOFT_LIMIT = 0.05   # ~5% soft stellarator beta limit (Mercier; can be exceeded)


@dataclass
class StellaratorResult:
    Eth: float        # stored thermal energy [MJ]
    H_ISS04: float    # ISS04 confinement quality factor
    Pheat: float      # net external heating power [MW]
    Pn: float         # neutron power [MW]
    Pfus: float       # fusion power [MW]
    Pwall: float      # first-wall load [MW/m^2]
    Qfus: float       # fusion gain
    betaT: float      # toroidal beta
    beta_o_limit: float   # betaT / 0.05 (soft-limit margin)
    nbar_o_Sudo: float    # line-avg density / Sudo limit
    Pbrem: float
    Pcycl: float
    Vp: float
    iota: float       # rotational transform (input, = 1/q-ish)
    tau_ISS04: float  # ISS04 predicted confinement time [s]
    Sp: float
    Sw: float
    ne0: float
    M: float
    Zeff: float
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def solve_stellarator(R0, A, kappa, delta, Sn, ST, ni0, Ti0, fT, fsig, f1,
                      B0, iota, tauE, fHe, fimp, Zimp, Rw, g, icase,
                      f_ren=1.0) -> StellaratorResult:
    """Evaluate the 0-D stellarator power balance at one operating point.

    Parameters mirror :func:`polyfusion.tokamak.funsc` except ``Ip`` is replaced
    by ``iota`` (rotational transform at r/a=2/3) and ``f_ren`` (ISS04
    configuration renormalization factor, ~1 for the database mean).
    """
    rx = _REACTIONS[icase]
    a = R0 / A
    Ad = R0 / (g + a)

    # --- geometry (identical to funsc) ---
    Vp = (2 * math.pi**2 * kappa * (A - delta) + 16 * math.pi * kappa * delta / 3) * a**3
    Sp = (4 * math.pi**2 * A * kappa**0.65 - 4 * kappa * delta) * a**2
    Sw = (4 * math.pi**2 * Ad * kappa**0.65 - 4 * kappa * delta) * (a + g)**2

    # --- composition (identical to funsc) ---
    Te0 = fT * Ti0
    d12 = rx["d12"]
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    Z1, Z2, ZHe = rx["Z1"], rx["Z2"], 2
    f12 = 1.0 - fHe - fimp
    n120 = f12 * ni0
    n10, n20 = x1 * n120, x2 * n120
    nHe0, nimp0 = fHe * ni0, fimp * ni0
    ne0 = (n10 * Z1 + n20 * Z2) / (1 + d12) + nHe0 * ZHe + nimp0 * Zimp
    Zeff = ((n10 * Z1**2 + n20 * Z2**2) / (1 + d12)
            + nHe0 * ZHe**2 + nimp0 * Zimp**2) / ne0
    M = (x1 * rx["A1"] + x2 * rx["A2"]) / (1 + d12)

    # --- profiles + reactivity integral (identical to funsc) ---
    x = np.linspace(0.0, 1.0, 101)
    dx = x[1] - x[0]
    phi = 0.0
    for xi in x:
        Tx = Ti0 * (1 - xi**2) ** ST
        sgv = reactivity(Tx, icase)
        if not math.isnan(sgv):
            phi += (1 - xi**2) ** (2 * Sn) * sgv * xi * dx
    Phi = fsig * 2 * phi
    Pfus = rx["Y"] / (1 + d12) * n10 * n20 * Phi * Vp * 1e-6
    Pn = Pfus * (1 - rx["fion"])

    # --- radiation (identical to funsc) ---
    Pbrem = (5.34e-37 * ne0**2 * math.sqrt(Te0)
             * (Zeff * (1 / (1 + 2 * Sn + 0.5 * ST)
                        + 0.7936 / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2)
                        + 1.874 / (1 + 2 * Sn + 2.5 * ST) * (Te0 / MEC2) ** 2)
                + 3 / math.sqrt(2) / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2))
             * 1e-6 * Vp)
    neff = ne0 / 1e20 / (1 + Sn)
    aeff = a * math.sqrt(kappa)
    Teff = Te0 * float(np.sum((1 - x**2) ** ST)) * dx
    Pcycl = (4.14e-7 * neff**0.5 * Teff**2.5 * B0**2.5 * (1 - Rw)**0.5
             * aeff**-0.5 * (1 + 2.5 * Teff / 511) * Vp)

    # --- stored energy, heating, gain (identical structure) ---
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / (1 + Sn + ST) * Vp * 1e-6
    Pth = Eth / tauE
    Pheat = Pcycl + Pbrem + Pth - rx["fion"] * Pfus
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0

    betaT = 2 * MU0 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / B0**2 / (1 + Sn + ST)
    nbar = ne0 * math.sqrt(math.pi) / 2 * math.gamma(Sn + 1) / math.gamma(Sn + 1.5)
    Pwall = (Pfus + Pheat) / Sw

    # --- stellarator-specific closure: ISS04 + Sudo (replace IPB98/Greenwald) ---
    PL = rx["fion"] * Pfus + Pheat   # loss power [MW]
    if PL > 0:
        tau_ISS04 = (0.134 * f_ren * a**2.28 * R0**0.64 * PL**-0.61
                     * (nbar / 1e19)**0.54 * B0**0.84 * iota**0.41)
        H_ISS04 = tauE / tau_ISS04
        n_Sudo = 0.25 * math.sqrt(PL * B0 / (a**2 * R0)) * 1e20   # m^-3
        nbar_o_Sudo = nbar / n_Sudo
    else:
        tau_ISS04 = float("inf")
        H_ISS04 = 0.0
        nbar_o_Sudo = 0.0

    return StellaratorResult(
        Eth=Eth, H_ISS04=H_ISS04, Pheat=Pheat, Pn=Pn, Pfus=Pfus, Pwall=Pwall,
        Qfus=Qfus, betaT=betaT, beta_o_limit=betaT / _BETA_SOFT_LIMIT,
        nbar_o_Sudo=nbar_o_Sudo, Pbrem=Pbrem, Pcycl=Pcycl, Vp=Vp, iota=iota,
        tau_ISS04=tau_ISS04, Sp=Sp, Sw=Sw, ne0=ne0, M=M, Zeff=Zeff,
        strcase=rx["name"],
    )
