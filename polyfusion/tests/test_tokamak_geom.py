import math
import numpy as np
import pytest
from polyfusion import tokageom as tg


def test_revolution_metrics_circular_torus():
    # a circle of minor radius a at major radius R0 -> known torus
    R0, a = 6.0, 1.5
    th = np.linspace(0.0, 2 * np.pi, 2000, endpoint=False)
    R = R0 + a * np.cos(th)
    Z = a * np.sin(th)
    Vp, Sp = tg.revolution_metrics(R, Z)
    assert Vp == pytest.approx(2 * math.pi**2 * R0 * a**2, rel=1e-3)   # 2 pi^2 R a^2
    assert Sp == pytest.approx(4 * math.pi**2 * R0 * a, rel=1e-3)      # 4 pi^2 R a


def test_miller_boundary_volume_matches_known_torus():
    # ITER-like: R0=6.2, a=2.0 (A=3.1), kappa=1.7, delta=0.33
    R, Z = tg.miller_boundary(R0=6.2, a=2.0, kappa=1.7, delta=0.33, n_theta=720)
    Vp, Sp = tg.revolution_metrics(R, Z)
    # circular-limit cross-check: extent and elongation sane
    assert R.max() == pytest.approx(8.2, rel=1e-6)        # R0 + a
    assert R.min() == pytest.approx(4.2, rel=1e-6)        # R0 - a
    assert Z.max() == pytest.approx(1.7 * 2.0, rel=1e-6)  # kappa * a
    assert 700.0 < Vp < 820.0                              # validated CF/Miller ~786 m^3


def test_cf_limiter_matches_miller_and_has_shafranov():
    R0, a, kappa, delta = 6.2, 1.984, 1.7, 0.33     # eps = a/R0 = 0.32
    Rl, Zl, shaf_l = tg.cf_boundary(R0, a, kappa, delta, n_theta=600)
    Vl, _ = tg.revolution_metrics(Rl, Zl)
    Rm, Zm = tg.miller_boundary(R0, a, kappa, delta, n_theta=600)
    Vm, _ = tg.revolution_metrics(Rm, Zm)
    assert Vl == pytest.approx(Vm, rel=0.02)         # CF limiter ~ Miller
    assert 0.0 < shaf_l < a                          # outward Shafranov shift


def test_legacy_dispatch_matches_old_formula_exactly():
    R0, A, kappa, delta, g = 6.2, 3.1, 1.7, 0.33, 0.05
    a = R0 / A
    Ad = R0 / (g + a)
    Vp_old = (2 * math.pi**2 * kappa * (A - delta) + 16 * math.pi * kappa * delta / 3) * a**3
    Sp_old = (4 * math.pi**2 * A * kappa**0.65 - 4 * kappa * delta) * a**2
    Sw_old = (4 * math.pi**2 * Ad * kappa**0.65 - 4 * kappa * delta) * (a + g)**2
    out = tg.tokamak_geometry(0, R0, A, kappa, delta, g, 0, 0.0, 0.0)
    assert out["Vp"] == pytest.approx(Vp_old, rel=0, abs=1e-9)
    assert out["Sp"] == pytest.approx(Sp_old, rel=0, abs=1e-9)
    assert out["Sw"] == pytest.approx(Sw_old, rel=0, abs=1e-9)
    assert out["a"] == pytest.approx(a)


def test_dispatch_override_replaces_metric_keeps_geom_diagnostic():
    out = tg.tokamak_geometry(1, 6.2, 3.1, 1.7, 0.33, 0.05, None, 900.0, 700.0)
    assert out["Vp"] == 900.0          # override wins
    assert out["Sw"] == 700.0
    assert out["Vp_geom"] != 900.0     # integrated value still reported
    assert out["geom_volume_ratio"] == pytest.approx(out["Vp_geom"] / 900.0)


