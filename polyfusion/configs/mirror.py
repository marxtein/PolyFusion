"""0-D axisymmetric magnetic-mirror power balance — v2 (R1 rebuild).

Tokamak-parity treatment (docs/24, mirroring docs/01 section by section):

* GEOMETRY: central cell = uniform-B cylinder (radius ``a_c``, length
  ``L_c``); end regions follow flux conservation a(z)=a_c*sqrt(B_c/B(z))
  with B(z)/B_c = 1+(R-1)sin^2(pi z/2L_th) over throat length
  ``f_throat*L_c`` each end (end volume integrates analytically to
  2*pi*a_c^2*L_th/sqrt(R)).  Wall radius r_w = a_c+g.  Throat flux area
  A_th = pi a_c^2 sqrt(1-beta)/R_mirror (engineering end-load number).
* PROFILES: radial n = ni0(1-x^2)^Sn, T = T0(1-x^2)^ST (axially uniform in
  the central cell) — same family and volume-average algebra as the tokamak.
* FUSION: same profile integral Phi = fsig*2*Int (1-x^2)^{2Sn} <sv>(T(x)) x dx.
* RADIATION: tokamak profile-weighted bremsstrahlung; cyclotron with the
  diamagnetic field B0.
* CONFINEMENT: Pastukhov + gas-dynamic + radial channels (unchanged physics,
  verified in test_mirror_benchmark.py), evaluated at peak values.
* END LOSS: P_trans = Int n(phi+T) dV / tau_c  (MCTrans form, volume-integrated
  over the radial profiles).

Flat-profile limit (Sn=ST=0, g=0, f_throat=0) reproduces v1 numbers exactly
(regression-tested).  References: arXiv:2411.06644; docs/05, docs/20, docs/24.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from ..constants import QE, MP, ME, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS

_KEV_J = 1e3 * QE
_LN_LAMBDA = 17.0


@dataclass
class MirrorResult:
    # power balance
    Pfus: float       # fusion power [MW]
    Pheat: float      # external heating power required [MW]
    Qfus: float       # fusion gain (capped at 1000)
    Qfus_raw: float   # uncapped Pfus/Pheat (negative => ignited/over-driven)
    ignited: float    # 1 if Pheat <= 0
    Pbrem: float      # bremsstrahlung [MW]
    Pcycl: float      # cyclotron [MW]
    Ptrans: float     # end-loss transport power [MW]
    Pn: float         # neutron power [MW]
    Pwall: float      # first-wall load [MW/m^2]
    P_end_flux: float # end-loss power flux through both throats [MW/m^2]
    P_coll_flux: float # flux at the expander collector (diluted by B_expand) [MW/m^2]
    P_alpha_loss: float # charged fusion power escaping before deposit [MW]
    Past_domain: float  # 1 = Pastukhov formula in validity domain, 0 = fallback used
    Eth: float        # stored thermal energy [MJ]
    # confinement
    tau_c: float; tau_Past: float; tau_gd: float; tau_rho: float
    phi_i: float      # ion confining potential [keV]
    phi_e: float      # electron confining potential [keV]
    lambda_ii: float  # ion mean free path [m]
    coll_ratio: float # lambda_ii/(R_mc*L_c): <1 gas-dynamic, >>1 Pastukhov (audit P1)
    ntau: float       # ni0 * tau_c
    # stability / fields
    beta: float       # peak beta
    beta_avg: float   # volume-averaged beta
    B0: float         # diamagnetically reduced central field [T]
    R_mc: float       # effective mirror ratio
    # geometry
    Vp: float; Sp: float; Sw: float; A_throat: float
    # plasma
    ne0: float; nbar: float; Zeff: float; M: float
    fTavg: float; fnavg: float
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def _solve_phi_e_over_Te(K: float) -> float:
    """Solve y*e^y = K (y = phi_e/Te) by Newton on y + ln y = ln K."""
    if K <= 0:
        return 0.0
    lnK = math.log(K)
    y = max(lnK, 0.1)
    for _ in range(60):
        g = y + math.log(y) - lnK
        ynew = y - g / (1.0 + 1.0 / y)
        if ynew <= 0:
            ynew = y / 2
        if abs(ynew - y) < 1e-12:
            return ynew
        y = ynew
    return y


def solve_mirror(a_c, L_c, B_vac, R_mirror, ni0, Ti0, Te0,
                 Sn=0.0, ST=0.0, g=0.0, fsig=1.0, f_throat=0.1,
                 f_alpha=1.0, B_expand=100.0,
                 Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10,
                 phi_i_over_Te=None, lnLambda=_LN_LAMBDA) -> MirrorResult:
    """Evaluate the 0-D mirror power balance at one operating point.

    Parameters (SI / keV / m^-3); see docs/24 §3 for the full table.
    ``Sn``/``ST`` are the radial peaking exponents (0 = flat, tokamak family),
    ``g`` the plasma-wall gap, ``f_throat`` the throat length fraction of L_c.
    """
    rx = _REACTIONS[icase]

    # --- input-domain guards (audit P0) ---
    if a_c <= 0 or L_c <= 0 or B_vac <= 0:
        raise ValueError(f"a_c, L_c, B_vac must be > 0 (got {a_c}, {L_c}, {B_vac})")
    if R_mirror <= 1.0:
        raise ValueError(f"mirror ratio R_mirror must be > 1 (got {R_mirror})")
    if ni0 <= 0 or Ti0 <= 0 or Te0 <= 0:
        raise ValueError(f"ni0, Ti0, Te0 must be > 0 (got {ni0}, {Ti0}, {Te0})")
    if Sn < 0 or ST < 0:
        raise ValueError(f"profile exponents must be >= 0 (got Sn={Sn}, ST={ST})")
    if not 0.0 <= f1 <= 1.0:
        raise ValueError(f"f1 must be in [0, 1] (got {f1})")
    if fHe < 0 or fimp < 0 or fHe + fimp >= 1.0:
        raise ValueError(f"need fHe,fimp >= 0 and fHe+fimp < 1 (got {fHe}, {fimp})")
    if Zimp <= 0:
        raise ValueError(f"Zimp must be > 0 (got {Zimp})")
    if not 0.0 <= Rw <= 1.0:
        raise ValueError(f"wall reflectivity Rw must be in [0, 1] (got {Rw})")
    if not 0.0 <= f_throat <= 0.5:
        raise ValueError(f"f_throat must be in [0, 0.5] (got {f_throat})")
    if not 0.0 <= f_alpha <= 1.0:
        raise ValueError(f"f_alpha must be in [0, 1] (got {f_alpha})")
    if B_expand < 1.0:
        raise ValueError(f"expander ratio B_expand must be >= 1 (got {B_expand})")
    if g < 0 or fsig < 0:
        raise ValueError(f"g and fsig must be >= 0 (got g={g}, fsig={fsig})")
    if lnLambda <= 1:
        raise ValueError(f"lnLambda must be > 1 (got {lnLambda})")
    if phi_i_over_Te is not None and phi_i_over_Te < 0:
        raise ValueError(f"phi_i_over_Te must be >= 0 (got {phi_i_over_Te})")

    # ---------- composition (identical algebra to the tokamak core) ----------
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
    mi = M * MP

    # ---------- beta and diamagnetic well (peak values set the well) ----------
    p_peak = (ni0 * Ti0 + ne0 * Te0) * _KEV_J
    beta = min(2 * MU0 * p_peak / B_vac**2, 0.99)
    beta_avg = beta / (1 + Sn + ST)
    B0 = B_vac * math.sqrt(1 - beta)
    R_mc = R_mirror / math.sqrt(1 - beta)

    # ---------- geometry: cylinder + flux-mapped throat regions ----------
    L_th = f_throat * L_c
    V_cyl = math.pi * a_c**2 * L_c
    # B(z)/Bc = 1+(R_mc-1) sin^2(pi z/2L_th): integral of Bc/B over the throat
    # is L_th/sqrt(R_mc) (analytic), giving the end-region volume exactly.
    V_end = 2 * math.pi * a_c**2 * L_th / math.sqrt(R_mc) if L_th > 0 else 0.0
    Vp = V_cyl + V_end
    # plasma side surface: cylinder part + throat part (numeric, a(z) flux map)
    if L_th > 0:
        zt = np.linspace(0.0, 1.0, 60)
        a_z = a_c / np.sqrt(1 + (R_mc - 1) * np.sin(math.pi * zt / 2) ** 2)
        S_end = 2 * 2 * math.pi * float(np.trapezoid(a_z, zt)) * L_th
    else:
        S_end = 0.0
    Sp = 2 * math.pi * a_c * L_c + S_end
    r_w = a_c + g
    Sw = 2 * math.pi * r_w * L_c + 2 * math.pi * r_w**2   # side + end plates
    A_throat = math.pi * a_c**2 * math.sqrt(1 - beta) / R_mirror  # flux area, both = 2x

    # ---------- radial profiles and volume averages (tokamak family) ----------
    x = np.linspace(0.0, 1.0, 101)
    dx = x[1] - x[0]
    fTavg = float(np.sum(x * (1 - x**2) ** ST) / np.sum(x))
    fnavg = float(np.sum(x * (1 - x**2) ** Sn) / np.sum(x))
    nbar = ne0 * math.sqrt(math.pi) / 2 * math.gamma(Sn + 1) / math.gamma(Sn + 1.5)

    # ---------- ambipolar potentials [keV] ----------
    phi_i = (phi_i_over_Te * Te0) if phi_i_over_Te is not None else Te0 * math.log(R_mirror)
    K = math.sqrt(mi / ME) * (Ti0 / Te0) ** 1.5 * (phi_i / Ti0) * math.exp(phi_i / Ti0)
    phi_e = _solve_phi_e_over_Te(K) * Te0

    # ---------- collision time, mean free path (NRL formulary) ----------
    tau_ii = (Ti0 * 1e3) ** 1.5 * math.sqrt(M) / (4.80e-8 * (ni0 * 1e-6) * lnLambda)
    v_th = math.sqrt(Ti0 * _KEV_J / (2 * mi))
    lambda_ii = v_th * tau_ii
    # collisionality regime label (audit P1): lambda_ii < R*L -> gas-dynamic
    coll_ratio = lambda_ii / (R_mc * L_c)

    # ---------- confinement channels (peak values; physics per docs/20) ----------
    s = math.sqrt(1 + 1 / R_mc)
    G = s * math.log((s + 1) / (s - 1))
    r = phi_i / Ti0
    # Pastukhov validity: the formula assumes a strong potential barrier
    # (phi_i >> Ti).  Its correction denominator 1 + 1/(2r) - 1/(2r)^2 turns
    # negative for r < (sqrt(5)-1)/2/2 ~ 0.31, giving unphysical tau < 0
    # (audit doc, GAMMA-10 case).  Below r=0.5 we fall back to the classic
    # unplugged-mirror scattering estimate tau ~ tau_ii*log10(R) (Post) and
    # flag the point so scans can mask it.
    Past_domain = 1.0
    if r >= 0.5:
        den = 1 + Ti0 / (2 * phi_i) - (Ti0 / (2 * phi_i)) ** 2
        tau_Past = math.sqrt(math.pi) / 2 * tau_ii * r * math.exp(r) * G / den
    else:
        Past_domain = 0.0
        tau_Past = tau_ii * max(math.log10(R_mc), 0.5) * math.exp(r)
    tau_gd = math.sqrt(math.pi) * R_mc * (L_c / v_th) * math.exp(r)
    rho_i = v_th / (Z1 * QE * B0 / mi)
    tau_rho = (a_c / rho_i) ** 2 * tau_ii
    tau_c = 1.0 / (1.0 / (tau_Past + tau_gd) + 1.0 / tau_rho)

    # ---------- fusion power: radial profile integral (tokamak form) ----------
    Tx = Ti0 * (1 - x**2) ** ST
    sgv = reactivity(Tx, icase)
    Phi = fsig * 2 * float(np.sum((1 - x**2) ** (2 * Sn) * sgv * x * dx))
    Pfus = rx["Y"] / (1 + d12) * n10 * n20 * Phi * Vp * 1e-6   # MW
    Pn = Pfus * (1 - rx["fion"])

    # ---------- radiation: tokamak profile-weighted forms ----------
    Pbrem = (5.34e-37 * ne0**2 * math.sqrt(Te0)
             * (Zeff * (1 / (1 + 2 * Sn + 0.5 * ST))
                + 0.7936 / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2)
                + 1.874 / (1 + 2 * Sn + 2.5 * ST) * (Te0 / MEC2) ** 2
                + 3 / math.sqrt(2) / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2))
             * 1e-6 * Vp)
    neff = ne0 / 1e20 / (1 + Sn)
    Teff = Te0 * float(np.sum((1 - x**2) ** ST)) * dx
    Pcycl = (4.14e-7 * neff**0.5 * Teff**2.5 * B0**2.5 * (1 - Rw)**0.5
             * a_c**-0.5 * (1 + 2.5 * Teff / 511) * Vp)

    # ---------- stored energy & end-loss power (profile-integrated) ----------
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * _KEV_J / (1 + Sn + ST) * Vp * 1e-6  # MJ
    # loss power density n(phi+T)/tau integrated over profiles:
    #   Int n dV = n0 V/(1+Sn);  Int nT dV = n0T0 V/(1+Sn+ST)
    Ptrans = ((ni0 * phi_i + ne0 * phi_e) / (1 + Sn)
              + (ni0 * Ti0 + ne0 * Te0) / (1 + Sn + ST)) * _KEV_J * Vp / tau_c * 1e-6

    # alpha/charged-product deposition: in an open trap part of the charged
    # fusion power escapes through the loss cone before slowing down
    # (audit §4.3); f_alpha = deposited fraction (1 = closed-trap assumption).
    P_charged = rx["fion"] * Pfus
    P_alpha_loss = (1.0 - f_alpha) * P_charged
    Pheat = Pbrem + Pcycl + Ptrans - f_alpha * P_charged
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0
    Pwall = (Pfus + Pheat) / Sw
    P_end_flux = Ptrans / (2 * A_throat) if A_throat > 0 else 0.0
    # end-expander engineering (audit §4.6): the throat flux is spread onto a
    # collector where B has dropped by B_expand; flux dilutes by the same factor.
    P_coll_flux = ((Ptrans + P_alpha_loss) / (2 * A_throat * B_expand)
                   if A_throat > 0 and B_expand > 0 else 0.0)

    return MirrorResult(
        Pfus=Pfus, Pheat=Pheat, Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        Pbrem=Pbrem, Pcycl=Pcycl,
        Ptrans=Ptrans, Pn=Pn, Pwall=Pwall, P_end_flux=P_end_flux,
        P_coll_flux=P_coll_flux, P_alpha_loss=P_alpha_loss, Past_domain=Past_domain,
        Eth=Eth,
        tau_c=tau_c, tau_Past=tau_Past, tau_gd=tau_gd, tau_rho=tau_rho,
        phi_i=phi_i, phi_e=phi_e, lambda_ii=lambda_ii, coll_ratio=coll_ratio,
        ntau=ni0 * tau_c,
        beta=beta, beta_avg=beta_avg, B0=B0, R_mc=R_mc,
        Vp=Vp, Sp=Sp, Sw=Sw, A_throat=A_throat,
        ne0=ne0, nbar=nbar, Zeff=Zeff, M=M, fTavg=fTavg, fnavg=fnavg,
        strcase=rx["name"],
    )
