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

from dataclasses import replace as _dc_replace

from ..constants import QE, MP, ME, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS, twotemp_diagnostics, line_radiation_profile
from ..twotemp import solve_channel_balance
from ..geometry import get_geometry

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
    tau_E: float; tau_c: float; tau_Past: float; tau_gd: float; tau_rho: float
    phi_i: float      # ion confining potential [keV]
    phi_e: float      # electron confining potential [keV]
    lambda_ii: float  # ion mean free path [m]
    coll_ratio: float # lambda_ii/(R_mc*L_c): <1 gas-dynamic, >>1 Pastukhov (audit P1)
    a_over_rhoi: float  # a_c/rho_i: DCLC micro-stability proxy — small values
                        # (~<20) historically drove drift-cyclotron loss-cone
                        # modes; large is favourable (docs/30 batch 3a)
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
    P_line: float     # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float      # Stix critical energy [keV]
    f_fast_ion: float # fast-product energy fraction to ions
    tau_eq_ie: float  # ion-electron equilibration time [s]
    P_ei: float       # ion->electron exchange power [MW] (diagnostic)
    f_alpha_used: float  # charged-product deposition fraction actually used
    Te0_used: float   # electron temperature actually used [keV]
    te_mode: float    # 0 = Te0 input, 1 = solved, 0.5 = pinned
    te_resid: float   # electron-channel residual at solution [MW]
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


