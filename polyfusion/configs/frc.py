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
    sep_model: str    # separatrix geometry family used ("superellipse" | "mrr")
    m_shape: float    # paper shape index (m=2 ellipse, large m racetrack)
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


# ---------------------------------------------------------------------------
# MRR (paper) separatrix geometry — Ma/Xie et al. GSEQ-FRC, arXiv:2103.00839.
# The FRC separatrix is the revolution about the z axis of
#     r(z) = r_s * (1 - |z/(l_s/2)|^m)^(1/2),   z in [-l_s/2, l_s/2],
# with shape index m: m=2 is an ellipse, large m is racetrack-like.  The volume
# factor is m/(m+1), identical to the existing f_shape via f_shape = m/(m+1).
# Added as an OPTIONAL geometry mode (sep_model="mrr"); the symmetric-
# superellipse path above is the default and stays numerically unchanged.
# ---------------------------------------------------------------------------

_M_MAX = 1.0e6   # racetrack limit; matches the superellipse p_max convention


def _f_shape_from_m(m: float) -> float:
    """Paper volume factor f_shape = m/(m+1)  (m=2 -> 2/3, m->inf -> 1)."""
    return m / (m + 1.0)


def _m_from_f_shape(f_shape: float, m_max: float = _M_MAX) -> float:
    """Invert f_shape = m/(m+1).  f_shape -> 1 is capped at a finite m_max."""
    if f_shape >= 1.0 - 1e-12:
        return m_max
    return f_shape / (1.0 - f_shape)


def _resolve_shape(f_shape, m, m_max: float = _M_MAX) -> tuple[float, float]:
    """Resolve the (f_shape, m) shape pair, MODE-INDEPENDENT (plan rev. D).

    ``m`` (paper shape index) takes precedence when given; an explicitly given
    ``f_shape`` must then agree with ``m/(m+1)``.  When only ``f_shape`` is
    given it sets ``m = f_shape/(1-f_shape)``.  When neither is given the FRC
    default ``f_shape=0.85`` is used.  Raises on ``m<2`` or an inconsistent pair.
    """
    if m is not None:
        if m < 2.0:
            raise ValueError(f"m must be >= 2 (ellipse floor m=2); got {m}")
        fm = _f_shape_from_m(float(m))
        if f_shape is not None and abs(float(f_shape) - fm) > 1e-6:
            raise ValueError(
                f"inconsistent m and f_shape: m={m} implies f_shape={fm:.6f}, "
                f"but f_shape={f_shape} was given")
        return fm, float(m)
    fs = 0.85 if f_shape is None else float(f_shape)
    if not 2.0 / 3.0 - 1e-9 <= fs <= 1.0:
        raise ValueError(f"f_shape must be in [2/3, 1] (got {fs})")
    return fs, _m_from_f_shape(fs, m_max)


def _mrr_separatrix(r_s: float, l_s: float, m: float, n: int = 4001):
    """(z, r) arrays of the paper separatrix on a uniform z grid in [-b, b]."""
    b = l_s / 2.0
    z = np.linspace(-b, b, n)
    r = r_s * np.sqrt(np.clip(1.0 - np.abs(z / b) ** m, 0.0, 1.0))
    return z, r


def _mrr_volume(r_s: float, l_s: float, m: float, n: int = 4001) -> float:
    """Numeric revolution volume int pi r(z)^2 dz (validates the closed form
    pi r_s^2 l_s m/(m+1))."""
    z, r = _mrr_separatrix(r_s, l_s, m, n)
    return float(np.trapezoid(math.pi * r * r, z))


def _mrr_surface(r_s: float, l_s: float, m: float, n: int = 4001) -> float:
    """Exact separatrix surface of revolution int 2 pi r sqrt(1 + r'^2) dz.

    The endpoints taper to points (r -> 0 at z = +-b) where r' -> inf, but the
    integrand is finite because r*r' stays finite.  Using r*r' in closed form
    avoids the 0*inf = nan a bare finite difference would produce (plan rev. E):
        r*r' = -(r_s^2 m / 2b) * sign(z) * |z/b|^(m-1).
    """
    b = l_s / 2.0
    z = np.linspace(-b, b, n)
    zb = np.abs(z / b)
    r = r_s * np.sqrt(np.clip(1.0 - zb ** m, 0.0, 1.0))
    rrp = -(r_s ** 2 * m / (2.0 * b)) * np.sign(z) * zb ** (m - 1.0)
    integrand = 2.0 * math.pi * np.sqrt(r * r + rrp * rrp)
    return float(np.trapezoid(integrand, z))


