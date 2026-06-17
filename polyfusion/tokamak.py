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
from dataclasses import replace as _dc_replace

from .twotemp import (critical_energy, ion_deposition_fraction, equilibration_time,
                      p_ei_exchange, solve_channel_balance)
from .impurity import lz_line_net, SPECIES as _IMP_SPECIES
from .tokageom import tokamak_geometry

# Per-reaction parameters: charges, mass numbers, charged-fraction fion,
# energy release Y [J], like-particle flag delta12, and a label.
# Efast/Afast: representative fast charged product (energy [keV], mass number)
# for the Stix slowing-down diagnostics (docs/30 P1-1).
_REACTIONS = {
    1: dict(Z1=1, Z2=1, A1=2, A2=3, fion=0.2, Y=17.59e6 * QE, d12=0, like=False,
            name="D-T", Efast=3520.0, Afast=4.0),
    2: dict(Z1=1, Z2=1, A1=2, A2=2, fion=(3.27 / 4 + 4.04) / (3.27 + 4.04),
            Y=0.5 * (3.27 + 4.04) * 1e6 * QE, d12=1, like=True,
            name="D-D", Efast=2430.0, Afast=2.0),
    3: dict(Z1=1, Z2=2, A1=2, A2=3, fion=1.0, Y=18.35e6 * QE, d12=0, like=False,
            name="D-He3", Efast=14680.0, Afast=1.0),
    4: dict(Z1=1, Z2=5, A1=1, A2=11, fion=1.0, Y=8.68e6 * QE, d12=0, like=False,
            name="pB-Nevins", Efast=2900.0, Afast=4.0),
    5: dict(Z1=1, Z2=5, A1=1, A2=11, fion=1.0, Y=8.68e6 * QE, d12=0, like=False,
            name="pB-Sikora", Efast=2900.0, Afast=4.0),
    6: dict(Z1=1, Z2=1, A1=2, A2=2, fion=26.73 / 43.25, Y=0.5 * 43.25e6 * QE,
            d12=1, like=True, name="D-D(cat)", Efast=3520.0, Afast=4.0),
}


def twotemp_diagnostics(rx, ni0, Te0, Ti0, n10, n20, nHe0, nimp0, Zimp, M):
    """Shared two-temperature diagnostic block (docs/30 P1-1).

    Returns (Ecrit [keV], f_fast_ion, tau_eq_ie [s], p_ei [W/m^3] at peak):
    the Stix critical energy and ion-deposition fraction of the reaction's
    representative fast charged product, and the bulk-ion/electron
    collisional equilibration channel at peak parameters.  Diagnostics only
    in this batch — they do not enter the power balance.
    """
    species = [(n10, rx["Z1"], rx["A1"]), (n20, rx["Z2"], rx["A2"]),
               (nHe0, 2, 4), (nimp0, Zimp, max(2 * Zimp, 1))]
    species = [(n, Z, A) for (n, Z, A) in species if n > 0]
    Ecrit = critical_energy(Te0, rx["Afast"], species)
    f_fast = ion_deposition_fraction(rx["Efast"], Ecrit)
    tau_eq = equilibration_time(ni0, Te0, 1.0, M)
    pei = p_ei_exchange(ni0, Ti0, Te0, 1.0, M)
    return Ecrit, f_fast, tau_eq, pei


def _line_average_factor(S):
    """Centered-line average factor for ``(1 - rho**2)**S``."""
    return math.sqrt(math.pi) / 2 * math.gamma(S + 1) / math.gamma(S + 1.5)


