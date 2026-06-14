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
from ..tokamak import _REACTIONS, twotemp_diagnostics
from ..impurity import lz_line_net, SPECIES as _IMP_SPECIES

_KEV_J = 1e3 * QE


@dataclass
class FRCResult:
    # power balance
    Pfus: float; Pheat: float; Qfus: float
    Qfus_raw: float   # uncapped Pfus/Pheat (negative => ignited/over-driven)
    ignited: float    # 1 if Pheat <= 0
    Pbrem: float; Pcycl: float; Ptrans: float; Pn: float; Pwall: float
    Eth: float
    # confinement
    tau_E: float      # energy ~ particle confinement (LSX scaling) [s]
    ntau: float       # <n_i> * tau_E
    # profile / stability
    K_rr: float       # rigid-rotor profile parameter (from average-beta theorem)
    G1: float         # <n>/n_m volume-average factor used by the power account
    G2: float         # <n^2>/n_m^2 volume-average factor used by fusion/radiation
    GB: float         # <|B|>/B_e volume-average factor used by synchrotron estimate
    p_shape: float    # superellipse exponent matching f_shape
    f_shape_calc: float  # volume factor recovered from p_shape
    geom_weighted: float # 1 = use finite-length superellipse weighting
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
    # flux & channel physics (docs/30 P1)
    tau_eta: float    # classical (Spitzer) flux-diffusion time mu0 r_s^2/eta [s]
    tauN_o_taueta: float  # energy account vs flux account: which dies first
    tau_classical: float  # resistive classical cross-field bound [s] (optimistic)
    tau_Bohm: float       # Bohm-diffusion bound [s] (pessimistic)
    P_line: float     # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float; f_fast_ion: float; tau_eq_ie: float; P_ei: float
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


def _beta_fn(a: float, b: float) -> float:
    """Beta(a,b) via the standard library to avoid a SciPy dependency."""
    return math.exp(math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))


def _frc_shape_factor_from_p(p: float) -> float:
    """Volume factor for |2z/l_s|^p + |r/r_s|^p = 1.

    The plasma volume is ``V = C(p) * pi * r_s**2 * l_s``.  The limits match
    the existing FRC input convention: ``C(2)=2/3`` for an ellipse and
    ``C(p)->1`` for a racetrack-like separatrix.
    """
    if p <= 0 or not math.isfinite(p):
        raise ValueError(f"p must be positive and finite (got {p})")
    return _beta_fn(1.0 / p, 1.0 + 2.0 / p) / p


def _frc_p_from_f_shape(f_shape: float, p_max: float = 1.0e6) -> float:
    """Invert the superellipse volume factor C(p)=f_shape."""
    f_min = 2.0 / 3.0
    if not f_min - 1e-12 <= f_shape <= 1.0 + 1e-12:
        raise ValueError(f"f_shape must be in [2/3, 1], got {f_shape}")
    if f_shape <= f_min + 1e-12:
        return 2.0
    if f_shape >= 1.0 - 1e-12:
        return p_max

    lo, hi = 2.0, 8.0
    while _frc_shape_factor_from_p(hi) < f_shape and hi < p_max:
        lo, hi = hi, min(hi * 2.0, p_max)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _frc_shape_factor_from_p(mid) < f_shape:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _frc_profile_factors(x_s: float, f_shape: float, n: int = 801) -> tuple[float, float, float, float, float]:
    """Finite-length FRC profile factors weighted by superellipse volume.

    The radial rigid-rotor profile is retained.  Only the volume element is
    changed from a cylinder ``2x dx`` to the separatrix-consistent
    ``2x(1-x^p)^(1/p) dx``.  K is then solved so the volume-averaged beta is
    still ``1 - x_s**2/2``.
    """
    p = _frc_p_from_f_shape(f_shape)
    x = np.linspace(0.0, 1.0, n)
    shell = np.clip(1.0 - x**p, 0.0, 1.0)
    weight = 2.0 * x * shell ** (1.0 / p)
    norm = float(np.trapezoid(weight, x))
    if norm <= 0.0:
        raise ValueError("invalid FRC superellipse volume weight")
    weight /= norm

    beta_avg = 1.0 - x_s**2 / 2.0
    u = 2.0 * x**2 - 1.0

    def avg_sech2(k: float) -> float:
        return float(np.trapezoid(weight / np.cosh(k * u) ** 2, x))

    lo, hi = 1e-4, 25.0
    if avg_sech2(lo) < beta_avg:
        K = lo
    else:
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if avg_sech2(mid) > beta_avg:
                lo = mid
            else:
                hi = mid
        K = 0.5 * (lo + hi)

    nrel = 1.0 / np.cosh(K * u) ** 2
    brel = np.abs(np.tanh(K * u))
    G1 = float(np.trapezoid(weight * nrel, x))
    G2 = float(np.trapezoid(weight * nrel * nrel, x))
    GB = float(np.trapezoid(weight * brel, x))
    return p, K, G1, G2, GB