def test_funsc_legacy_default_unchanged_and_models_differ():
    from polyfusion.tokamak import funsc
    base = dict(R0=6.35, A=3.43, kappa=1.86, delta=0.5, Sn=0.5, ST=1.0,
                ni0=6.81e19, Ti0=25, fT=1.0, fsig=1.0, f1=0.5, BT0=5.18,
                Ip=9.2, tauE=2.0, fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7,
                g=0.05, icase=1)
    r0 = funsc(**base)                                   # default geom_model=0
    r0b = funsc(**base, geom_model=0)
    assert r0.Vp == pytest.approx(r0b.Vp, abs=1e-9)      # default == explicit legacy
    r1 = funsc(**base, geom_model=1)
    r2 = funsc(**base, geom_model=2)
    assert r1.Vp != pytest.approx(r0.Vp, rel=1e-6)        # Miller differs from fit
    assert r2.Vp == pytest.approx(r1.Vp, rel=0.02)        # CF limiter ~ Miller
    assert r2.shaf_shift > 0.0
    assert r1.geom_volume_ratio == pytest.approx(1.0)     # no override -> ratio 1


def test_shape_outlines_closed_and_wall_outside():
    out = tg.tokamak_shape_outlines(R0=6.2, A=3.1, kappa=1.7, delta=0.33, g=0.1,
                                    geom_model=2, eq=None)
    lcfs = out["lcfs"]
    wall = out["wall"]
    assert len(lcfs["R"]) == len(lcfs["Z"]) >= 64
    # wall encloses a larger area than the LCFS
    Vp_l, _ = tg.revolution_metrics(np.array(lcfs["R"]), np.array(lcfs["Z"]))
    Vp_w, _ = tg.revolution_metrics(np.array(wall["R"]), np.array(wall["Z"]))
    assert Vp_w > Vp_l
    assert out["geom_model"] == 2


def test_config_spec_accepts_geom_params():
    from polyfusion.configs.base import get
    spec = get("tokamak")
    for k in ("geom_model", "Vp_override", "Sw_override"):
        assert k in spec.params
    # bounds reject out-of-range model
    errs = spec.validate({**spec.presets["ITER"], "geom_model": 5})
    assert any("geom_model" in e for e in errs)


def test_all_presets_solve_under_every_geom_model():
    from polyfusion.configs.base import get
    spec = get("tokamak")
    for name, preset in spec.presets.items():
        for gm in (0, 1, 2):
            out = spec.solve({**preset, "geom_model": gm})
            assert out["valid"] == 1.0, f"{name} invalid under geom_model={gm}: {out.get('invalid_fields')}"
            assert out["Vp"] > 0


def test_legacy_vs_miller_within_few_percent_for_conventional_aspect():
    # conventional tokamaks (A >~ 2.5): the fit and the integral should agree well
    from polyfusion.configs.base import get
    spec = get("tokamak")
    for name in ("ITER", "JET", "EAST"):
        p = spec.presets[name]
        v0 = spec.solve({**p, "geom_model": 0})["Vp"]
        v1 = spec.solve({**p, "geom_model": 1})["Vp"]
        assert abs(v1 - v0) / v0 < 0.05, f"{name}: legacy {v0:.1f} vs Miller {v1:.1f}"


def test_cf_low_aspect_no_log_domain_warning():
    # high-eps spherical tokamak (EXL-50U-like) must not trip a numpy log warning
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any RuntimeWarning becomes an error
        R, Z, shaf = tg.cf_boundary(R0=0.7, a=0.4375, kappa=2.5, delta=0.5,
                                    n_theta=600)
    Vp, _ = tg.revolution_metrics(R, Z)
    assert Vp > 0
    assert np.all(R > 0)


def test_dispatch_eq_uses_equilibrium_boundary():
    import os
    from polyfusion import eqdsk
    fx = os.path.join(os.path.dirname(__file__), "data", "test_1.geqdsk")
    eq = eqdsk.equilibrium_geometry(eqdsk.parse_geqdsk(open(fx).read()))
    out = tg.tokamak_geometry(2, 6.2, 3.1, 1.7, 0.33, 0.05, eq, 0.0, 0.0)
    assert out["Vp"] == pytest.approx(eq["Vp"], rel=1e-6)
    assert out["a"] == pytest.approx(eq["a"], rel=1e-6)
    assert out["shaf_shift"] == pytest.approx(eq["shaf_shift"], rel=1e-6)
    cf = tg.tokamak_geometry(2, 6.2, 3.1, 1.7, 0.33, 0.05, None, 0.0, 0.0)
    assert cf["Vp"] != pytest.approx(eq["Vp"], rel=1e-3)