def _line_average_factor_from_vfrac(S, rho, vfrac):
    """Area-equivalent line-average factor from a cumulative volume fraction.

    ``u = sqrt(V(rho) / V(1))`` is the equivalent circular line coordinate.  For
    self-similar circular geometry, ``u == rho`` and this reduces to the gamma
    expression in :func:`_line_average_factor`.
    """
    rho = np.asarray(rho, dtype=float)
    vfrac = np.asarray(vfrac, dtype=float)
    if rho.shape != vfrac.shape or rho.ndim != 1 or rho.size < 2:
        raise ValueError("rho and vfrac must be one-dimensional arrays of equal length")
    if np.allclose(vfrac, rho**2, rtol=1e-10, atol=1e-12):
        return _line_average_factor(S)
    u = np.sqrt(np.clip(vfrac, 0.0, 1.0))
    order = np.argsort(u)
    u = u[order]
    rho = rho[order]
    values = (1.0 - np.clip(rho, 0.0, 1.0) ** 2) ** S
    return float(np.trapezoid(values, u))


def _line_average_value(center, S, rho, vfrac):
    return float(center) * _line_average_factor_from_vfrac(S, rho, vfrac)


def line_radiation_profile(imp_name, ne0, nimp0, Te0, Sn, ST, Vp, x, dx):
    """Impurity line-radiation power [MW] for the (1-x^2)^S profile family.

    P_line = Int n_e(x) n_imp(x) Lz_net(Te(x)) 2x dx * Vp; Lz_net is the
    Mavrin coronal cooling rate minus the bremsstrahlung share already
    counted in P_brem through Z_eff (no double counting; docs/30 P1-2).
    """
    if imp_name is None or nimp0 <= 0:
        return 0.0
    if imp_name not in _IMP_SPECIES:
        raise ValueError(f"unknown impurity species {imp_name!r}; have {_IMP_SPECIES}")
    Tex = Te0 * (1 - x ** 2) ** ST
    lz = lz_line_net(imp_name, Tex)
    integ = 2.0 * float(np.sum((1 - x ** 2) ** (2 * Sn) * lz * x * dx))
    return ne0 * nimp0 * integ * Vp * 1e-6


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
    Qfus: float     # fusion gain Pfus/Pheat (capped at 1000)
    Qfus_raw: float # uncapped Pfus/Pheat (negative => ignited/over-driven)
    ignited: float  # 1 if Pheat <= 0 (alpha heating alone exceeds losses)
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
    Ptrans: float   # alias of Pth for release UI consistency [MW]
    Zeff: float     # effective charge
    P_line: float   # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float    # Stix critical energy of the fast product [keV]
    f_fast_ion: float  # fraction of fast-product energy deposited on ions
    tau_eq_ie: float   # ion-electron equilibration time [s] (peak params)
    P_ei: float     # ion->electron collisional exchange power [MW] (diagnostic)
    Te0: float      # central electron temperature actually used [keV]
    fT_used: float  # Te0/Ti0 actually used (input, or solved when fT=0)
    te_mode: float  # 0 = fT input (legacy), 1 = Te solved self-consistently
    te_resid: float # electron-channel residual at the solution [MW]
    tauE_used: float  # confinement time actually used [s]
    taue_mode: float  # 0 = tauE input (legacy), 1 = solved from scaling (tauE=0)
    P_LH: float       # Martin 2008 L->H threshold power [MW] (mass-corrected)
    LH_ratio: float   # P_sep/P_LH = Pth/P_LH; >~1 required for H-mode access
    tau_ITPA20: float # ITPA20-IL H-mode scaling prediction [s] (Verdoolaege 2021)
    H_ITPA20: float   # tauE / tau_ITPA20 (second opinion next to H98)
    nu_eff_ang: float  # Angioni effective collisionality 0.1 Zeff n19 R/<Te>^2
    Sn_sugg: float  # density-peaking exponent suggested by Angioni scaling
    nbar_geom: float  # area-equivalent line-average density diagnostic [m^-3]
    Te_line_geom: float  # area-equivalent line-average electron temperature [keV]
    Ti_line_geom: float  # area-equivalent line-average ion temperature [keV]
    Vp_geom: float        # raw integrated/fit plasma volume before override [m^3]
    Sw_geom: float        # raw integrated/fit wall area before override [m^2]
    geom_volume_ratio: float  # Vp_geom / Vp (1.0 unless Vp_override set)
    geom_wall_ratio: float    # Sw_geom / Sw (1.0 unless Sw_override set)
    shaf_shift: float     # Shafranov shift [m] (CF model only; 0 otherwise)
    geom_model: float     # geometry model actually used (0/1/2)
    divertor: float       # divertor topology echo (0 limiter / 1 double-null)
    strcase: str    # reaction label

    def as_dict(self) -> dict:
        return asdict(self)