def _mrr_profile_factors(x_s: float, m: float, n: int = 801):
    """Rigid-rotor profile factors weighted by the MRR volume shell.

    Same structure as ``_frc_profile_factors`` but the volume element is the
    paper-separatrix shell ``w(x) ~ x (1 - x^2)^(1/m)`` (x = r/r_s) instead of
    the symmetric superellipse one.  K is solved so the volume-averaged beta is
    still ``1 - x_s^2/2``; G1/G2/GB therefore differ from the superellipse path,
    which is what changes the MRR-mode power account.
    """
    x = np.linspace(0.0, 1.0, n)
    shell = np.clip(1.0 - x ** 2, 0.0, 1.0)
    weight = 2.0 * x * shell ** (1.0 / m)
    norm = float(np.trapezoid(weight, x))
    if norm <= 0.0:
        raise ValueError("invalid MRR volume weight")
    weight /= norm

    beta_avg = 1.0 - x_s ** 2 / 2.0
    u = 2.0 * x ** 2 - 1.0

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
    return K, G1, G2, GB


# ---------------------------------------------------------------------------
# Nested poloidal flux surfaces (audit docs/42 P0+P1).
# The rigid-rotor MIDPLANE flux is analytic (integrate B_z/B_e = tanh(K u),
# u = 2 x^2 - 1, x = r/r_s):
#     psi_tilde(x) = ln[ cosh(K (2 x^2 - 1)) / cosh(K) ]     (drop the
# B_e r_s^2 / 4K prefactor; only the shape matters for labeling surfaces).
# psi=0 on the magnetic axis (x=0) and the separatrix radius (x=1); the minimum
# psi_o = -ln cosh K is the O point at x = 1/sqrt(2).  Interior flux surfaces
# are the level sets psi=const in (psi_o, 0); each level has TWO midplane radii
# x_in < 1/sqrt2 < x_out (closed form below).  For the 0-D shape view they are
# closed into cartoon loops around the O-point ring, radially anchored at their
# true flux radii (NOT a pure geometric guess); the rho=1 boundary is the drawn
# separatrix, so this never touches the power account.
# ---------------------------------------------------------------------------


def _rr_flux_norm(x, K: float):
    """Normalized rigid-rotor midplane flux psi_tilde(x) (0 at axis/separatrix,
    minimum -ln cosh K at the O point x=1/sqrt2)."""
    u = 2.0 * np.asarray(x, dtype=float) ** 2 - 1.0
    out = np.log(np.cosh(K * u) / math.cosh(K))
    return float(out) if np.ndim(x) == 0 else out


def _rr_flux_radii(psi_star: float, K: float) -> tuple[float, float]:
    """Two midplane radii (x_in, x_out) with psi_tilde = psi_star.

    Closed-form inverse of psi_tilde:  cosh(K(2x^2-1)) = cosh(K) e^{psi_star},
    so  2x^2 - 1 = +- arccosh(cosh K e^{psi_star}) / K.  Valid for
    psi_star in [psi_o, 0] (psi_o = -ln cosh K); clamped at the endpoints."""
    C = math.cosh(K) * math.exp(psi_star)
    A = math.acosh(max(C, 1.0)) / K           # in [0, 1]; 0 at O point, 1 at sep
    A = min(A, 1.0)
    x_out = math.sqrt(0.5 * (1.0 + A))
    x_in = math.sqrt(max(0.5 * (1.0 - A), 0.0))
    return x_in, x_out


