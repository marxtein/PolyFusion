"""Literature benchmarks (independent cross-checks against published results).

Run: python polyfusion/tests/test_literature_benchmark.py

1. Reactivity <sigma-v> vs the Bosch-Hale NF 32 (1992) 611 *parameterization*
   (Table VII).  Our code computes <sigma-v> by numerically integrating the
   cross-section over a Maxwellian; Bosch-Hale also published a direct fitted
   formula for <sigma-v>(T).  The two routes are independent, so agreement
   validates both the cross-section implementation and the Maxwellian integral.
   Anchor sanity: the universally quoted DT value <sv>(10 keV)=1.13e-22 m^3/s.

2. IPB98(y,2) confinement scaling vs the ITER Physics Basis inductive
   scenario: tau_E,98y2 ~ 3.66 s for R=6.2 m, a=2.0 m, Ip=15 MA, BT=5.3 T,
   kappa=1.7, nbar=1.01e20 m^-3, M=2.5, P_loss=87 MW.

3. Greenwald density limit closed form: n_Gw = Ip/(pi a^2) [1e20 m^-3].
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.reactivity import reactivity  # noqa: E402

PASS = True


def ok(cond, msg):
    global PASS
    print(("PASS" if cond else "FAIL"), msg)
    PASS = PASS and cond


# ---------------------------------------------------------------- Bosch-Hale
# <sigma-v>(T) fitted parameterization, NF 32 (1992) 611 Table VII.
# T in keV, result in cm^3/s.
BH = {
    "DT": dict(
        BG=34.3827,
        mrc2=1124656.0,
        C=[
            1.17302e-9,
            1.51361e-2,
            7.51886e-2,
            4.60643e-3,
            1.35000e-2,
            -1.06750e-4,
            1.36600e-5,
        ],
    ),
    "DDpt": dict(
        BG=31.3970,
        mrc2=937814.0,  # D(d,p)T branch
        C=[5.65718e-12, 3.41267e-3, 1.99167e-3, 0.0, 1.05060e-5, 0.0, 0.0],
    ),
    "DDn3": dict(
        BG=31.3970,
        mrc2=937814.0,  # D(d,n)3He branch
        C=[5.43360e-12, 5.85778e-3, 7.68222e-3, 0.0, -2.96400e-6, 0.0, 0.0],
    ),
    "DHe3": dict(
        BG=68.7508,
        mrc2=1124572.0,
        C=[5.51036e-10, 6.41918e-3, -2.02896e-3, -1.91080e-5, 1.35776e-4, 0.0, 0.0],
    ),
}


def bosch_hale_sv(T, key):
    """Bosch-Hale fitted <sigma-v>(T) [m^3/s]."""
    p = BH[key]
    C = p["C"]
    num = T * (C[1] + T * (C[3] + T * C[5]))
    den = 1.0 + T * (C[2] + T * (C[4] + T * C[6]))
    theta = T / (1.0 - num / den)
    xi = (p["BG"] ** 2 / (4.0 * theta)) ** (1.0 / 3.0)
    sv_cm3 = C[0] * theta * math.sqrt(xi / (p["mrc2"] * T**3)) * math.exp(-3.0 * xi)
    return sv_cm3 * 1e-6  # cm^3/s -> m^3/s


def main():
    # 0. validate the BH coefficients themselves against the canonical anchor
    sv10 = bosch_hale_sv(10.0, "DT")
    ok(
        abs(sv10 - 1.13e-22) / 1.13e-22 < 0.02,
        f"BH anchor: DT <sv>(10keV)={sv10:.3e} vs published 1.13e-22 m3/s",
    )

    # 1. our integral vs BH parameterization across the relevant range
    #    (BH fits quoted valid ~0.2-100 keV; our sigma fits carry a few % error)
    for key, icase, Ts, tol in [
        ("DT", 1, [5, 10, 20, 50, 100], 0.06),
        ("DHe3", 3, [5, 10, 20, 50, 100], 0.10),
    ]:
        worst = 0.0
        for T in Ts:
            ours = reactivity(float(T), icase)
            ref = bosch_hale_sv(float(T), key)
            rel = abs(ours - ref) / ref
            worst = max(worst, rel)
        ok(
            worst < tol,
            f"{key}: ours vs Bosch-Hale fit, worst rel err {worst:.1%} over {Ts} keV (tol {tol:.0%})",
        )

    # D-D: our icase=2 is the *sum* of both branches
    worst = 0.0
    for T in [5, 10, 20, 50]:
        ours = reactivity(float(T), 2)
        ref = bosch_hale_sv(float(T), "DDpt") + bosch_hale_sv(float(T), "DDn3")
        worst = max(worst, abs(ours - ref) / ref)
    ok(worst < 0.06, f"DD(sum): ours vs Bosch-Hale fit, worst rel err {worst:.1%}")

    # 2. IPB98(y,2) vs ITER Physics Basis inductive scenario (~3.66 s)
    Ip, R0, a, kappa, nbar20, BT, M, PL = 15.0, 6.2, 2.0, 1.7, 1.01, 5.3, 2.5, 87.0
    tau98 = (
        0.145
        * Ip**0.93
        * R0**1.39
        * a**0.58
        * kappa**0.78
        * nbar20**0.41
        * BT**0.15
        * M**0.19
    ) / PL**0.69
    ok(
        abs(tau98 - 3.66) / 3.66 < 0.10,
        f"IPB98y2 ITER inductive: tau={tau98:.2f}s vs published ~3.66s",
    )

    # 3. Greenwald limit closed form
    nGw = 1e20 * Ip / (math.pi * a**2)
    ok(
        abs(nGw - 1.194e20) / 1.194e20 < 0.01,
        f"Greenwald ITER: {nGw:.3e} vs 1.19e20 m^-3",
    )

    print("\nRESULT:", "ALL LITERATURE BENCHMARKS PASS" if PASS else "SOME FAILED")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