def funsc(R0, A, kappa, delta, Sn, ST, ni0, Ti0, fT, fsig, f1,
          BT0, Ip, tauE, fHe, fimp, Zimp, Rw, g, icase,
          imp_name=None, f_aux_e=0.5, H_fac=1.0, use_tauE=1.0,
          geom_model=0.0, divertor=0.0, Vp_override=0.0, Sw_override=0.0) -> Result:
    """Evaluate the 0-D power balance for one operating point.

    See parameter table in ``docs/01_托卡马克代码说明文档.md`` (§3) for units.

    SENTINEL MODES (docs/30; every upgrade degrades back to the legacy
    calculation by NOT using the sentinel):

    * ``fT = 0`` — solve the electron temperature self-consistently from the
      0-D electron-channel balance
          (1-f_i) P_charged + P_ei + f_aux_e * max(P_heat, 0)
              = P_brem + P_cycl + P_line + E_th,e / tauE
      (``f_aux_e`` = electron fraction of external heating; NBI ~0.5, ECH ~1).
      Outputs ``fT_used``/``Te0``/``te_mode``/``te_resid``.
    * ``tauE = 0`` — solve the confinement time PREDICTIVELY from the IPB98
      scaling: find tauE such that H98 = ``H_fac`` (default 1 = database
      average; an implicit equation because tau98 depends on the loss power,
      which depends on tauE).  Outputs ``tauE_used``/``taue_mode``; H98 then
      equals H_fac by construction.  tauE > 0 keeps the legacy input mode.
    """
    rx = _REACTIONS[icase]

    if not 0.0 <= f_aux_e <= 1.0:
        raise ValueError(f"f_aux_e must be in [0, 1] (got {f_aux_e})")
    if H_fac <= 0:
        raise ValueError(f"H_fac must be > 0 (got {H_fac})")
    manual_tauE = bool(use_tauE)
    if manual_tauE and tauE <= 0:
        raise ValueError(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    if not manual_tauE:
        tauE = 0.0

    if tauE == 0:
        def _eval_t(t):
            return funsc(R0, A, kappa, delta, Sn, ST, ni0, Ti0, fT, fsig, f1,
                         BT0, Ip, t, fHe, fimp, Zimp, Rw, g, icase,
                         imp_name=imp_name, f_aux_e=f_aux_e, H_fac=H_fac,
                         use_tauE=1.0,
                         geom_model=geom_model, divertor=divertor,
                         Vp_override=Vp_override, Sw_override=Sw_override)

        def _resid_t(t, res):
            # H98(t) is monotone increasing in t; root at H98 = H_fac
            return H_fac - res.H98

        t, res, r, conv = solve_channel_balance(_eval_t, _resid_t, 1e-3, 50.0)
        return _dc_replace(res, taue_mode=1.0 if conv else 0.5,
                           tauE_used=t)
    if fT == 0:
        def _eval(ft):
            return funsc(R0, A, kappa, delta, Sn, ST, ni0, Ti0, ft, fsig, f1,
                         BT0, Ip, tauE, fHe, fimp, Zimp, Rw, g, icase,
                         imp_name=imp_name, f_aux_e=f_aux_e, H_fac=H_fac,
                         use_tauE=1.0,
                         geom_model=geom_model, divertor=divertor,
                         Vp_override=Vp_override, Sw_override=Sw_override)

        def _resid(ft, res):
            Eth_e = 1.5 * res.ne0 * ft * Ti0 * 1e3 * QE / (1 + Sn + ST) * res.Vp * 1e-6
            heat = ((1 - res.f_fast_ion) * (res.Pfus - res.Pn) + res.P_ei
                    + f_aux_e * max(res.Pheat, 0.0))
            return heat - (res.Pbrem + res.Pcycl + res.P_line + Eth_e / tauE)

        ft, res, r, conv = solve_channel_balance(_eval, _resid, 0.03, 2.5)
        # te_mode: 1 = solved & converged, 0.5 = pinned at a bracket endpoint
        return _dc_replace(res, te_mode=1.0 if conv else 0.5, te_resid=r,
                           fT_used=ft, Te0=ft * Ti0)

    # --- input-domain guards (audit P0: no complex/inf results may escape) ---
    if R0 <= 0 or A <= 0 or kappa <= 0:
        raise ValueError(f"R0, A, kappa must be > 0 (got {R0}, {A}, {kappa})")
    if not -1.0 < delta < 1.0:
        raise ValueError(f"triangularity delta must be in (-1, 1) (got {delta})")
    if Sn < 0 or ST < 0:
        raise ValueError(f"profile exponents must be >= 0 (got Sn={Sn}, ST={ST})")
    if fT < 0:
        raise ValueError(f"fT must be >= 0 (got {fT}; 0 = solve Te self-consistently)")
    if not 0.0 <= f1 <= 1.0:
        raise ValueError(f"f1 must be in [0, 1] (got {f1})")
    if fHe < 0 or fimp < 0 or fHe + fimp >= 1.0:
        raise ValueError(f"need fHe,fimp >= 0 and fHe+fimp < 1 (got {fHe}, {fimp})")
    if Zimp <= 0:
        raise ValueError(f"Zimp must be > 0 (got {Zimp})")
    if not 0.0 <= Rw <= 1.0:
        raise ValueError(f"wall reflectivity Rw must be in [0, 1] (got {Rw})")
    if g < 0 or fsig < 0:
        raise ValueError(f"g and fsig must be >= 0 (got g={g}, fsig={fsig})")
    if BT0 <= 0 or Ip <= 0 or tauE <= 0:
        raise ValueError(f"BT0, Ip, tauE must be > 0 (got {BT0}, {Ip}, {tauE})")

    # --- geometry (three selectable models; docs/04) ---
    geom = tokamak_geometry(int(geom_model), R0, A, kappa, delta, g,
                            int(divertor), Vp_override, Sw_override)
    a = geom["a"]
    Vp = geom["Vp"]
    Sp = geom["Sp"]
    Sw = geom["Sw"]

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
    vfrac = x**2

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

    # --- impurity line radiation (Mavrin; opt-in, docs/30 P1-2) ---
    P_line = line_radiation_profile(imp_name, ne0, nimp0, Te0, Sn, ST, Vp, x, dx)

    # --- stored energy, transport loss, heating, gain ---
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / (1 + Sn + ST) * Vp * 1e-6
    Pth = Eth / tauE
    Pheat = Pcycl + Pbrem + P_line + Pth - rx["fion"] * Pfus
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0

    # --- beta limits ---
    betaT = 2 * MU0 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / BT0**2 / (1 + Sn + ST)
    betaN = 100 * betaT / (Ip / (a * BT0))
    betap = (25 / betaT) * ((1 + kappa**2) / 2) * (betaN / 100) ** 2

    # --- density limits and confinement scalings ---
    nbar = ne0 * _line_average_factor(Sn)
    nbar_geom = _line_average_value(ne0, Sn, x, vfrac)
    Te_line_geom = _line_average_value(Te0, ST, x, vfrac)
    Ti_line_geom = _line_average_value(Ti0, ST, x, vfrac)
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
        # ITPA20-IL (Verdoolaege NF 61 (2021) 076006; coefficients cross-read
        # from cfspopcon energy_confinement_scalings.yaml): a second, newer
        # database regression next to IPB98 — their spread is a free
        # uncertainty estimate on the confinement assumption.
        tau_ITPA20 = (0.067 * M**0.3 * BT0**-0.13 * Ip**1.29 * R0**1.19
                      * (1 + delta)**0.56 * kappa**0.67
                      * (nbar / 1e19)**0.15 / PL**0.644)
        H_ITPA20 = tauE / tau_ITPA20
    else:
        H98 = HST = 0.0
        tau_ITPA20 = float("nan")
        H_ITPA20 = 0.0

    # L->H transition threshold (Martin NF 2008, with 2/M mass correction —
    # the IPB98/ITPA20 H-mode scalings only apply when Pth exceeds this):
    P_LH = 0.0488 * (nbar / 1e20)**0.717 * BT0**0.803 * Sp**0.941 * (2.0 / M)
    LH_ratio = Pth / P_LH if P_LH > 0 else 0.0

    q = 5 * BT0 * a**2 * kappa / (R0 * Ip)
    Pwall = (Pfus + Pheat) / Sw

    # --- two-temperature channel diagnostics (docs/30 P1-1) ---
    Ecrit, f_fast, tau_eq, pei = twotemp_diagnostics(
        rx, ni0, Te0, Ti0, n10, n20, nHe0, nimp0, Zimp, M)
    P_ei = pei * Vp / (1 + 2 * Sn + ST) * 1e-6   # peak-weighted estimate [MW]

    # --- Angioni density-peaking suggestion (docs/30 batch 2, diagnostic) ---
    # nu_n = 1.347 - 0.117 ln(nu_eff) - 4.03 betaT,  nu_eff = 0.1 Zeff n19 R/<Te>^2
    # (Angioni NF 2007); for our profile family peak/<n> = 1+Sn exactly, so the
    # scaling's suggested exponent is Sn_sugg = nu_n - 1.  Compare with your input.
    nu_eff = 0.1 * Zeff * (ne0 / (1 + Sn) * 1e-19) * R0 / (Te0 / (1 + ST)) ** 2
    nu_n = max(1.347 - 0.117 * math.log(nu_eff) - 4.03 * betaT, 1.0)
    Sn_sugg = nu_n - 1.0

    return Result(
        Eth=Eth, H98=H98, HST=HST, Pheat=Pheat, Pn=Pn, Pfus=Pfus, Pwall=Pwall,
        Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        betaN=betaN, betaT=betaT, nbar_o_nGw=nbar_o_nGw, q=q,
        Pbrem=Pbrem, Pcycl=Pcycl, Vp=Vp, betap=betap, Sp=Sp, ne0=ne0, M=M,
        fTavg=fTavg, fnavg=fnavg, Sw=Sw, Pth=Pth, Ptrans=Pth, Zeff=Zeff,
        P_line=P_line, Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq,
        P_ei=P_ei, Te0=Te0, fT_used=fT, te_mode=0.0, te_resid=0.0,
        tauE_used=tauE, taue_mode=0.0,
        P_LH=P_LH, LH_ratio=LH_ratio, tau_ITPA20=tau_ITPA20, H_ITPA20=H_ITPA20,
        nu_eff_ang=nu_eff, Sn_sugg=Sn_sugg, nbar_geom=nbar_geom,
        Te_line_geom=Te_line_geom, Ti_line_geom=Ti_line_geom,
        Vp_geom=geom["Vp_geom"], Sw_geom=geom["Sw_geom"],
        geom_volume_ratio=geom["geom_volume_ratio"],
        geom_wall_ratio=geom["geom_wall_ratio"], shaf_shift=geom["shaf_shift"],
        geom_model=float(int(geom_model)), divertor=float(int(divertor)),
        strcase=rx["name"],
    )