def _frc_nested_surfaces(z_arch, r_arch, r_s: float, K: float,
                         n_levels: int = 8, n_theta: int = 161) -> list:
    """Closed interior flux-surface loops: rounded ovals around the O point ring.

    Real psi=const<0 surfaces are smooth ovals encircling the O point
    (r_o = r_s/sqrt2, z=0); they stay OFF the axis (psi=0 lives on r=0) — so a
    flat bottom on the axis would be unphysical.  We draw SELF-SIMILAR ellipses
    around the O point:

        r(phi) = r_o + a_r sin(phi),   z(phi) = a_z cos(phi).

    The bounding ellipse (level s=1) has a_r0 = r_s - r_o (top tangent to the
    arch at the midplane) and the largest a_z0 that still fits strictly inside
    the drawn arch ``r_arch(z_arch)`` (found by bisection).  Inner levels are
    scaled copies s*(a_r0, a_z0), so they are nested by construction and each is
    a subset of the bounding ellipse -> GUARANTEED inside the separatrix and
    never flat-bottomed.  The level fraction s is set from the analytic flux so
    the oval's midplane top radius equals the true flux radius x_out(psi)."""
    z_arch = np.asarray(z_arch, dtype=float)
    r_arch = np.asarray(r_arch, dtype=float)
    r_o = r_s / math.sqrt(2.0)
    b = float(np.max(np.abs(z_arch)))
    psi_o = -math.log(math.cosh(K))
    phi = np.linspace(0.0, 2.0 * math.pi, n_theta)
    cphi, sphi = np.cos(phi), np.sin(phi)
    a_r0 = r_s - r_o

    # largest a_z that keeps the bounding ellipse (a_r0) inside the arch
    def _fits(a_z: float) -> bool:
        z = a_z * cphi
        r = r_o + a_r0 * sphi
        return bool(np.all(r <= np.interp(z, z_arch, r_arch) + 1e-12))

    lo, hi = 0.0, b
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        if _fits(mid):
            lo = mid
        else:
            hi = mid
    a_z0 = 0.97 * lo                      # small margin so it reads as interior

    out = []
    for t in np.linspace(0.0, 1.0, n_levels + 2)[1:-1]:
        psi_star = psi_o * (1.0 - t)
        _x_in, x_out = _rr_flux_radii(psi_star, K)
        s = (x_out * r_s - r_o) / a_r0    # midplane top radius = flux x_out
        s = min(max(s, 1e-3), 1.0)
        z = s * a_z0 * cphi
        r = r_o + s * a_r0 * sphi
        out.append({"psi": float(psi_star), "z": z.tolist(), "r": r.tolist()})
    return out


def frc_shape_outlines(r_s, l_s, r_w, f_shape=None, n_theta=181,
                       sep_model="superellipse", m=None, **_ignored) -> dict:
    """JSON-able FRC separatrix geometry for front-end shape views.

    ``sep_model="superellipse"`` (default) draws the symmetric superellipse;
    ``sep_model="mrr"`` draws the paper (Ma/Xie) separatrix.
    """
    if sep_model not in ("superellipse", "mrr"):
        raise ValueError(f"sep_model must be 'superellipse' or 'mrr' (got {sep_model!r})")
    f_shape, m_shape = _resolve_shape(f_shape, m)
    rn = r_s / math.sqrt(2.0)
    b = l_s / 2.0
    wall = {
        "z": [-b * 1.15, b * 1.15],
        "r_upper": [r_w, r_w],
        "r_lower": [-r_w, -r_w],
    }
    # O point (magnetic axis / field null) at the null radius r_s/sqrt2; X points
    # where the separatrix meets the axis at z = +- l_s/2 (audit docs/42 P1).
    nulls = {"z": [0.0, 0.0], "r": [rn, -rn]}
    o_points = {"z": [0.0, 0.0], "r": [rn, -rn]}
    x_points = {"z": [b, -b], "r": [0.0, 0.0]}
    # nested interior flux surfaces around the O point (audit docs/42 P0).  K is
    # the rigid-rotor parameter at this x_s.  The ovals fit inside the SAME
    # separatrix arch the mode draws.  The upper (+r_o) and lower (-r_o) O-point
    # families are emitted as SEPARATE closed curves (merging them into one
    # polyline drew a spurious vertical connector across the axis).
    K = _solve_K(1.0 - (r_s / r_w) ** 2 / 2.0)
    za = np.linspace(-b, b, 91)
    if sep_model == "mrr":
        ra = r_s * np.sqrt(np.clip(1.0 - np.abs(za / b) ** m_shape, 0.0, 1.0))
    else:
        p_arch = _frc_p_from_f_shape(float(f_shape))
        ra = r_s * np.clip(1.0 - np.abs(za / b) ** p_arch, 0.0, 1.0) ** (1.0 / p_arch)
    half = _frc_nested_surfaces(za, ra, r_s, K)
    surfaces = []
    for srf in half:
        zr = srf["z"]; rr = np.asarray(srf["r"])
        surfaces.append({"psi": srf["psi"], "z": zr, "r": rr.tolist()})          # upper +r_o
        surfaces.append({"psi": srf["psi"], "z": zr, "r": (-rr).tolist()})       # lower -r_o
    common = {
        "type": "frc", "m_shape": float(m_shape), "f_shape_calc": f_shape,
        "wall": wall, "null_points": nulls,
        "o_points": o_points, "x_points": x_points, "surfaces": surfaces,
    }
    if sep_model == "mrr":
        zt, rt = _mrr_separatrix(r_s, l_s, m_shape, n_theta)
        z = np.concatenate([zt, zt[::-1]])
        r = np.concatenate([rt, -rt[::-1]])
        return {**common, "mode": "mrr",
                "separatrix": {"z": z.tolist(), "r": r.tolist()}}
    p = _frc_p_from_f_shape(float(f_shape))
    th = np.linspace(0.0, 2.0 * math.pi, n_theta)
    c, s = np.cos(th), np.sin(th)
    z = b * np.sign(c) * np.abs(c) ** (2.0 / p)
    r = r_s * np.sign(s) * np.abs(s) ** (2.0 / p)
    return {**common, "mode": "superellipse", "p_shape": p,
            "f_shape_calc": _frc_shape_factor_from_p(p),
            "separatrix": {"z": z.tolist(), "r": r.tolist()}}


