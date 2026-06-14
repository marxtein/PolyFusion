"""0-D stellarator power balance — v4 (Scheme D: single near-axis geometry).

Tokamak-parity treatment (docs/27 + docs/28, mirroring docs/01 section by
section).  ONE analytic geometry: FIRST-ORDER NEAR-AXIS EXPANSION (Garren-
Boozer / Mercier, in the Landreman-Sengupta-Plunk form used by pyQSC) — the
standard analytic representation of modern optimized stellarators.  ``etabar``
(!= 0, REQUIRED) is the single shaping parameter; the cross-section elongation
is a DERIVED OUTPUT, not an input.  The axis is the 3-D Fourier curve
R = R0 + delta_h cos(N_fp phi), Z = -delta_h sin(N_fp phi) by default, or an
explicit ``rc``/``zs`` Fourier list for a custom axis.  The periodic sigma
equation is solved for the self-consistent on-axis transform, INCLUDING the
axis-torsion contribution and the full elongation profile e(phi) (see
polyfusion/nearaxis.py; validated to machine precision against pyQSC).  Volume
follows Pappus with the flux-conserving section area pi*a^2; surface areas use
the arclength-weighted elongation profile.

(The legacy rotating-ellipse / ``kappa_s`` mode was removed in Scheme D: it
left ``kappa_s`` inert in near-axis mode and ``delta_h`` blind to iota in
legacy mode.  See docs/superpowers/plans/2026-06-14-stellarator-scheme-d.md.)

Measured-machine overrides (D1): a real device that single-harmonic near-axis
cannot represent (W7-X quasi-isodynamic, LHD heliotron) supplies an explicit
``iota`` (> 0) used in the ISS04/Sudo closure, and optionally ``Vp_override`` /
``Sw_override`` (m^3 / m^2, > 0) to anchor the power account to the real
plasma geometry instead of the near-axis estimate.

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

from dataclasses import replace as _dc_replace

from ..constants import QE, MU0, MEC2
from ..reactivity import reactivity
from ..tokamak import _REACTIONS, twotemp_diagnostics, line_radiation_profile
from ..twotemp import solve_channel_balance
from ..nearaxis import solve_near_axis

_KEV_J = 1e3 * QE
_BETA_SOFT_LIMIT = 0.05   # ~5% soft stellarator beta limit (Mercier; can be exceeded)
_IOTA_MIN = 1e-6          # below this the configuration has no effective transform


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
    rhos = (0.22, 0.34, 0.46, 0.58, 0.70, 0.82, 0.94, 1.0)
    cuts = [(0.0, "φ=0"), (0.25, "φ=T/4"), (0.5, "φ=T/2")]
    sections = []

    def _section(label, elong, center_R, center_Z, boundary_R, boundary_Z):
        Rb = np.asarray(boundary_R)
        Zb = np.asarray(boundary_Z)
        surfaces = []
        for rho in rhos:
            Rrho = center_R + rho * (Rb - center_R)
            Zrho = center_Z + rho * (Zb - center_Z)
            surfaces.append({"rho": float(rho), "R": Rrho.tolist(), "Z": Zrho.tolist()})
        return {"label": label, "elong": float(elong), "R": Rb.tolist(),
                "Z": Zb.tolist(), "surfaces": surfaces}

    def _poly_area(R, Z):
        R, Z = np.asarray(R), np.asarray(Z)
        return 0.5 * abs(float(np.sum(R[:-1] * Z[1:] - R[1:] * Z[:-1])))

    def _fourier_section(Rc, Zc, sx, sy, c2, c3, s2, s3, rot):
        x = sx * (np.cos(th) + c2 * np.cos(2 * th) + c3 * np.cos(3 * th))
        y = sy * (np.sin(th) + s2 * np.sin(2 * th) + s3 * np.sin(3 * th))
        area = _poly_area(x, y)
        if area > 0:
            scale = math.sqrt((math.pi * a**2) / area)
            x, y = scale * x, scale * y
        Rsec = Rc + x * math.cos(rot) - y * math.sin(rot)
        Zsec = Zc + x * math.sin(rot) + y * math.cos(rot)
        return Rsec, Zsec

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
            sections.append(_section(label, na.elongation[j], na.R0_arr[j],
                                     na.Z0_arr[j], Rsec, Zsec))
        axis = {"R": na.R0_arr[::6].tolist(), "Z": na.Z0_arr[::6].tolist()}
        mode = "near-axis"
    else:
        display = {
            0.0: dict(sx=0.42 * a, sy=1.05 * a, c2=-0.36, c3=0.10,
                      s2=0.04, s3=-0.04, rot=-0.05),
            0.25: dict(sx=0.80 * a, sy=0.58 * a, c2=0.18, c3=-0.08,
                       s2=0.16, s3=0.03, rot=0.48),
            0.5: dict(sx=1.10 * a, sy=0.35 * a, c2=0.12, c3=-0.05,
                      s2=0.12, s3=-0.02, rot=0.02),
        }
        for frac, label in cuts:
            phi_c = frac * 2 * math.pi / N_fp
            Rc = R0 + delta_h * math.cos(N_fp * phi_c)
            Zc = delta_h * math.sin(N_fp * phi_c)
            Rsec, Zsec = _fourier_section(Rc, Zc, **display[frac])
            sections.append(_section(label, kappa_s, Rc, Zc, Rsec, Zsec))
        axis = {"R": [R0 + delta_h, R0, R0 - delta_h],
                "Z": [0.0, delta_h, 0.0]}
        mode = "fourier-display"
    return {"mode": mode, "metric_mode": "near-axis" if etabar else "rotating-ellipse",
            "a": a, "g": g, "sections": sections, "axis": axis}


def _ellipse_perimeter(amaj, amin):
    """Ramanujan's approximation (works elementwise on numpy arrays)."""
    h = ((amaj - amin) / (amaj + amin)) ** 2
    return math.pi * (amaj + amin) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h)))