def solve_mirror(a_c, L_c, B_vac, R_mirror, ni0, Ti0, Te0, geometry="sin2_simple", tauE=1.0,
                 Sn=0.0, ST=0.0, g=0.0, fsig=1.0, f_throat=0.1,
                 f_alpha=None, B_expand=100.0,
                 Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10,
                 phi_i_over_Te=None, lnLambda=_LN_LAMBDA,
                 imp_name=None, f_aux_e=0.5, use_tauE=1.0,
                 L_th=None, profile="hermite", f_axial=0.8, L_expand=2.0) -> MirrorResult:
    """Evaluate the 0-D mirror power balance at one operating point.

    Parameters (SI / keV / m^-3); see docs/24 §3 for the full table.
    ``Sn``/``ST`` are the radial peaking exponents (0 = flat, tokamak family),
    ``g`` the plasma-wall gap, ``f_throat`` the throat length fraction of L_c.
    ``geometry`` selects the axial geometry model: ``"sin2_simple"`` (default,
    original cylinder + sin² throat model) or ``"multi_zone"`` (independent
    throat length, expander zone, switchable B(z) profile).

    Batch-2 physics (docs/30):
    * ``f_alpha = None`` (default) now computes the prompt loss-cone bound
      sqrt(1 - 1/R_mc): an isotropically born charged product is lost at
      birth with the loss-cone solid-angle fraction.  Pass ``f_alpha = 1``
      to recover the old closed-trap idealisation.
    * ``Te0 = 0`` solves the electron temperature self-consistently from the
      electron-channel balance (alpha electron share + P_ei + f_aux_e*Pheat
      = brems + cycl + line + electron end loss); the GDT-type Te << Ti
      hierarchy becomes an OUTPUT instead of an input.
    """
    rx = _REACTIONS[icase]

    if not 0.0 <= f_aux_e <= 1.0:
        raise ValueError(f"f_aux_e must be in [0, 1] (got {f_aux_e})")
    manual_tauE = bool(use_tauE)
    if manual_tauE and tauE <= 0:
        raise ValueError(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    if manual_tauE and Te0 == 0:
        raise ValueError("Te0=0 self-consistent solve is only available when use_tauE is disabled")

    if Te0 == 0:
        def _eval(te):
            return solve_mirror(a_c, L_c, B_vac, R_mirror, ni0, Ti0, te, geometry=geometry, tauE=tauE,
                                Sn=Sn, ST=ST, g=g, fsig=fsig, f_throat=f_throat,
                                f_alpha=f_alpha, B_expand=B_expand, Rw=Rw,
                                icase=icase, f1=f1, fHe=fHe, fimp=fimp,
                                Zimp=Zimp, phi_i_over_Te=phi_i_over_Te,
                                lnLambda=lnLambda, imp_name=imp_name,
                                f_aux_e=f_aux_e, use_tauE=use_tauE,
                                L_th=L_th, profile=profile, f_axial=f_axial, L_expand=L_expand)

        def _resid(te, res):
            # electron share of the end loss (phi_e + Te per escaping electron)
            Ptrans_e = ((res.ne0 * res.phi_e / (1 + Sn)
                         + res.ne0 * te / (1 + Sn + ST))
                        * _KEV_J * res.Vp / res.tau_c * 1e-6)
            heat = ((1 - res.f_fast_ion) * res.f_alpha_used * (res.Pfus - res.Pn)
                    + res.P_ei + f_aux_e * max(res.Pheat, 0.0))
            return heat - (res.Pbrem + res.Pcycl + res.P_line + Ptrans_e)

        te, res, r, conv = solve_channel_balance(
            _eval, _resid, max(0.005, 0.01 * Ti0), 1.5 * Ti0)
        return _dc_replace(res, te_mode=1.0 if conv else 0.5, te_resid=r,
                           Te0_used=te)

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
    if f_alpha is not None and not 0.0 <= f_alpha <= 1.0:
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

    # ---------- geometry object ----------
    geom_cls = get_geometry(geometry)
    geom_kwargs = dict(a_c=a_c, L_c=L_c, B_vac=B_vac, R_mirror=R_mirror, beta=beta)
    f_axial_used = 1.0
    if geometry == "sin2_simple":
        geom_kwargs.update(f_throat=f_throat, g=g)
    elif geometry == "multi_zone":
        L_th_val = f_throat * L_c if L_th is None else L_th
        geom_kwargs.update(L_th=L_th_val, g=g, profile=profile,
                           f_axial=f_axial, L_expand=L_expand, B_expand=B_expand)
        f_axial_used = f_axial
    geom = geom_cls(**geom_kwargs)

    # charged-product deposition: default = prompt loss-cone bound (docs/30
    # batch 2).  An isotropically born alpha falls in the loss cone with
    # solid-angle fraction 1 - sqrt(1 - 1/R_mc); the deposited fraction is
    # the complement.  Ignores scattering INTO the cone during slow-down, so
    # it is an OPTIMISTIC bound — explicit f_alpha input overrides.
    f_alpha_used = 1.0 if manual_tauE else (
        math.sqrt(1.0 - 1.0 / R_mc) if f_alpha is None else f_alpha)

    # ---------- geometry (from geometry module) ----------
    Vp = geom.volume()
    Sp = geom.surface()
    Sw = geom.wall_surface()
    A_throat = geom.throat_area()

    # ---------- radial profiles and volume averages (tokamak family) ----------
    x = np.linspace(0.0, 1.0, 101)
    dx = x[1] - x[0]
    fTavg = float(np.sum(x * (1 - x**2) ** ST) / np.sum(x))
    fnavg = float(np.sum(x * (1 - x**2) ** Sn) / np.sum(x))
    nbar = ne0 * math.sqrt(math.pi) / 2 * math.gamma(Sn + 1) / math.gamma(Sn + 1.5)

    # ---------- ambipolar potentials [keV] ----------
    # phi_i_over_Te: None or 0 = auto (Te*ln R); > 0 = explicit override
    phi_i = ((phi_i_over_Te * Te0) if (phi_i_over_Te is not None and phi_i_over_Te > 0)
             else Te0 * math.log(R_mirror))
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
    a_over_rhoi = a_c / rho_i
    tau_rho = a_over_rhoi ** 2 * tau_ii
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

    # ---------- stored energy & transport power ----------
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * _KEV_J / (1 + Sn + ST) * Vp * 1e-6  # MJ
    if manual_tauE:
        Ptrans = Eth / tauE
    else:
        # loss power density n(phi+T)/tau integrated over profiles:
        #   Int n dV = n0 V/(1+Sn);  Int nT dV = n0T0 V/(1+Sn+ST)
        Ptrans = ((ni0 * phi_i + ne0 * phi_e) / (1 + Sn)
                  + f_axial_used * (ni0 * Ti0 + ne0 * Te0) / (1 + Sn + ST)) * _KEV_J * Vp / tau_c * 1e-6

    # alpha/charged-product deposition: in an open trap part of the charged
    # fusion power escapes through the loss cone before slowing down
    # (audit §4.3); f_alpha = deposited fraction (1 = closed-trap assumption).
    # impurity line radiation (Mavrin; opt-in, docs/30 P1-2)
    P_line = line_radiation_profile(imp_name, ne0, nimp0, Te0, Sn, ST, Vp, x, dx)

    P_charged = rx["fion"] * Pfus
    P_alpha_loss = 0.0 if manual_tauE else (1.0 - f_alpha_used) * P_charged
    Pheat = Pbrem + Pcycl + P_line + Ptrans - f_alpha_used * P_charged
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0
    Pwall = (Pfus + Pheat) / Sw
    if manual_tauE:
        P_end_flux = 0.0
        P_coll_flux = 0.0
    else:
        P_end_flux = Ptrans / (2 * A_throat) if A_throat > 0 else 0.0
        # end-expander engineering (audit §4.6): the throat flux is spread
        # onto a collector where B has dropped by B_expand.
        P_coll_flux = ((Ptrans + P_alpha_loss) / (2 * A_throat * B_expand)
                       if A_throat > 0 and B_expand > 0 else 0.0)

    # two-temperature channel diagnostics (docs/30 P1-1)
    Ecrit, f_fast, tau_eq, pei = twotemp_diagnostics(
        rx, ni0, Te0, Ti0, n10, n20, nHe0, nimp0, Zimp, M)
    P_ei = pei * Vp / (1 + 2 * Sn + ST) * 1e-6

    return MirrorResult(
        Pfus=Pfus, Pheat=Pheat, Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        Pbrem=Pbrem, Pcycl=Pcycl,
        Ptrans=Ptrans, Pn=Pn, Pwall=Pwall, P_end_flux=P_end_flux,
        P_coll_flux=P_coll_flux, P_alpha_loss=P_alpha_loss, Past_domain=Past_domain,
        Eth=Eth,
        tau_E=tauE if manual_tauE else tau_c,
        tau_c=tau_c, tau_Past=tau_Past, tau_gd=tau_gd, tau_rho=tau_rho,
        phi_i=phi_i, phi_e=phi_e, lambda_ii=lambda_ii, coll_ratio=coll_ratio,
        a_over_rhoi=a_over_rhoi, ntau=ni0 * (tauE if manual_tauE else tau_c),
        beta=beta, beta_avg=beta_avg, B0=B0, R_mc=R_mc,
        Vp=Vp, Sp=Sp, Sw=Sw, A_throat=A_throat,
        ne0=ne0, nbar=nbar, Zeff=Zeff, M=M, fTavg=fTavg, fnavg=fnavg,
        P_line=P_line, Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq,
        P_ei=P_ei, f_alpha_used=f_alpha_used, Te0_used=Te0,
        te_mode=0.0, te_resid=0.0, strcase=rx["name"],
    )
