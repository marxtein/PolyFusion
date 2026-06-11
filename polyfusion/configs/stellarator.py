"""0-D stellarator power balance — v3 (near-axis geometry upgrade).

Tokamak-parity treatment (docs/27 + docs/28, mirroring docs/01 section by
section).  TWO analytic geometry levels are supported:

* LEVEL 1 (legacy, ``etabar == 0``): ROTATING-ELLIPSE stellarator — elliptical
  cross-section of constant area pi*a^2 whose major axis rotates poloidally by
  (N_fp/2)*phi (Spitzer's classical analytic stellarator).  On-axis transform
  in closed form (validated against Floquet integration):
      iota0 = (N_fp/2) * (kappa_s - 1)^2 / (kappa_s^2 + 1).
  Limitation (audit docs/仿星器0D物理闭合性审核报告): the helical axis
  excursion ``delta_h`` only lengthens the axis here — its TORSION does not
  contribute to iota, and the ellipse/axis couplings are ignored.

* LEVEL 2 (``etabar != 0``): FIRST-ORDER NEAR-AXIS EXPANSION (Garren-Boozer /
  Mercier, in the Landreman-Sengupta-Plunk form used by pyQSC) — the standard
  analytic representation of modern optimized stellarators.  The axis is the
  3-D Fourier curve R = R0 + delta_h cos(N_fp phi), Z = -delta_h sin(N_fp phi)
  and the periodic sigma equation is solved for the self-consistent on-axis
  transform, INCLUDING the axis-torsion contribution and the full elongation
  profile e(phi) (see polyfusion/nearaxis.py; validated to machine precision
  against pyQSC published values).  Volume still follows Pappus with the
  flux-conserving section area pi*a^2 (first-order surfaces are ellipses of
  that area); surface areas use the arclength-weighted elongation profile.

* An explicit ``iota`` input (> 0) overrides the geometric value in the
  ISS04/Sudo closure for machines with measured transforms.
* PROFILES / REACTIVITY / RADIATION: identical to the tokamak core (already
  L3-verified); confinement closure stays ISS04 + Sudo (docs/23).

Input-domain guards (audit P0): composition, Rw, profile exponents and the
rotational transform are validated here even when the solver is called
directly, so no complex/inf/divide-by-zero "results" can escape.

References: Yamada NF 45 (2005) 1684 (ISS04); Sudo NF 30 (1990); Helander,
Rep. Prog. Phys. 77, 087001 (2014); Garren & Boozer, Phys. Fluids B 3 (1991)
2805; Landreman, Sengupta & Plunk, J. Plasma Phys. 85 (2019) 905850103.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np

from ..constants import QE, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS, twotemp_diagnostics, line_radiation_profile
from ..nearaxis import solve_near_axis

_KEV_J = 1e3 * QE
_BETA_SOFT_LIMIT = 0.05   # ~5% soft stellarator beta limit (Mercier; can be exceeded)
_IOTA_MIN = 1e-6          # below this the configuration has no effective transform


def iota_rotating_ellipse(kappa_s: float, N_fp: float) -> float:
    """On-axis rotational transform of a rotating-ellipse stellarator.

    Closed form from the near-axis Floquet problem: in the frame rotating
    with the ellipse (rate M = N_fp/2) the field-line equations become
    constant-coefficient with matrix [[eps, M], [-M, -eps]]; elliptical
    invariant curves of axis ratio kappa_s fix eps = M(k^2-1)/(k^2+1) and the
    lab-frame transform is M - sqrt(M^2 - eps^2) = M (k-1)^2/(k^2+1).
    (Equivalent to Mercier's vacuum formula M (cosh 2eta - 1)/cosh 2eta with
    kappa_s = e^{2 eta}, zero axis torsion.)
    """
    M = N_fp / 2.0
    k = kappa_s
    return M * (k - 1.0) ** 2 / (k * k + 1.0)


def axis_length(R0: float, N_fp: float, delta_h: float, n: int = 720) -> float:
    """Arc length of the (possibly helical) magnetic axis, numerically exact
    for the model R = R0 + delta_h cos(N_fp phi), Z = delta_h sin(N_fp phi)."""
    if delta_h <= 0:
        return 2 * math.pi * R0
    phi = np.linspace(0.0, 2 * math.pi, n)
    R = R0 + delta_h * np.cos(N_fp * phi)
    dR = -delta_h * N_fp * np.sin(N_fp * phi)
    dZ = delta_h * N_fp * np.cos(N_fp * phi)
    return float(np.trapezoid(np.sqrt(dR**2 + R**2 + dZ**2), phi))


def section_outlines(R0, A, kappa_s, N_fp, delta_h=0.0, etabar=0.0, g=0.1,
                     n_theta=121, **_ignored) -> dict:
    """Flux-surface cross-section outlines for the UI shape view.

    Returns ``{"mode", "sections": [{"label","R","Z"}...], "axis": {...}}``
    with cuts at phi = 0, quarter period and half period.

    * near-axis mode (etabar != 0): exact first-order surfaces
          P(theta) = axis + a [ X1(theta) n_hat + Y1(theta) b_hat ],
          X1 = (etabar/kappa) cos(theta),
          Y1 = (kappa/etabar) [ sigma cos(theta) + sin(theta) ],
      projected on the (R, Z) display plane — elongation AND orientation vary
      along the field period (sigma tilts the ellipse off the normal).
    * legacy mode: rotating ellipse, semi-axes a*sqrt(ks), a/sqrt(ks), major
      axis rotated by (N_fp/2)*phi, centred on the helical axis.

    Extra keyword arguments (the full parameter dict) are ignored so the
    caller can pass ``**params`` directly.
    """
    a = R0 / A
    th = np.linspace(0.0, 2 * math.pi, n_theta)
    cuts = [(0.0, "φ=0"), (0.25, "φ=T/4"), (0.5, "φ=T/2")]
    sections = []
    if etabar:
        na = solve_near_axis([R0, delta_h], [0.0, -delta_h],
                             int(round(N_fp)), etabar, nphi=121)
        period = 2 * math.pi / int(round(N_fp))
        for frac, label in cuts:
            j = int(np.argmin(np.abs(na.phi - frac * period)))
            kap, sig = na.curvature[j], na.sigma[j]
            X1 = (na.etabar / kap) * np.cos(th)
            Y1 = (kap / na.etabar) * (sig * np.cos(th) + np.sin(th))
            n_hat, b_hat = na.normal[:, j], na.binormal[:, j]
            Rsec = na.R0_arr[j] + a * (X1 * n_hat[0] + Y1 * b_hat[0])
            Zsec = na.Z0_arr[j] + a * (X1 * n_hat[2] + Y1 * b_hat[2])
            sections.append({"label": label, "elong": float(na.elongation[j]),
                             "R": Rsec.tolist(), "Z": Zsec.tolist()})
        axis = {"R": na.R0_arr[::6].tolist(), "Z": na.Z0_arr[::6].tolist()}
        mode = "near-axis"
    else:
        am, an = a * math.sqrt(kappa_s), a / math.sqrt(kappa_s)
        for frac, label in cuts:
            phi_c = frac * 2 * math.pi / N_fp
            rot = (N_fp / 2.0) * phi_c
            Rc = R0 + delta_h * math.cos(N_fp * phi_c)
            Zc = delta_h * math.sin(N_fp * phi_c)
            ex, ey = am * np.cos(th), an * np.sin(th)
            Rsec = Rc + ex * math.cos(rot) - ey * math.sin(rot)
            Zsec = Zc + ex * math.sin(rot) + ey * math.cos(rot)
            sections.append({"label": label, "elong": float(kappa_s),
                             "R": Rsec.tolist(), "Z": Zsec.tolist()})
        axis = {"R": [R0 + delta_h, R0, R0 - delta_h],
                "Z": [0.0, delta_h, 0.0]}
        mode = "rotating-ellipse"
    return {"mode": mode, "a": a, "g": g, "sections": sections, "axis": axis}


def _ellipse_perimeter(amaj, amin):
    """Ramanujan's approximation (works elementwise on numpy arrays)."""
    h = ((amaj - amin) / (amaj + amin)) ** 2
    return math.pi * (amaj + amin) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h)))