def frc_shape_outlines(r_s, l_s, r_w, f_shape=0.85, n_theta=181, **_ignored) -> dict:
    """JSON-able FRC separatrix geometry for front-end shape views."""
    p = _frc_p_from_f_shape(float(f_shape))
    th = np.linspace(0.0, 2.0 * math.pi, n_theta)
    c, s = np.cos(th), np.sin(th)
    z = (l_s / 2.0) * np.sign(c) * np.abs(c) ** (2.0 / p)
    r = r_s * np.sign(s) * np.abs(s) ** (2.0 / p)
    rn = r_s / math.sqrt(2.0)
    return {
        "type": "frc",
        "mode": "superellipse",
        "p_shape": p,
        "f_shape_calc": _frc_shape_factor_from_p(p),
        "separatrix": {"z": z.tolist(), "r": r.tolist()},
        "wall": {
            "z": [-(l_s / 2.0) * 1.15, (l_s / 2.0) * 1.15],
            "r_upper": [r_w, r_w],
            "r_lower": [-r_w, -r_w],
        },
        "null_points": {"z": [0.0, 0.0], "r": [rn, -rn]},
    }


def solve_frc(r_s, l_s, r_w, B_e, Ti, Te, tauE=0.01, use_tauE=1.0,
              f_shape=0.85, fsig=1.0, geom_weighted=0.0,
              Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10,
              imp_name=None) -> FRCResult:
    """Evaluate the 0-D FRC power balance at one operating point.

    Parameters (SI / keV); see docs/25 §3.  ``f_shape`` interpolates the
    separatrix volume between ellipse (2/3) and racetrack (1).
    """
    rx = _REACTIONS[icase]

    # --- input-domain guards (audit P0: x_s >= 1 gives negative <beta>) ---
    if r_s <= 0 or l_s <= 0 or r_w <= 0:
        raise ValueError(f"r_s, l_s, r_w must be > 0 (got {r_s}, {l_s}, {r_w})")
    if r_s >= r_w:
        raise ValueError(f"need r_s < r_w: separatrix inside the wall "
                         f"(got r_s={r_s}, r_w={r_w})")
    manual_tauE = bool(use_tauE)
    if B_e <= 0 or Ti <= 0 or Te <= 0:
        raise ValueError(f"B_e, Ti, Te must be > 0 (got {B_e}, {Ti}, {Te})")
    if manual_tauE and tauE <= 0:
        raise ValueError(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    if not 2.0 / 3.0 - 1e-9 <= f_shape <= 1.0:
        raise ValueError(f"f_shape must be in [2/3, 1] (ellipse..racetrack), got {f_shape}")
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
    use_geom_weight = bool(geom_weighted)

    # ---------- geometry ----------
    x_s = r_s / r_w
    elongation = l_s / (2 * r_s)
    p_shape = _frc_p_from_f_shape(f_shape)
    f_shape_calc = _frc_shape_factor_from_p(p_shape)
    Vp = f_shape * math.pi * r_s**2 * l_s
    Sp = 2 * math.pi * r_s * l_s * (0.5 + 0.5 * f_shape)   # ellipse<->racetrack side area
    Sw = 2 * math.pi * r_w * l_s + 2 * math.pi * r_w**2

    # ---------- rigid-rotor profile from the average-beta theorem ----------
    beta_avg = 1.0 - x_s**2 / 2.0
    if use_geom_weight:
        p_shape, K, G1, G2, GB = _frc_profile_factors(x_s, f_shape)
        f_shape_calc = _frc_shape_factor_from_p(p_shape)
    else:
        K = _solve_K(beta_avg)
        tK = math.tanh(K)
        G1 = tK / K                          # <n>/n_m   (== beta_avg by construction)
        G2 = (tK - tK**3 / 3.0) / K          # <n^2>/n_m^2
        GB = math.log(math.cosh(K)) / K      # <|B|>/B_e
    GB_flux = math.log(math.cosh(K)) / K     # cross-section factor for trapped flux

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
             * (Zeff + 0.7936 * t + 1.874 * t**2 + 3 / math.sqrt(2) * t)
             * 1e-6 * Vp)
    B_int = B_e * GB
    Pcycl = (4.14e-7 * (ne_m * G1 / 1e20)**0.5 * Te**2.5 * B_int**2.5
             * (1 - Rw)**0.5 * r_s**-0.5 * (1 + 2.5 * Te / 511) * Vp)

    # ---------- confinement ----------
    if manual_tauE:
        tau_E = tauE
    else:
        # LSX empirical scaling (SI; docs/25 §5)
        tau_E = 3.2e-15 * elongation**0.5 * x_s**2 * r_s**2.1 * ne_m**0.6

    # ---------- stored energy & balance ----------
    Eth = 1.5 * (ni_m * Ti + ne_m * Te) * _KEV_J * G1 * Vp * 1e-6   # MJ
    Ptrans = Eth / tau_E
    # impurity line radiation (Mavrin; uniform T, <n^2> weighting like Pbrem)
    if imp_name is not None and nimp0 > 0:
        if imp_name not in _IMP_SPECIES:
            raise ValueError(f"unknown impurity species {imp_name!r}; have {_IMP_SPECIES}")
        P_line = float(ne_m * nimp0 * lz_line_net(imp_name, Te) * G2 * Vp * 1e-6)
    else:
        P_line = 0.0

    Pheat = Pbrem + Pcycl + P_line + Ptrans - rx["fion"] * Pfus
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0
    Pwall = (Pfus + Pheat) / Sw

    # ---------- FRC-specific engineering quantities ----------
    flux_p = math.pi * r_s**2 * B_e * GB_flux / 2.0  # trapped poloidal flux [Wb]
    v_th = math.sqrt(Ti * _KEV_J / mi)
    rho_ie = mi * v_th / (Z1 * QE * B_e)
    s_param = r_s / rho_ie

    # ---------- flux account (docs/30 P1-4): classical resistive bound ----------
    # Spitzer eta ~ 5.2e-5 Zeff lnL / Te[eV]^1.5 [Ohm m]; tau_eta = mu0 r_s^2/eta
    # is the CLASSICAL magnetic-diffusion scale — an optimistic upper bound
    # (experimental FRC flux decay is anomalous, i.e. faster).  tauN/tau_eta
    # tells which account goes bankrupt first: energy (>1) or flux (<1)... see docs.
    eta_sp = 5.2e-5 * Zeff * 17.0 / (Te * 1e3) ** 1.5
    tau_eta = MU0 * r_s**2 / eta_sp

    # transport BRACKET (docs/30 batch 3a): FRC confinement predictions span
    # orders of magnitude, so report the two physical bounds next to the LSX
    # regression instead of pretending one number is right.
    #   classical: D_perp ~ 2 eta_par p / B^2;  Bohm: D_B = T_e[eV]/(16 B);
    #   tau = r_s^2 / (4 D).  LSX tau_E should land inside the bracket.
    D_cl = 2.0 * eta_sp * (ni_m * Ti + ne_m * Te) * _KEV_J / B_e**2
    tau_classical = r_s**2 / (4.0 * D_cl)
    D_Bohm = Te * 1e3 / (16.0 * B_e)
    tau_Bohm = r_s**2 / (4.0 * D_Bohm)

    # two-temperature channel diagnostics (docs/30 P1-1; uniform T)
    Ecrit, f_fast, tau_eq, pei = twotemp_diagnostics(
        rx, ni_m, Te, Ti, n10, n20, nHe0, nimp0, Zimp, M)
    P_ei = pei * G2 * Vp * 1e-6          # <n^2>-weighted estimate [MW]

    return FRCResult(
        Pfus=Pfus, Pheat=Pheat, Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        Pbrem=Pbrem, Pcycl=Pcycl,
        Ptrans=Ptrans, Pn=Pn, Pwall=Pwall, Eth=Eth,
        tau_E=tau_E, ntau=ni_m * G1 * tau_E,
        K_rr=K, G1=G1, G2=G2, GB=GB,
        p_shape=p_shape, f_shape_calc=f_shape_calc,
        geom_weighted=1.0 if use_geom_weight else 0.0,
        beta=beta_avg, beta_null=1.0, x_s=x_s, elongation=elongation,
        s_param=s_param, flux_p=flux_p,
        B_int=B_int, ni0=ni_m, ne0=ne_m, nbar=nbar,
        Vp=Vp, Sp=Sp, Sw=Sw, Zeff=Zeff, M=M,
        tau_eta=tau_eta, tauN_o_taueta=tau_E / tau_eta,
        tau_classical=tau_classical, tau_Bohm=tau_Bohm, P_line=P_line,
        Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq, P_ei=P_ei,
        strcase=rx["name"],
    )
