"""0-D tokamak power-balance solver (port of ``funsc.m`` / ``etsc.html``).

``funsc`` takes geometry, profile, plasma and engineering inputs and returns
a :class:`Result` with the steady-state power balance and derived figures of
merit.  All formulas mirror the validated reference implementations; see
``docs/01_托卡马克代码说明文档.md`` for the physics derivation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from .constants import QE, MU0, MEC2
from .reactivity import reactivity

# Per-reaction parameters: charges, mass numbers, charged-fraction fion,
# energy release Y [J], like-particle flag delta12, and a label.
_REACTIONS = {
    1: dict(Z1=1, Z2=1, A1=2, A2=3, fion=0.2, Y=17.59e6 * QE, d12=0, like=False, name="D-T"),
    2: dict(Z1=1, Z2=1, A1=2, A2=2, fion=(3.27 / 4 + 4.04) / (3.27 + 4.04),
            Y=0.5 * (3.27 + 4.04) * 1e6 * QE, d12=1, like=True, name="D-D"),
    3: dict(Z1=1, Z2=2, A1=2, A2=3, fion=1.0, Y=18.35e6 * QE, d12=0, like=False, name="D-He3"),
    4: dict(Z1=1, Z2=5, A1=1, A2=11, fion=1.0, Y=8.68e6 * QE, d12=0, like=False, name="pB-Nevins"),
    5: dict(Z1=1, Z2=5, A1=1, A2=11, fion=1.0, Y=8.68e6 * QE, d12=0, like=False, name="pB-Sikora"),
    6: dict(Z1=1, Z2=1, A1=2, A2=2, fion=26.73 / 43.25, Y=0.5 * 43.25e6 * QE,
            d12=1, like=True, name="D-D(cat)"),
}


@dataclass
class Result:
    """Outputs of a single 0-D power-balance evaluation."""
    Eth: float      # stored thermal energy [MJ]
    H98: float      # IPB98y2 confinement quality factor
    HST: float      # spherical-tokamak confinement quality factor
    Pheat: float    # net external heating power [MW]
    Pn: float       # neutron power [MW]
    Pfus: float     # fusion power [MW]
    Pwall: float    # first-wall load [MW/m^2]
    Qfus: float     # fusion gain Pfus/Pheat
    betaN: float    # normalized beta
    betaT: float    # toroidal beta
    nbar_o_nGw: float  # line-avg density / Greenwald limit
    q: float        # safety factor
    Pbrem: float    # bremsstrahlung power [MW]
    Pcycl: float    # cyclotron radiation power [MW]
    Vp: float       # plasma volume [m^3]
    betap: float    # poloidal beta
    Sp: float       # plasma surface area [m^2]
    ne0: float      # central electron density [m^-3]
    M: float        # mean fuel mass number
    fTavg: float    # temperature volume-average factor
    fnavg: float    # density volume-average factor
    Sw: float       # first-wall area [m^2]
    Pth: float      # transport loss power [MW]
    Zeff: float     # effective charge
    strcase: str    # reaction label

    def as_dict(self) -> dict:
        return asdict(self)


def funsc(R0, A, kappa, delta, Sn, ST, ni0, Ti0, fT, fsig, f1,
          BT0, Ip, tauE, fHe, fimp, Zimp, Rw, g, icase) -> Result:
    """Evaluate the 0-D power balance for one operating point.

    See parameter table in ``docs/01_托卡马克代码说明文档.md`` (§3) for units.
    """
    rx = _REACTIONS[icase]

    # --- geometry ---
    a = R0 / A
    Ad = R0 / (g + a)
    Vp = (2 * math.pi**2 * kappa * (A - delta) + 16 * math.pi * kappa * delta / 3) * a**3
    Sp = (4 * math.pi**2 * A * kappa**0.65 - 4 * kappa * delta) * a**2
    Sw = (4 * math.pi**2 * Ad * kappa**0.65 - 4 * kappa * delta) * (a + g)**2

    # --- composition ---
    Te0 = fT * Ti0
    f12 = 1.0 - fHe - fimp
    n120 = f12 * ni0
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    d12 = rx["d12"]
    Z1, Z2, Zimp_, ZHe = rx["Z1"], rx["Z2"], Zimp, 2
    n10 = x1 * n120
    n20 = x2 * n120
    nHe0 = fHe * ni0
    nimp0 = fimp * ni0
    ne0 = (n10 * Z1 + n20 * Z2) / (1 + d12) + nHe0 * ZHe + nimp0 * Zimp_
    Zeff = ((n10 * Z1**2 + n20 * Z2**2) / (1 + d12)
            + nHe0 * ZHe**2 + nimp0 * Zimp_**2) / ne0
    M = (x1 * rx["A1"] + x2 * rx["A2"]) / (1 + d12)

    # --- profiles and volume averages ---
    x = np.linspace(0.0, 1.0, 101)
    dx = x[1] - x[0]
    fTavg = np.sum(x * (1 - x**2) ** ST) / np.sum(x)
    fnavg = np.sum(x * (1 - x**2) ** Sn) / np.sum(x)

    # --- reactivity profile integral Phi ---
    phi = 0.0
    for xi in x:
        Tx = Ti0 * (1 - xi**2) ** ST
        sgv = reactivity(Tx, icase)
        if not math.isnan(sgv):
            phi += (1 - xi**2) ** (2 * Sn) * sgv * xi * dx
    Phi = fsig * 2 * phi

    # --- fusion power ---
    Pfus = rx["Y"] / (1 + d12) * n10 * n20 * Phi * Vp * 1e-6
    Pn = Pfus * (1 - rx["fion"])

    # --- bremsstrahlung (relativistic-corrected, profile-weighted) ---
    term1 = Zeff * (1 / (1 + 2 * Sn + 0.5 * ST))
    term2 = 0.7936 / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2)
    term3 = 1.874 / (1 + 2 * Sn + 2.5 * ST) * (Te0 / MEC2) ** 2
    term4 = 3 / math.sqrt(2) / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2)
    Pbrem = 5.34e-37 * ne0**2 * math.sqrt(Te0) * (term1 + term2 + term3 + term4) * 1e-6 * Vp

    # --- cyclotron radiation (empirical) ---
    neff = ne0 / 1e20 / (1 + Sn)
    aeff = a * math.sqrt(kappa)
    Teff = Te0 * np.sum((1 - x**2) ** ST) * dx
    Pcycl = (4.14e-7 * neff**0.5 * Teff**2.5 * BT0**2.5 * (1 - Rw)**0.5
             * aeff**-0.5 * (1 + 2.5 * Teff / 511) * Vp)

    # --- stored energy, transport loss, heating, gain ---
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / (1 + Sn + ST) * Vp * 1e-6
    Pth = Eth / tauE
    Pheat = Pcycl + Pbrem + Pth - rx["fion"] * Pfus
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0

    # --- beta limits ---
    betaT = 2 * MU0 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / BT0**2 / (1 + Sn + ST)
    betaN = 100 * betaT / (Ip / (a * BT0))
    betap = (25 / betaT) * ((1 + kappa**2) / 2) * (betaN / 100) ** 2

    # --- density limits and confinement scalings ---
    nbar = ne0 * math.sqrt(math.pi) / 2 * math.gamma(Sn + 1) / math.gamma(Sn + 1.5)
    nGw = 1e20 * Ip / (math.pi * a**2)
    nbar_o_nGw = nbar / nGw
    PL = rx["fion"] * Pfus + Pheat
    if PL > 0:
        tauE98 = (0.145 * Ip**0.93 * R0**1.39 * a**0.58 * kappa**0.78
                  * (nbar / 1e20)**0.41 * BT0**0.15 * M**0.19) / PL**0.69
        tauEST = (0.066 * Ip**0.53 * BT0**1.05 * (nbar / 1e19)**0.65
                  * R0**2.66 * kappa**0.78) / PL**0.58
        H98 = tauE / tauE98
        HST = tauE / tauEST
    else:
        H98 = HST = 0.0

    q = 5 * BT0 * a**2 * kappa / (R0 * Ip)
    Pwall = (Pfus + Pheat) / Sw

    return Result(
        Eth=Eth, H98=H98, HST=HST, Pheat=Pheat, Pn=Pn, Pfus=Pfus, Pwall=Pwall,
        Qfus=Qfus, betaN=betaN, betaT=betaT, nbar_o_nGw=nbar_o_nGw, q=q,
        Pbrem=Pbrem, Pcycl=Pcycl, Vp=Vp, betap=betap, Sp=Sp, ne0=ne0, M=M,
        fTavg=fTavg, fnavg=fnavg, Sw=Sw, Pth=Pth, Zeff=Zeff, strcase=rx["name"],
    )