@dataclass
class StellaratorResult:
    Eth: float        # stored thermal energy [MJ]
    H_ISS04: float    # ISS04 confinement quality factor
    Pheat: float      # net external heating power [MW]
    Pn: float         # neutron power [MW]
    Pfus: float       # fusion power [MW]
    Pwall: float      # first-wall load [MW/m^2]
    Qfus: float       # fusion gain (capped at 1000; see Qfus_raw/ignited)
    Qfus_raw: float   # uncapped Pfus/Pheat (negative => ignited/over-driven)
    ignited: float    # 1 if Pheat <= 0 (alpha heating alone exceeds losses)
    betaT: float      # toroidal beta
    beta_o_limit: float   # betaT / 0.05 (soft-limit margin)
    nbar_o_Sudo: float    # line-avg density / Sudo limit
    Pbrem: float
    Pcycl: float
    Vp: float
    iota: float       # rotational transform actually used in the closure
    iota_geom: float  # transform from the analytic geometry
    helicity: float   # near-axis helicity (0 in rotating-ellipse mode)
    L_ax: float       # magnetic-axis length [m]
    kappa_eff: float  # effective section elongation used for areas
    elong_max: float  # maximum section elongation along the axis
    tau_ISS04: float  # ISS04 predicted confinement time [s]
    Sp: float
    Sw: float
    ne0: float
    nbar: float
    M: float
    Zeff: float
    kappa_s: float    # section elongation input (echo)
    N_fp: float       # field periods (echo)
    etabar: float     # near-axis shaping parameter (echo; 0 = legacy mode)
    P_line: float     # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float      # Stix critical energy of the fast product [keV]
    f_fast_ion: float # fraction of fast-product energy deposited on ions
    tau_eq_ie: float  # ion-electron equilibration time [s]
    P_ei: float       # ion->electron exchange power [MW] (diagnostic)
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def _check_inputs(R0, A, kappa_s, N_fp, delta_h, Sn, ST, fT, B0, tauE,
                  f1, fHe, fimp, Zimp, Rw, g, fsig, etabar):
    """Domain guards (audit P0).  Raise ValueError on unphysical inputs so
    that no complex/inf/NaN value can masquerade as a result."""
    if R0 <= 0 or A <= 0:
        raise ValueError(f"R0 and A must be > 0 (got R0={R0}, A={A})")
    if kappa_s <= 0:
        raise ValueError(f"kappa_s must be > 0 (got {kappa_s})")
    if N_fp < 1:
        raise ValueError(f"N_fp must be >= 1 (got {N_fp})")
    if delta_h < 0 or delta_h >= R0:
        raise ValueError(f"delta_h must satisfy 0 <= delta_h < R0 (got {delta_h})")
    if Sn < 0 or ST < 0:
        raise ValueError(f"profile exponents must be >= 0 (got Sn={Sn}, ST={ST})")
    if fT <= 0:
        raise ValueError(f"fT must be > 0 (got {fT})")
    if B0 <= 0 or tauE <= 0:
        raise ValueError(f"B0 and tauE must be > 0 (got B0={B0}, tauE={tauE})")
    if not 0.0 <= f1 <= 1.0:
        raise ValueError(f"f1 must be in [0, 1] (got {f1})")
    if fHe < 0 or fimp < 0 or fHe + fimp >= 1.0:
        raise ValueError(f"need fHe,fimp >= 0 and fHe+fimp < 1 (got {fHe}, {fimp})")
    if Zimp <= 0:
        raise ValueError(f"Zimp must be > 0 (got {Zimp})")
    if not 0.0 <= Rw <= 1.0:
        raise ValueError(f"wall reflectivity Rw must be in [0, 1] (got {Rw})")
    if g < 0:
        raise ValueError(f"wall gap g must be >= 0 (got {g})")
    if fsig < 0:
        raise ValueError(f"fsig must be >= 0 (got {fsig})")


