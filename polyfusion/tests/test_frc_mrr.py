"""FRC Ma-Xie paper separatrix geometry verification (docs/superpowers/specs/
2026-06-16-frc-mrr-geometry-design.md).

Run: python polyfusion/tests/test_frc_mrr.py

The paper separatrix (Ma/Xie GSEQ-FRC, arXiv:2103.00839) is the revolution of
    r(z) = r_s * (1 - |z/(l_s/2)|^m)^(1/2),   m=2 ellipse, large m racetrack.
Volume factor is m/(m+1) == f_shape (exact bijection f_shape=m/(m+1)).  Used as
an OPTIONAL geometry mode sep_model="ma_xie"; the legacy value "mrr" remains
an accepted alias.  The default superellipse path must stay numerically unchanged.
"""

import math
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs import solve_frc  # noqa: E402
from polyfusion.configs.frc import (  # noqa: E402
    _f_shape_from_m,
    _m_from_f_shape,
    _mrr_volume,
    _mrr_surface,
    _mrr_profile_factors,
)

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


def main():
    # ---- 1. m <-> f_shape bijection ----
    ok(abs(_f_shape_from_m(2.0) - 2.0 / 3.0) < 1e-12, "m=2 -> f_shape=2/3 (ellipse)")
    ok(_f_shape_from_m(1e6) > 0.999, "large m -> f_shape -> 1 (racetrack)")
    ok(abs(_m_from_f_shape(2.0 / 3.0) - 2.0) < 1e-9, "f_shape=2/3 -> m=2")
    # 2. round-trip identity
    for f in (0.70, 0.85, 0.97):
        ok(
            abs(_f_shape_from_m(_m_from_f_shape(f)) - f) < 1e-9,
            f"f_shape={f}: f->m->f round-trip",
        )
    # 3. f_shape=1 maps to finite m_max, no overflow
    m1 = _m_from_f_shape(1.0)
    ok(math.isfinite(m1) and m1 >= 1e6 - 1, f"f_shape=1 -> finite m_max ({m1:g})")

    # ---- 4. Ma-Xie numeric volume == closed form m/(m+1) pi r_s^2 l_s ----
    for m in (2.0, 4.0, 20.0):
        r_s, l_s = 0.5, 5.0
        V_num = _mrr_volume(r_s, l_s, m)
        V_cf = math.pi * r_s**2 * l_s * m / (m + 1.0)
        ok(
            abs(V_num - V_cf) / V_cf < 1e-6,
            f"m={m}: Ma-Xie volume numeric {V_num:.6f} == closed form {V_cf:.6f}",
        )

    # ---- 5. m=2 surface == prolate-spheroid analytic reference ----
    r_s, l_s = 0.5, 5.0  # a=r_s=0.5, c=l_s/2=2.5 (prolate, c>a)
    a, c = r_s, l_s / 2.0
    e = math.sqrt(1.0 - a**2 / c**2)
    S_spheroid = 2 * math.pi * a**2 * (1.0 + (c / (a * e)) * math.asin(e))
    S_num = _mrr_surface(r_s, l_s, 2.0, 4001)
    ok(
        abs(S_num - S_spheroid) / S_spheroid < 1e-3,
        f"m=2 Ma-Xie surface {S_num:.5f} == prolate spheroid {S_spheroid:.5f}",
    )

    # ---- 6. Ma-Xie profile factors bounded and ordered ----
    K, G1, G2, GB = _mrr_profile_factors(0.5, _m_from_f_shape(0.85))
    ok(
        K > 0 and 0.0 < G2 <= G1 <= 1.0 and 0.0 < GB < 1.0,
        f"Ma-Xie profile factors bounded/ordered (K={K:.3f}, G1={G1:.3f}, G2={G2:.3f}, GB={GB:.3f})",
    )

    # ---- 7/8. Ma-Xie vs superellipse at equal f_shape: Vp identical, Pfus differs ----
    base = dict(r_s=0.5, l_s=5.0, r_w=0.7, B_e=3.5, Ti=15.0, Te=12.0, tauE=0.013)
    se = solve_frc(f_shape=0.85, sep_model="superellipse", **base)
    mr = solve_frc(f_shape=0.85, sep_model="ma_xie", **base)
    ok(mr.sep_model == "ma_xie", "Ma-Xie is the canonical sep_model value")
    ok(
        abs(se.Vp - mr.Vp) / se.Vp < 1e-6,
        "Ma-Xie Vp == superellipse Vp at equal f_shape",
    )
    ok(
        abs(se.Pfus - mr.Pfus) / se.Pfus > 1e-6,
        "Ma-Xie Pfus differs from superellipse (G factors)",
    )
    legacy = solve_frc(f_shape=0.85, sep_model="mrr", **base)
    ok(legacy.sep_model == "ma_xie", "legacy sep_model='mrr' canonicalizes to ma_xie")

    # ---- 9. Ma-Xie Sp finite, positive, < Sw ----
    ok(
        math.isfinite(mr.Sp) and mr.Sp > 0 and mr.Sp < mr.Sw,
        f"Ma-Xie Sp finite, positive, < Sw (Sp={mr.Sp:.4f}, Sw={mr.Sw:.4f})",
    )

    # ---- D. m honored in superellipse mode (sets f_shape=m/(m+1)) ----
    m_in = _m_from_f_shape(0.85)
    by_m = solve_frc(m=m_in, sep_model="superellipse", **base)
    ok(
        abs(by_m.Vp - se.Vp) / se.Vp < 1e-9,
        "m supplied in superellipse mode reproduces equal-f_shape result",
    )

    # ---- 10. default FRC path numerically UNCHANGED (regression baseline) ----
    d = solve_frc(
        r_s=0.5,
        l_s=5.0,
        r_w=0.7,
        B_e=3.5,
        Ti=15.0,
        Te=12.0,
        tauE=0.013,
        f_shape=0.85,
        geom_weighted=0.0,
    )
    ok(abs(d.Vp - 3.3379421944391554) < 1e-10, "default Vp unchanged")
    ok(abs(d.Pfus - 487.81477418624826) < 1e-6, "default Pfus unchanged")
    ok(abs(d.Sp - 14.529866022852794) < 1e-9, "default Sp unchanged")

    # ---- 11. invalid inputs fail cleanly ----
    def raises(fn):
        try:
            fn()
            return False
        except (ValueError, KeyError):
            return True

    ok(
        raises(lambda: solve_frc(sep_model="bad", **base, f_shape=0.85)),
        "sep_model='bad' rejected",
    )
    ok(raises(lambda: solve_frc(sep_model="ma_xie", m=1.5, **base)), "m<2 rejected")
    ok(
        raises(lambda: solve_frc(sep_model="ma_xie", m=2.0, f_shape=0.9, **base)),
        "inconsistent m and f_shape rejected",
    )

    print("\nRESULT:", "FRC Ma-Xie PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