def stellarator_geometry_metrics(R0, A, N_fp, rc, zs, etabar, g=0.1,
                                 n_rho=101) -> dict:
    """Analytic stellarator geometry metrics shared by solver and UI.

    Single near-axis (Garren-Boozer) path (Scheme D): the axis is the custom
    Fourier curve ``rc``/``zs`` and ``etabar`` is the sole shaping knob — the
    transform AND elongation profile come from the self-consistent sigma
    equation.  ``A_flux`` is the first-order flux-section area used by the 0-D
    account.  The R-Z outlines returned by ``section_outlines`` are display
    projections; their projected polygon area is diagnostic, not the volume
    integral.
    """
    a = R0 / A
    A_flux = math.pi * a**2
    na = solve_near_axis(rc, zs, int(round(N_fp)), etabar)
    L_ax = na.axis_length
    iota_geom = abs(na.iota)
    helicity = float(na.helicity)
    kappa_eff = na.mean_elongation
    elong_max = na.max_elongation
    e = na.elongation
    w_axis = na.d_l_d_phi
    per_p = float(np.sum(_ellipse_perimeter(a * np.sqrt(e), a / np.sqrt(e)) * w_axis)
                  / np.sum(w_axis))
    per_w = float(np.sum(_ellipse_perimeter(a * np.sqrt(e) + g, a / np.sqrt(e) + g) * w_axis)
                  / np.sum(w_axis))
    mode = "near-axis"

    rho = np.linspace(0.0, 1.0, n_rho)
    profile_weight = 2.0 * rho
    return {
        "mode": mode,
        "A_flux": A_flux,
        "C_sec_mean": per_p,
        "C_wall_mean": per_w,
        "L_ax": L_ax,
        "Vp_geom": A_flux * L_ax,
        "Sp_geom": per_p * L_ax,
        "Sw_geom": per_w * L_ax,
        "profile_rho": rho.tolist(),
        "profile_weight": profile_weight.tolist(),
        "iota_geom": iota_geom,
        "helicity": helicity,
        "kappa_eff": kappa_eff,
        "elong_max": elong_max,
    }


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
    Ptrans: float
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
    A_flux: float     # analytic flux-section area [m^2]
    C_sec_mean: float # arclength-weighted plasma section perimeter [m]
    C_wall_mean: float # arclength-weighted wall section perimeter [m]
    Vp_geom: float    # geometry-helper plasma volume [m^3]
    Sp_geom: float    # geometry-helper plasma surface area [m^2]
    Sw_geom: float    # geometry-helper wall surface area [m^2]
    ne0: float
    nbar: float
    M: float
    Zeff: float
    N_fp: float       # field periods (echo)
    etabar: float     # near-axis shaping parameter (echo; required != 0)
    P_line: float     # impurity line radiation [MW] (0 unless imp_name given)
    Ecrit: float      # Stix critical energy of the fast product [keV]
    f_fast_ion: float # fraction of fast-product energy deposited on ions
    tau_eq_ie: float  # ion-electron equilibration time [s]
    P_ei: float       # ion->electron exchange power [MW] (diagnostic)
    Te0: float        # central electron temperature actually used [keV]
    fT_used: float    # Te0/Ti0 actually used (input, or solved when fT=0)
    te_mode: float    # 0 = fT input, 1 = solved, 0.5 = pinned (not converged)
    te_resid: float   # electron-channel residual at solution [MW]
    tauE_used: float  # confinement time actually used [s]
    taue_mode: float  # 0 = tauE input, 1 = solved from ISS04 (tauE=0)
    strcase: str

    def as_dict(self) -> dict:
        return asdict(self)