def solve_stellarator(R0, A, kappa_s, N_fp, Sn, ST, ni0, Ti0, fT, fsig, f1,
                      B0, tauE, fHe, fimp, Zimp, Rw, g, icase,
                      delta_h=0.0, iota=None, f_ren=1.0,
                      etabar=0.0, imp_name=None) -> StellaratorResult:
    """Evaluate the 0-D stellarator power balance at one operating point.

    Geometry inputs replace the tokamak's (kappa, delta, Ip):
    ``kappa_s`` = elliptical section elongation (rotating-ellipse mode),
    ``N_fp`` = number of field periods (5 for W7-X/HELIAS, 4 for HSX,
    10 for LHD, 2 for CFQS), ``delta_h`` = helical axis excursion [m].

    ``etabar`` [1/m] activates the first-order NEAR-AXIS geometry (Garren-
    Boozer): axis rc=[R0, delta_h], zs=[0, -delta_h]; iota and the elongation
    profile then come from the sigma equation (kappa_s is ignored except as a
    drawing hint).  ``iota`` (optional, > 0) overrides the geometric transform
    for machines with measured values.
    """
    rx = _REACTIONS[icase]
    _check_inputs(R0, A, kappa_s, N_fp, delta_h, Sn, ST, fT, B0, tauE,
                  f1, fHe, fimp, Zimp, Rw, g, fsig, etabar)
    if iota is not None and iota != 0 and iota < 0:
        raise ValueError(f"explicit iota must be > 0 (got {iota})")
    a = R0 / A

    # --- geometry: near-axis (etabar != 0) or rotating ellipse (legacy) ---
    if etabar:
        if delta_h <= 0 and not (iota and iota > 0):
            raise ValueError("near-axis mode with a planar circular axis has "
                             "iota=0: set delta_h > 0 or give an explicit iota")
        na = solve_near_axis([R0, delta_h], [0.0, -delta_h],
                             int(round(N_fp)), etabar)
        L_ax = na.axis_length
        iota_geom = abs(na.iota)
        helicity = float(na.helicity)
        kappa_eff = na.mean_elongation
        elong_max = na.max_elongation
        # arclength-weighted mean perimeter of the (varying) elliptical section
        e = na.elongation
        w = na.d_l_d_phi
        per_p = float(np.sum(_ellipse_perimeter(a * np.sqrt(e), a / np.sqrt(e)) * w)
                      / np.sum(w))
        per_w = float(np.sum(_ellipse_perimeter(a * np.sqrt(e) + g, a / np.sqrt(e) + g) * w)
                      / np.sum(w))
    else:
        L_ax = axis_length(R0, N_fp, delta_h)
        iota_geom = iota_rotating_ellipse(kappa_s, N_fp)
        helicity = 0.0
        kappa_eff = kappa_s
        elong_max = kappa_s
        amaj, amin = a * math.sqrt(kappa_s), a / math.sqrt(kappa_s)
        per_p = float(_ellipse_perimeter(amaj, amin))
        per_w = float(_ellipse_perimeter(amaj + g, amin + g))

    Vp = math.pi * a**2 * L_ax                       # Pappus, constant section area
    Sp = per_p * L_ax
    Sw = per_w * L_ax

    # --- rotational transform actually used in the closure (overridable) ---
    iota_used = iota if (iota is not None and iota > 0) else iota_geom
    if iota_used <= _IOTA_MIN:
        raise ValueError(
            "rotational transform is zero: a kappa_s=1 rotating ellipse (or a "
            "planar near-axis configuration) has no closed flux surfaces in "
            "this model — increase kappa_s/delta_h/etabar or set iota > 0")

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
    Tx = Ti0 * (1 - x**2) ** ST
    sgv = reactivity(Tx, icase)
    Phi = fsig * 2 * float(np.sum((1 - x**2) ** (2 * Sn) * sgv * x * dx))
    Pfus = rx["Y"] / (1 + d12) * n10 * n20 * Phi * Vp * 1e-6
    Pn = Pfus * (1 - rx["fion"])

    # --- radiation (identical to funsc; a = area-equivalent radius) ---
    # NB grouping follows the JS/golden reference (tokamak.py): Zeff multiplies
    # only the leading e-i term; MATLAB groups the relativistic corrections
    # inside Zeff (~1% at Zeff~2) — documented in docs/27.
    Pbrem = (5.34e-37 * ne0**2 * math.sqrt(Te0)
             * (Zeff * (1 / (1 + 2 * Sn + 0.5 * ST))
                + 0.7936 / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2)
                + 1.874 / (1 + 2 * Sn + 2.5 * ST) * (Te0 / MEC2) ** 2
                + 3 / math.sqrt(2) / (1 + 2 * Sn + 1.5 * ST) * (Te0 / MEC2))
             * 1e-6 * Vp)
    neff = ne0 / 1e20 / (1 + Sn)
    Teff = Te0 * float(np.sum((1 - x**2) ** ST)) * dx
    Pcycl = (4.14e-7 * neff**0.5 * Teff**2.5 * B0**2.5 * (1 - Rw)**0.5
             * a**-0.5 * (1 + 2.5 * Teff / 511) * Vp)

    # --- impurity line radiation (Mavrin; opt-in, docs/30 P1-2) ---
    P_line = line_radiation_profile(imp_name, ne0, nimp0, Te0, Sn, ST, Vp, x, dx)

    # --- stored energy, heating, gain (identical structure) ---
    Eth = 1.5 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / (1 + Sn + ST) * Vp * 1e-6
    Pth = Eth / tauE
    Pheat = Pcycl + Pbrem + P_line + Pth - rx["fion"] * Pfus
    ignited = 1.0 if Pheat <= 0 else 0.0
    Qfus_raw = Pfus / Pheat if Pheat != 0 else math.inf
    Qfus = Pfus / Pheat if Pheat > 0 else 1000.0
    if Qfus <= 0 or Qfus > 1000:
        Qfus = 1000.0

    betaT = 2 * MU0 * (ni0 * Ti0 + ne0 * Te0) * 1e3 * QE / B0**2 / (1 + Sn + ST)
    nbar = ne0 * math.sqrt(math.pi) / 2 * math.gamma(Sn + 1) / math.gamma(Sn + 1.5)
    Pwall = (Pfus + Pheat) / Sw

    # --- stellarator closure: ISS04 + Sudo (verified docs/23) ---
    PL = rx["fion"] * Pfus + Pheat
    if PL > 0:
        tau_ISS04 = (0.134 * f_ren * a**2.28 * R0**0.64 * PL**-0.61
                     * (nbar / 1e19)**0.54 * B0**0.84 * iota_used**0.41)
        H_ISS04 = tauE / tau_ISS04
        n_Sudo = 0.25 * math.sqrt(PL * B0 / (a**2 * R0)) * 1e20
        nbar_o_Sudo = nbar / n_Sudo
    else:
        # losses fully covered without external+alpha heating: outside the
        # ISS04 database domain — flag with NaN rather than inf (audit P0)
        tau_ISS04 = float("nan")
        H_ISS04 = float("nan")
        nbar_o_Sudo = float("nan")

    # --- two-temperature channel diagnostics (docs/30 P1-1) ---
    Ecrit, f_fast, tau_eq, pei = twotemp_diagnostics(
        rx, ni0, Te0, Ti0, n10, n20, nHe0, nimp0, Zimp, M)
    P_ei = pei * Vp / (1 + 2 * Sn + ST) * 1e-6

    return StellaratorResult(
        Eth=Eth, H_ISS04=H_ISS04, Pheat=Pheat, Pn=Pn, Pfus=Pfus, Pwall=Pwall,
        Qfus=Qfus, Qfus_raw=Qfus_raw, ignited=ignited,
        betaT=betaT, beta_o_limit=betaT / _BETA_SOFT_LIMIT,
        nbar_o_Sudo=nbar_o_Sudo, Pbrem=Pbrem, Pcycl=Pcycl, Vp=Vp,
        iota=iota_used, iota_geom=iota_geom, helicity=helicity, L_ax=L_ax,
        kappa_eff=kappa_eff, elong_max=elong_max, tau_ISS04=tau_ISS04,
        Sp=Sp, Sw=Sw, ne0=ne0, nbar=nbar, M=M, Zeff=Zeff,
        kappa_s=kappa_s, N_fp=N_fp, etabar=etabar,
        P_line=P_line, Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq,
        P_ei=P_ei, strcase=rx["name"],
    )
