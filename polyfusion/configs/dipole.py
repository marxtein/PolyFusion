"""0-D levitated-dipole power balance (SP4.5).

Forward evaluator (cf. ``funsc`` / ``solve_mirror`` / ``solve_frc``).  Dipole
defining physics: ideal-MHD marginal stability ``δ(pV^{5/3})≥0`` makes the
plasma self-organise to a steeply peaked profile ``n∝r^{-4}``, ``T∝r^{-8/3}``
(``p∝r^{-20/3}``), allowing very high beta with no shear.  Fusion power is
integrated over the marginal radial profile; the signature fuel is D-D.

There is no established empirical confinement scaling for dipoles, so ``tauE``
is taken as an input (as the tokamak code itself does for τ_E).  Reactivity and
radiation machinery is reused from the validated core.

References: Hasegawa 1987; Kesner & Mauel (LDX).  See ``docs/10_偶极场0D物理调研.md``.
NOTE: uncalibrated — verification is physical-limit/monotonicity sanity.
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
class DipoleResult:
    Pfus: float       # fusion power [MW]
    Pheat: float      # external heating power required [MW]
    Qfus: float       # fusion gain
    Pbrem: float      # bremsstrahlung [MW]
    Pcycl: float      # cyclotron [MW]
    Ptrans: float     # transport loss [MW]
    tau_E: float      # energy confinement time (input) [s]
    beta_ring: float  # beta at the ring (peak)
    Vp: float         # plasma volume [m^3]
    ne0: float        # peak electron density at ring [m^-3]
    Eth: float        # stored thermal energy [MJ]
    Zeff: float
    M: float
    ntau: float       # n0 * tau_E [s/m^3]
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def solve_dipole(r_ring, R_p, B_ring, n0, Ti0, Te0, tauE,
                 icase=2, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10,
                 Rw=0.9, f_belt=0.5, N=120) -> DipoleResult:
    """Evaluate the 0-D dipole power balance.

    Parameters (SI / keV)
    ----------
    r_ring, R_p : ring (coil) radius and plasma outer radius [m]
    B_ring      : field at the ring surface [T]
    n0, Ti0, Te0 : peak ion density [m^-3] and ion/electron temperature [keV] at ring
    tauE        : energy confinement time [s] (input — no dipole scaling exists)
    icase       : reaction (default 2 = D-D, the dipole signature fuel)
    f_belt      : fraction of the (4/3)π(R_p³-r_ring³) shell occupied by plasma
    """
    rx = _REACTIONS[icase]
    d12 = rx["d12"]
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    Z1, Z2, ZHe = rx["Z1"], rx["Z2"], 2
    f12 = 1.0 - fHe - fimp
    M = (x1 * rx["A1"] + x2 * rx["A2"]) / (1 + d12)

    # --- marginal radial profiles: n ∝ r^-4, T ∝ r^-8/3 (p ∝ r^-20/3) ---
    # Log-spaced grid: resolves the steep near-ring cusp independently of R_p
    # (uniform grid + rectangle rule mis-weights the r^-8 fusion integrand).
    r = np.geomspace(r_ring, R_p, N)
    nfac = (r_ring / r) ** 4
    Tfac = (r_ring / r) ** (8.0 / 3.0)
    ni = n0 * nfac
    Ti = Ti0 * Tfac
    Te = Te0 * Tfac
    n120 = f12 * ni
    n10, n20 = x1 * n120, x2 * n120
    ne = (n10 * Z1 + n20 * Z2) / (1 + d12) + (fHe * ni) * ZHe + (fimp * ni) * Zimp
    ne0 = float(ne[0])
    # composition ratios are r-independent -> scalar Zeff (value at the ring)
    Zeff = float((((n10[0] * Z1**2 + n20[0] * Z2**2) / (1 + d12)
                   + (fHe * n0) * ZHe**2 + (fimp * n0) * Zimp**2) / ne0))

    w = f_belt * 4 * math.pi * r**2          # dV/dr weight
    Vp = float(np.trapezoid(w, r))

    # --- fusion power: integrate marginal profile (trapezoidal over log grid) ---
    sgv = np.array([reactivity(t, icase) for t in Ti])
    Pfus = rx["Y"] / (1 + d12) * float(np.trapezoid(n10 * n20 * sgv * w, r)) * 1e-6

    # --- bremsstrahlung (per-shell ETSC density form) ---
    rel = Zeff * (1 + 0.7936 * (Te / MEC2) + 1.874 * (Te / MEC2) ** 2) + 3 / math.sqrt(2) * (Te / MEC2)
    Pbrem = 5.34e-37 * float(np.trapezoid(ne**2 * np.sqrt(Te) * rel * w, r)) * 1e-6

    # --- cyclotron (field falls as r^-3; concentrated near ring) ---
    Br = B_ring * (r_ring / r) ** 3
    Pcycl = 4.14e-7 * float(np.trapezoid((ne / 1e20) ** 0.5 * Te**2.5 * Br**2.5
                                         * (1 - Rw) ** 0.5 * r_ring**-0.5
                                         * (1 + 2.5 * Te / 511) * w, r))

    # --- stored energy, transport, balance ---
    Eth = 1.5 * float(np.trapezoid((ni * Ti + ne * Te) * _KEV_J * w, r)) * 1e-6   # MJ
    Ptrans = Eth / tauE
    beta_ring = 2 * MU0 * (n0 * Ti0 + ne0 * Te0) * _KEV_J / B_ring**2
    Pheat = Pbrem + Pcycl + Ptrans - rx["fion"] * Pfus
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0

    return DipoleResult(
        Pfus=Pfus, Pheat=Pheat, Qfus=Qfus, Pbrem=Pbrem, Pcycl=Pcycl,
        Ptrans=Ptrans, tau_E=tauE, beta_ring=beta_ring, Vp=Vp, ne0=ne0,
        Eth=Eth, Zeff=Zeff, M=M, ntau=n0 * tauE, strcase=rx["name"],
    )