def _check_inputs(R0, A, N_fp, delta_h, Sn, ST, fT, B0, tauE,
                  f1, fHe, fimp, Zimp, Rw, g, fsig, etabar):
    """Domain guards (audit P0).  Raise ValueError on unphysical inputs so
    that no complex/inf/NaN value can masquerade as a result."""
    if R0 <= 0 or A <= 0:
        raise ValueError(f"R0 and A must be > 0 (got R0={R0}, A={A})")
    if etabar == 0.0:
        raise ValueError("etabar must be != 0: near-axis shaping is required "
                         "(legacy rotating-ellipse mode was removed in Scheme D)")
    if N_fp < 1:
        raise ValueError(f"N_fp must be >= 1 (got {N_fp})")
    if delta_h < 0 or delta_h >= R0:
        raise ValueError(f"delta_h must satisfy 0 <= delta_h < R0 (got {delta_h})")
    if Sn < 0 or ST < 0:
        raise ValueError(f"profile exponents must be >= 0 (got Sn={Sn}, ST={ST})")
    if fT < 0:
        raise ValueError(f"fT must be >= 0 (got {fT}; 0 = solve Te self-consistently)")
    if B0 <= 0 or tauE < 0:
        raise ValueError(f"B0 must be > 0 and tauE >= 0 "
                         f"(got B0={B0}, tauE={tauE}; tauE=0 = solve from ISS04)")
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


