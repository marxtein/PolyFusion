"""0-D levitated-dipole power balance — v2 (R3 rebuild).

Tokamak-parity treatment (docs/26, mirroring docs/01 section by section):

* GEOMETRY (v2): true point-dipole flux-shell geometry.  A field line crossing
  the equator at distance L follows r = L cos^2(lambda); the volume enclosed
  by the shell of lines out to L is ANALYTIC:
      V_enc(L) = (2pi L^3/3) Int cos^7(lambda) dlambda = 64 pi L^3 / 105,
  so the plasma between the inner boundary L_in and the outer boundary R_p
  has volume V = 64 pi (R_p^3 - L_in^3)/105 and the shell weight is
  dV/dL = 64 pi L^2 / 35.  This replaces the ad-hoc ``f_belt`` spherical
  shell of v1 with the actual dipole topology.
* PROFILES: the marginal-stability profiles hang on the flux label L:
  the dipole flux-tube volume is U(L) = oint dl/B ~ L^4, so delta(p U^gamma)=0
  with gamma=5/3 gives p ~ L^(-20/3); with n ~ U^-1 ~ L^-4 this splits into
  T ~ L^(-8/3).  (Same closure logic as the FRC's K: the profile is the
  *result* of a stability theorem, not a free input.)  The exponent identity
  d ln p/d ln L = -20/3 is verified in the benchmark.
* CONFINEMENT: no established dipole tau_E scaling exists -> tau_E stays an
  input (as for the tokamak); turbulent-pinch literature is cited in docs/26.
* Reactivity / radiation machinery shared with the validated core.

References: Hasegawa 1987; Kesner & Mauel, LDX; docs/10, docs/26.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from ..constants import QE, MP, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS, twotemp_diagnostics
from ..twotemp import p_ei_exchange
from ..impurity import lz_line_net, SPECIES as _IMP_SPECIES
from .. import ringfield

_KEV_J = 1e3 * QE
_SHELL = 64.0 * math.pi / 35.0      # dV/dL = _SHELL * L^2  (exact, point dipole)


@dataclass
class DipoleResult:
    # power balance
    Pfus: float; Pheat: float; Qfus: float
    Qfus_raw: float   # uncapped Pfus/Pheat (negative => ignited/over-driven)
    ignited: float    # 1 if Pheat <= 0
    Pbrem: float; Pcycl: float; Ptrans: float; Pn: float; Pwall: float
    Eth: float
    # confinement
    tau_E: float      # energy confinement time (input) [s]
    ntau: float       # n0 * tau_E
    # profile / stability
    beta_in: float    # beta at the inner (peak-pressure) boundary
    beta_out: float   # beta at the outer boundary (~beta_in*(L_in/L_out)^(2/3)... see docs)
    U_ratio: float    # flux-tube volume ratio U(R_p)/U(L_in) = (R_p/L_in)^4
    p_slope: float    # d ln p / d ln L of the implemented profile (= -20/3)
    # fields / densities
    B_in: float       # field at the inner equatorial boundary [T]
    B_out: float      # field at the outer boundary [T]
    ne0: float        # peak electron density (at L_in) [m^-3]
    nbar: float       # line-averaged density along the outboard equator [m^-3]
    # geometry
    Vp: float; Sw: float; L_in: float
    Zeff: float; M: float
    ring_model: float  # 0 = point dipole (legacy), 1 = exact finite loop
    P_line: float      # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float; f_fast_ion: float; tau_eq_ie: float; P_ei: float
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def solve_dipole(r_ring, R_p, B_ring, n0, Ti0, Te0, tauE,
                 L_in_fac=1.5, fsig=1.0,
                 icase=2, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10,
                 Rw=0.9, N=160, ring_model=0, imp_name=None,
                 use_tauE=1.0) -> DipoleResult:
    """Evaluate the 0-D dipole power balance.

    Parameters (SI / keV)
    ----------
    r_ring, R_p : ring (coil) radius and plasma outer equatorial radius [m]
    B_ring      : field at the ring surface [T]
    n0, Ti0, Te0 : ion density [m^-3] and temperatures [keV] at the INNER
                   plasma boundary L_in = L_in_fac * r_ring (peak values)
    tauE        : energy confinement time [s] (input; no dipole scaling exists)
    L_in_fac    : inner plasma boundary in ring radii (SOL/coil clearance)
    icase       : reaction (default 2 = D-D, the dipole signature fuel)
    """
    rx = _REACTIONS[icase]
    if not bool(use_tauE):
        raise ValueError("dipole has no implemented self-consistent loss closure; keep use_tauE enabled")

    # --- input-domain guards (audit P0: L_in >= R_p gives negative volume) ---
    if r_ring <= 0 or R_p <= 0 or B_ring <= 0:
        raise ValueError(f"r_ring, R_p, B_ring must be > 0 (got {r_ring}, {R_p}, {B_ring})")
    if L_in_fac < 1.0:
        raise ValueError(f"L_in_fac must be >= 1 (inner boundary outside the coil), got {L_in_fac}")
    if L_in_fac * r_ring >= R_p:
        raise ValueError(f"need L_in = L_in_fac*r_ring < R_p "
                         f"(got {L_in_fac * r_ring} >= {R_p}): no plasma shell")
    if n0 <= 0 or Ti0 <= 0 or Te0 <= 0 or tauE <= 0:
        raise ValueError(f"n0, Ti0, Te0, tauE must be > 0 "
                         f"(got {n0}, {Ti0}, {Te0}, {tauE})")
    if not 0.0 <= f1 <= 1.0:
        raise ValueError(f"f1 must be in [0, 1] (got {f1})")
    if fHe < 0 or fimp < 0 or fHe + fimp >= 1.0:
        raise ValueError(f"need fHe,fimp >= 0 and fHe+fimp < 1 (got {fHe}, {fimp})")
    if Zimp <= 0:
        raise ValueError(f"Zimp must be > 0 (got {Zimp})")
    if not 0.0 <= Rw <= 1.0:
        raise ValueError(f"wall reflectivity Rw must be in [0, 1] (got {Rw})")
    if fsig < 0:
        raise ValueError(f"fsig must be >= 0 (got {fsig})")
    d12 = rx["d12"]
    x1 = 1.0 if rx["like"] else f1
    x2 = 1.0 if rx["like"] else (1.0 - f1)
    Z1, Z2, ZHe = rx["Z1"], rx["Z2"], 2
    f12 = 1.0 - fHe - fimp
    M = (x1 * rx["A1"] + x2 * rx["A2"]) / (1 + d12)

    # ---------- flux-shell geometry: point dipole (legacy) or exact loop ----------
    L_in = L_in_fac * r_ring
    L = np.geomspace(L_in, R_p, N)
    Sw = 4 * math.pi * R_p**2               # outer boundary (vessel) area
    if ring_model:
        # exact finite current loop (docs/30 P1-3): universal dimensionless
        # tables in lambda = L/r_ring; U = dV/dpsi exactly; the marginal-
        # stability logic delta(p U^gamma) = 0 is unchanged, only U(L) is real.
        lam = L / r_ring
        U = ringfield.u_spec(lam)
        w = ringfield.dv_dlam(lam) * r_ring**2          # dV/dL
        Vp = float((ringfield.v_enc(lam[-1]) - ringfield.v_enc(lam[0])) * r_ring**3)
        Ufac = U / U[0]
        nfac = 1.0 / Ufac                                # n ~ U^-1
        Tfac = Ufac ** (-2.0 / 3.0)                      # T ~ U^-2/3
        # realised local pressure slope at the geometric mid-shell (no longer
        # exactly -20/3: that value is the POINT-dipole U ~ L^4 special case)
        lnp = np.log(nfac * Tfac * (nfac * Tfac > 0))
        mid = N // 2
        p_slope = float((lnp[mid + 1] - lnp[mid - 1])
                        / (np.log(L[mid + 1]) - np.log(L[mid - 1])))
    else:
        w = _SHELL * L**2                       # dV/dL
        Vp = _SHELL / 3.0 * (R_p**3 - L_in**3)  # = 64*pi*(R_p^3-L_in^3)/105
        nfac = (L_in / L) ** 4                  # n ~ U^-1 ~ L^-4
        Tfac = (L_in / L) ** (8.0 / 3.0)        # T ~ L^-8/3  (p ~ L^-20/3)
        p_slope = -20.0 / 3.0
    ni = n0 * nfac
    Ti = Ti0 * Tfac
    Te = Te0 * Tfac
    n120 = f12 * ni
    n10, n20 = x1 * n120, x2 * n120
    ne = (n10 * Z1 + n20 * Z2) / (1 + d12) + (fHe * ni) * ZHe + (fimp * ni) * Zimp
    ne0 = float(ne[0])
    Zeff = float(((n10[0] * Z1**2 + n20[0] * Z2**2) / (1 + d12)
                  + (fHe * n0) * ZHe**2 + (fimp * n0) * Zimp**2) / ne0)

    # equatorial field and local beta along the shell.  Loop mode keeps the
    # legacy calibration "B_ring = dipole-equivalent field scale at L=r_ring"
    # (mu0 I = 4 r_ring B_ring), so it is a pure geometry correction.
    if ring_model:
        B_L = 4.0 * B_ring * ringfield.b_eq(L / r_ring)
    else:
        B_L = B_ring * (r_ring / L) ** 3
    B_in, B_out = float(B_L[0]), float(B_L[-1])
    p_keV = (ni * Ti + ne * Te)             # [keV*m^-3]
    beta_loc = 2 * MU0 * p_keV * _KEV_J / B_L**2
    beta_in, beta_out = float(beta_loc[0]), float(beta_loc[-1])
    U_ratio = (R_p / L_in) ** 4

    # outboard-equator line-averaged density (interferometer chord)
    nbar = float(np.trapezoid(ne, L) / (R_p - L_in))

    # ---------- fusion power: integral over the marginal profile ----------
    sgv = reactivity(Ti, icase)
    Pfus = rx["Y"] / (1 + d12) * fsig * float(np.trapezoid(n10 * n20 * sgv * w, L)) * 1e-6
    Pn = Pfus * (1 - rx["fion"])

    # ---------- radiation (per-shell forms) ----------
    rel = (Zeff + 0.7936 * (Te / MEC2) + 1.874 * (Te / MEC2) ** 2
           + 3 / math.sqrt(2) * (Te / MEC2))
    Pbrem = 5.34e-37 * float(np.trapezoid(ne**2 * np.sqrt(Te) * rel * w, L)) * 1e-6
    Pcycl = 4.14e-7 * float(np.trapezoid((ne / 1e20) ** 0.5 * Te**2.5 * B_L**2.5
                                         * (1 - Rw) ** 0.5 * L_in**-0.5
                                         * (1 + 2.5 * Te / 511) * w, L))

    # impurity line radiation (Mavrin; shell-integrated, docs/30 P1-2)
    if imp_name is not None and fimp > 0:
        if imp_name not in _IMP_SPECIES:
            raise ValueError(f"unknown impurity species {imp_name!r}; have {_IMP_SPECIES}")
        nimp_L = fimp * ni
        P_line = float(np.trapezoid(ne * nimp_L * lz_line_net(imp_name, Te) * w, L)) * 1e-6
    else:
        P_line = 0.0

    # ---------- stored energy, transport, balance ----------
    Eth = 1.5 * float(np.trapezoid((ni * Ti + ne * Te) * _KEV_J * w, L)) * 1e-6   # MJ
    Ptrans = Eth / tauE
    Pheat = Pbrem + Pcycl + P_line + Ptrans - rx["fion"] * Pfus
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0
    Pwall = (Pfus + Pheat) / Sw

    # two-temperature channel diagnostics (docs/30 P1-1)
    Ecrit, f_fast, tau_eq, _ = twotemp_diagnostics(
        rx, n0, Te0, Ti0, float(n10[0]), float(n20[0]),
        fHe * n0, fimp * n0, Zimp, M)
    # shell-resolved exchange integral (profiles are steep: do it properly)
    pei_L = np.array([p_ei_exchange(float(nv), float(tiv), float(tev), 1.0, M)
                      if tev > 1e-3 else 0.0
                      for nv, tiv, tev in zip(ni, Ti, Te)])
    P_ei = float(np.trapezoid(pei_L * w, L)) * 1e-6

    return DipoleResult(
        Pfus=Pfus, Pheat=Pheat, Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        Pbrem=Pbrem, Pcycl=Pcycl,
        Ptrans=Ptrans, Pn=Pn, Pwall=Pwall, Eth=Eth,
        tau_E=tauE, ntau=n0 * tauE,
        beta_in=beta_in, beta_out=beta_out, U_ratio=U_ratio, p_slope=p_slope,
        B_in=B_in, B_out=B_out, ne0=ne0, nbar=nbar,
        Vp=Vp, Sw=Sw, L_in=L_in, Zeff=Zeff, M=M,
        ring_model=float(ring_model), P_line=P_line,
        Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq, P_ei=P_ei,
        strcase=rx["name"],
    )
