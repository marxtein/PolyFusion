"""Every stellarator geometry parameter must change at least one core output.
Guards against the Scheme-D motivating bug (kappa_s dead in near-axis,
delta_h dead for iota in legacy).  Run: python polyfusion/tests/test_stellarator_param_activity.py
"""
import inspect, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.stellarator import solve_stellarator

ACCEPTED = set(inspect.signature(solve_stellarator).parameters)
# post-Scheme-D base: near-axis, etabar-driven, NO kappa_s
BASE = dict(R0=18.0, a=1.8, N_fp=5, delta_h=0.9, etabar=0.05, Sn=0.5, ST=1.0,
            ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5, B0=5.0, tauE=1.0,
            fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1)
EXPECT = {
    "R0":      ["Vp"], "a": ["Vp"], "N_fp": ["iota_geom"], "delta_h": ["iota_geom"],
    "etabar":  ["elong_max"], "g": ["Sw"], "B0": ["betaT"],
}

def _run(p): return solve_stellarator(**{k: v for k, v in p.items() if k in ACCEPTED}).as_dict()

def main():
    assert "kappa_s" not in ACCEPTED, "kappa_s must be removed from the solver"
    r0 = _run(BASE); ok = True
    for p, keys in EXPECT.items():
        q = dict(BASE); q[p] = BASE[p] * 1.2
        r = _run(q)
        moved = any(abs(r[k]-r0[k])/(abs(r0[k])+1e-30) > 1e-6 for k in keys)
        print(("PASS" if moved else "FAIL"), f"{p} moves {keys}")
        ok &= moved
    print("\nRESULT:", "ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