def solve_stellarator(R0, A, N_fp, Sn, ST, ni0, Ti0, fT, fsig, f1,
                      B0, tauE, fHe, fimp, Zimp, Rw, g, icase,
                      delta_h=0.0, iota=None, f_ren=1.0,
                      etabar=0.05, imp_name=None, f_aux_e=0.5,
                      H_fac=1.0, use_tauE=1.0,
                      rc=None, zs=None, Vp_override=0.0,
                      Sw_override=0.0) -> StellaratorResult:
    """Evaluate the 0-D stellarator power balance at one operating point.

    Single near-axis (Garren-Boozer) geometry (Scheme D).  ``etabar`` [1/m] is
    the sole shaping knob; elongation is a derived OUTPUT.  The magnetic axis is
    the Fourier curve ``rc``/``zs`` (default rc=[R0, delta_h], zs=[0, -delta_h]
    built from the helical excursion ``delta_h``); iota and the elongation
    profile come from the self-consistent sigma equation.

    ``N_fp`` = number of field periods (5 for W7-X/HELIAS, 4 for HSX, 10 for
    LHD, 2 for CFQS).  ``iota`` (optional, > 0) overrides the geometric
    transform for machines with a measured value; ``Vp_override`` /
    ``Sw_override`` (> 0) override the geometric plasma volume / wall surface
    for measured machines.
    """
    rx = _REACTIONS[icase]
    _check_inputs(R0, A, N_fp, delta_h, Sn, ST, fT, B0, tauE,
                  f1, fHe, fimp, Zimp, Rw, g, fsig, etabar)
    if iota is not None and iota != 0 and iota < 0:
        raise ValueError(f"explicit iota must be > 0 (got {iota})")
    if not 0.0 <= f_aux_e <= 1.0:
        raise ValueError(f"f_aux_e must be in [0, 1] (got {f_aux_e})")
    if H_fac <= 0:
        raise ValueError(f"H_fac must be > 0 (got {H_fac})")
    manual_tauE = bool(use_tauE)
    if manual_tauE and tauE <= 0:
        raise ValueError(f"tauE must be > 0 when use_tauE is enabled (got {tauE})")
    if not manual_tauE:
        tauE = 0.0

    # tauE = 0: solve the confinement time PREDICTIVELY from ISS04 — find
    # tauE such that H_ISS04 = H_fac (implicit: tau_ISS04 depends on P_L)
    if tauE == 0:
        def _eval_t(t):
            return solve_stellarator(R0, A, N_fp, Sn, ST, ni0, Ti0,
                                     fT, fsig, f1, B0, t, fHe, fimp, Zimp,
                                     Rw, g, icase, delta_h=delta_h, iota=iota,
                                     f_ren=f_ren, etabar=etabar,
                                     imp_name=imp_name, f_aux_e=f_aux_e,
                                     H_fac=H_fac, use_tauE=1.0,
                                     rc=rc, zs=zs, Vp_override=Vp_override,
                                     Sw_override=Sw_override)

        def _resid_t(t, res):
            return H_fac - res.H_ISS04

        t, res, r, conv = solve_channel_balance(_eval_t, _resid_t, 1e-3, 50.0)
        return _dc_replace(res, taue_mode=1.0 if conv else 0.5, tauE_used=t)

    # fT = 0: solve Te self-consistently from the electron-channel balance
    # (docs/30 batch 2; same closure as the tokamak — shared loss structure)
    if fT == 0:
        def _eval(ft):
            return solve_stellarator(R0, A, N_fp, Sn, ST, ni0, Ti0,
                                     ft, fsig, f1, B0, tauE, fHe, fimp, Zimp,
                                     Rw, g, icase, delta_h=delta_h, iota=iota,
                                     f_ren=f_ren, etabar=etabar,
                                     imp_name=imp_name, f_aux_e=f_aux_e,
                                     H_fac=H_fac, use_tauE=1.0,
                                     rc=rc, zs=zs, Vp_override=Vp_override,
                                     Sw_override=Sw_override)

        def _resid(ft, res):
            Eth_e = 1.5 * res.ne0 * ft * Ti0 * 1e3 * QE / (1 + Sn + ST) * res.Vp * 1e-6
            heat = ((1 - res.f_fast_ion) * (res.Pfus - res.Pn) + res.P_ei
                    + f_aux_e * max(res.Pheat, 0.0))
            return heat - (res.Pbrem + res.Pcycl + res.P_line + Eth_e / tauE)

        ft, res, r, conv = solve_channel_balance(_eval, _resid, 0.03, 2.5)
        return _dc_replace(res, te_mode=1.0 if conv else 0.5, te_resid=r,
                           fT_used=ft, Te0=ft * Ti0)

    a = R0 / A
    axis_rc = list(rc) if rc is not None else [R0, delta_h]
    axis_zs = list(zs) if zs is not None else [0.0, -delta_h]
    geom = stellarator_geometry_metrics(R0, A, N_fp, axis_rc, axis_zs, etabar, g)
    L_ax = geom["L_ax"]; iota_geom = geom["iota_geom"]
    helicity = geom["helicity"]; kappa_eff = geom["kappa_eff"]; elong_max = geom["elong_max"]
    Vp = Vp_override if (Vp_override and Vp_override > 0) else geom["Vp_geom"]
    Sp = geom["Sp_geom"]
    Sw = Sw_override if (Sw_override and Sw_override > 0) else geom["Sw_geom"]
    iota_used = iota if (iota is not None and iota > 0) else iota_geom
    if iota_used <= _IOTA_MIN:
        raise ValueError("rotational transform is ~0: give an explicit iota "
                         "override (measured machine) or shaping that produces "
                         "transform (etabar + helical/multi-harmonic axis)")

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
        nbar_o_Sudo=nbar_o_Sudo, Pbrem=Pbrem, Pcycl=Pcycl, Ptrans=Pth, Vp=Vp,
        iota=iota_used, iota_geom=iota_geom, helicity=helicity, L_ax=L_ax,
        kappa_eff=kappa_eff, elong_max=elong_max, tau_ISS04=tau_ISS04,
        Sp=Sp, Sw=Sw, A_flux=geom["A_flux"], C_sec_mean=geom["C_sec_mean"],
        C_wall_mean=geom["C_wall_mean"], Vp_geom=geom["Vp_geom"],
        Sp_geom=geom["Sp_geom"], Sw_geom=geom["Sw_geom"],
        ne0=ne0, nbar=nbar, M=M, Zeff=Zeff,
        N_fp=N_fp, etabar=etabar,
        P_line=P_line, Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq,
        P_ei=P_ei, Te0=Te0, fT_used=fT, te_mode=0.0, te_resid=0.0,
        tauE_used=tauE, taue_mode=0.0, strcase=rx["name"],
    )