def test_shape_outlines_eq_has_flux_surfaces():
    import os
    from polyfusion import eqdsk
    fx = os.path.join(os.path.dirname(__file__), "data", "test_1.geqdsk")
    eq = eqdsk.equilibrium_geometry(eqdsk.parse_geqdsk(open(fx).read()))
    out = tg.tokamak_shape_outlines(R0=6.2, A=3.1, kappa=1.7, delta=0.33, g=0.05,
                                    geom_model=2, eq=eq)
    assert len(out["lcfs"]["R"]) >= 100
    assert len(out["flux"]) >= 4
    assert out["axis"]["R"][0] == pytest.approx(eq["axis"]["R"][0])


def test_funsc_eq_drives_volume_and_no_divertor_kwarg():
    import os
    from polyfusion.tokamak import funsc
    from polyfusion import eqdsk
    fx = os.path.join(os.path.dirname(__file__), "data", "test_1.geqdsk")
    eq = eqdsk.equilibrium_geometry(eqdsk.parse_geqdsk(open(fx).read()))
    base = dict(R0=6.35, A=3.43, kappa=1.86, delta=0.5, Sn=0.5, ST=1.0,
                ni0=6.81e19, Ti0=25, fT=1.0, fsig=1.0, f1=0.5, BT0=5.18,
                Ip=9.2, tauE=2.0, fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7,
                g=0.05, icase=1)
    r2 = funsc(**base, geom_model=2, eq=eq)
    assert r2.Vp == pytest.approx(eq["Vp"], rel=1e-6)
    assert r2.shaf_shift == pytest.approx(eq["shaf_shift"], rel=1e-6)
    with pytest.raises(TypeError):
        funsc(**base, divertor=1)


def test_config_spec_has_eq_param():
    from polyfusion.configs.base import get
    spec = get("tokamak")
    assert "eq" in spec.params
    assert "divertor" not in spec.params
    import os
    from polyfusion import eqdsk
    fx = os.path.join(os.path.dirname(__file__), "data", "test_1.geqdsk")
    eq = eqdsk.equilibrium_geometry(eqdsk.parse_geqdsk(open(fx).read()))
    out = spec.solve({**spec.presets["ITER"], "geom_model": 2, "eq": eq})
    assert out["valid"] == 1.0
    assert out["Vp"] == pytest.approx(eq["Vp"], rel=1e-6)


def test_geom_model_switch_changes_power_account():
    from polyfusion.configs.base import get
    spec = get("tokamak")
    p = spec.presets["ITER"]
    vps = [spec.solve({**p, "geom_model": gm})["Vp"] for gm in (0, 1, 2)]
    assert vps[0] != pytest.approx(vps[1], rel=1e-6)   # legacy fit != Miller integral
    pf = [spec.solve({**p, "geom_model": gm})["Pfus"] for gm in (0, 1)]
    assert pf[0] != pytest.approx(pf[1], rel=1e-6)      # geometry drives fusion power


def test_miller_flux_surfaces_nested_and_rounder_inward():
    fs = tg.miller_flux_surfaces(6.2, 2.0, 1.8, 0.5)
    assert len(fs) >= 3
    widths = [max(s["R"]) - min(s["R"]) for s in fs]
    assert widths == sorted(widths)                        # nested, growing outward
    elong = lambda s: (max(s["Z"]) - min(s["Z"])) / (max(s["R"]) - min(s["R"]))
    assert elong(fs[0]) < elong(fs[-1])                    # inner rounder than outer
    # Miller shape_fn now returns constructed flux surfaces (not naive scaling)
    out = tg.tokamak_shape_outlines(R0=6.2, A=3.1, kappa=1.8, delta=0.5, geom_model=1)
    assert len(out["flux"]) >= 3