def solve_frc(r_s, l_s, r_w, B_e, Ti, Te, tauE=0.01, use_tauE=1.0,
              f_shape=None, fsig=1.0, geom_weighted=0.0,
              Rw=0.8, icase=1, f1=0.5, fHe=0.0, fimp=0.0, Zimp=10,
              imp_name=None, sep_model="superellipse", m=None) -> FRCResult:
    """Evaluate the 0-D FRC power balance at one operating point.

    Parameters (SI / keV); see docs/25 §3.  ``f_shape`` interpolates the
    separatrix volume between ellipse (2/3) and racetrack (1).  ``sep_model``
    selects the separatrix geometry family: ``"superellipse"`` (default, the
    symmetric superellipse) or ``"mrr"`` (the Ma/Xie GSEQ-FRC paper separatrix,
    arXiv:2103.00839).  ``m`` is the paper shape index (>=2), interchangeable
    with ``f_shape`` via ``f_shape = m/(m+1)``.
    """
    if sep_model not in ("superellipse", "mrr"):
        raise ValueError(f"sep_model must be 'superellipse' or 'mrr' (got {sep_model!r})")
    f_shape, m_shape = _resolve_shape(f_shape, m)
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
    # wall surface is the same cylinder + endcaps for either separatrix model
    # (the first-wall load Pwall = (Pfus+Pheat)/Sw uses the WALL, not Sp).
    Sw = 2 * math.pi * r_w * l_s + 2 * math.pi * r_w**2
    beta_avg = 1.0 - x_s**2 / 2.0

    if sep_model == "mrr":
        # paper (Ma/Xie) separatrix: one boundary supplies Vp, Sp and the
        # volume-weighted profile factors.  Vp closed form == f_shape volume;
        # G1/G2/GB use the paper-shell weight (differs from the superellipse).
        Vp = math.pi * r_s**2 * l_s * m_shape / (m_shape + 1.0)
        Sp = _mrr_surface(r_s, l_s, m_shape)
        K, G1, G2, GB = _mrr_profile_factors(x_s, m_shape)
        # p_shape is a NOMINAL compatibility value only (the paper geometry is
        # NOT a symmetric superellipse, so no exact equivalent p exists).
        p_shape = _frc_p_from_f_shape(f_shape)
        f_shape_calc = f_shape
    else:
        p_shape = _frc_p_from_f_shape(f_shape)
        f_shape_calc = _frc_shape_factor_from_p(p_shape)
        Vp = f_shape * math.pi * r_s**2 * l_s
        Sp = 2 * math.pi * r_s * l_s * (0.5 + 0.5 * f_shape)   # ellipse<->racetrack side area
        # ---------- rigid-rotor profile from the average-beta theorem ----------
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
        Vp=Vp, Sp=Sp, Sw=Sw, sep_model=sep_model, m_shape=m_shape, Zeff=Zeff, M=M,
        tau_eta=tau_eta, tauN_o_taueta=tau_E / tau_eta,
        tau_classical=tau_classical, tau_Bohm=tau_Bohm, P_line=P_line,
        Ecrit=Ecrit, f_fast_ion=f_fast, tau_eq_ie=tau_eq, P_ei=P_ei,
        strcase=rx["name"],
    )
