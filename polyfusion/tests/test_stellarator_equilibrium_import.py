from __future__ import annotations

import os
import tempfile
import json
import threading
import urllib.request
import subprocess

import h5py
import numpy as np
import pytest
from netCDF4 import Dataset

from app.server import Handler, ThreadingHTTPServer
from polyfusion.equilibrium_import import (
    MAX_FILE_BYTES,
    equilibrium_to_stellarator_params,
    parse_equilibrium_bytes,
    parse_equilibrium_file,
)
from polyfusion.io import run_case
from polyfusion.presets_io import load_presets


def _vmec_fixture(path):
    with Dataset(path, "w") as ds:
        ds.createDimension("scalar", 1)
        ds.createDimension("radius", 3)
        ds.createDimension("mn_mode", 3)
        ds.createVariable("nfp", "i4", ("scalar",))[:] = [5]
        ds.createVariable("ns", "i4", ("scalar",))[:] = [3]
        ds.createVariable("xm", "f8", ("mn_mode",))[:] = [0, 1, 1]
        ds.createVariable("xn", "f8", ("mn_mode",))[:] = [0, 0, 5]
        rmnc = ds.createVariable("rmnc", "f8", ("radius", "mn_mode"))
        zmns = ds.createVariable("zmns", "f8", ("radius", "mn_mode"))
        rmnc[:] = [[5.5, 0, 0], [5.5, 0.4, 0.1], [5.5, 0.55, 0.12]]
        zmns[:] = [[0, 0, 0], [0, 0.4, 0.1], [0, 0.55, 0.12]]
        ds.createVariable("iotaf", "f8", ("radius",))[:] = [0.7, 0.8, 0.9]
        ds.createVariable("raxis_cc", "f8", ("mn_mode",))[:] = [5.5, 0.12, 0]
        ds.createVariable("zaxis_cs", "f8", ("mn_mode",))[:] = [0, -0.12, 0]
        ds.createVariable("Rmajor_p", "f8", ("scalar",))[:] = [5.5]
        ds.createVariable("Aminor_p", "f8", ("scalar",))[:] = [0.55]
        ds.createVariable("volume_p", "f8", ("scalar",))[:] = [30.0]
        ds.createVariable("b0", "f8", ("scalar",))[:] = [2.5]
        # uniform |B| (only the m=0,n=0 harmonic) and uniform Jacobian: the
        # real-field inhomogeneity factor <(|B|/B0)^2.5>_V must come out 1.0.
        bmnc = ds.createVariable("bmnc", "f8", ("radius", "mn_mode"))
        gmnc = ds.createVariable("gmnc", "f8", ("radius", "mn_mode"))
        bmnc[:] = [[0, 0, 0], [2.5, 0, 0], [2.5, 0, 0]]
        gmnc[:] = [[0, 0, 0], [-1.0, 0, 0], [-1.0, 0, 0]]


def _vmec_fixture_ripple(path, ripple):
    """VMEC wout with a single-helicity |B| ripple b0*(1 + ripple*cos(theta))."""
    _vmec_fixture(path)
    with Dataset(path, "a") as ds:
        bmnc = ds.variables["bmnc"]
        # xm=[0,1,1], xn=[0,0,5]: put the ripple on the m=1,n=0 (poloidal) mode.
        bmnc[1, 1] = 2.5 * ripple
        bmnc[2, 1] = 2.5 * ripple


def _desc_fixture(path):
    with h5py.File(path, "w") as f:
        f.create_dataset(
            "__class__", data=np.bytes_("desc.equilibrium.equilibrium.EquilibriaFamily")
        )
        f.create_dataset("__version__", data=np.bytes_("0.14.0"))
        family = f.create_group("_equilibria")
        family.create_dataset("__class__", data=np.bytes_("list"))
        eq = family.create_group("0")
        eq.create_dataset("_NFP", data=4)
        surf = eq.create_group("_surface")
        surf.create_dataset("_NFP", data=4)
        rb = surf.create_group("_R_basis")
        zb = surf.create_group("_Z_basis")
        modes_r = np.array([[0, 0, 0], [0, 1, 0], [0, 1, 1]], dtype=int)
        modes_z = np.array([[0, -1, 0], [0, -1, -1]], dtype=int)
        rb.create_dataset("_modes", data=modes_r)
        zb.create_dataset("_modes", data=modes_z)
        surf.create_dataset("_R_lmn", data=[5.0, 0.5, 0.1])
        surf.create_dataset("_Z_lmn", data=[0.5, 0.1])
        axis = eq.create_group("_axis")
        axis.create_dataset("_NFP", data=4)
        axis.create_group("_R_basis").create_dataset(
            "_modes", data=np.array([[0, 0, 0], [0, 0, 1]], dtype=int)
        )
        axis.create_group("_Z_basis").create_dataset(
            "_modes", data=np.array([[0, 0, -1]], dtype=int)
        )
        axis.create_dataset("_R_n", data=[5.0, 0.1])
        axis.create_dataset("_Z_n", data=[-0.1])
        iota = eq.create_group("_iota")
        iota.create_group("_basis").create_dataset(
            "_modes", data=np.array([[0, 0, 0], [2, 0, 0]], dtype=int)
        )
        iota.create_dataset("_params", data=[0.4, 0.09])


def test_vmec_wout_import_maps_lcfs_and_iota_rho_two_thirds():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wout_test.nc")
        _vmec_fixture(path)
        out = parse_equilibrium_file(path)

    assert out["source"]["format"] == "vmec"
    assert out["nfp"] == 5
    assert out["metrics"]["R0_m"] == 5.5
    assert out["metrics"]["a_vol_m"] == 0.55
    assert out["metrics"]["boundary_scale_m"] == pytest.approx(0.55)
    assert out["metrics"]["Vp_m3"] == 30.0
    assert out["B0_T"] == 2.5
    assert out["iota"]["rho_2_3"] == pytest.approx(
        np.interp(4 / 9, [0, 0.5, 1], [0.7, 0.8, 0.9])
    )
    assert [1, 1, pytest.approx(0.12 / 0.55)] in out["shape"]["R"]
    assert [-1, -1, pytest.approx(0.12 / 0.55)] in out["shape"]["R"]


def test_vmec_import_computes_real_field_b25_uniform_field_is_one():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wout_test.nc")
        _vmec_fixture(path)
        out = parse_equilibrium_file(path)
    # uniform |B| -> <(|B|/B0)^2.5> = 1 exactly (independent of grid)
    assert out["metrics"]["b25_real"] == pytest.approx(1.0, abs=1e-9)


def test_vmec_import_real_field_b25_matches_direct_quadrature_for_ripple():
    ripple = 0.2
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wout_test.nc")
        _vmec_fixture_ripple(path, ripple)
        out = parse_equilibrium_file(path)
    # |B|/B0 = 1 + ripple*cos(theta), uniform Jacobian -> the volume average is
    # the plain theta-average of (1 + ripple*cos)^2.5.
    th = np.linspace(0.0, 2 * np.pi, 4096, endpoint=False)
    expected = float(np.mean(np.abs(1.0 + ripple * np.cos(th)) ** 2.5))
    assert out["metrics"]["b25_real"] == pytest.approx(expected, rel=1e-4)
    assert out["metrics"]["b25_real"] > 1.0


def test_imported_real_field_b25_overrides_first_order_in_power_balance():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wout_test.nc")
        _vmec_fixture_ripple(path, 0.3)
        imported = parse_equilibrium_file(path)
    base = dict(load_presets("stellarator")[0]["W7-X"])
    base.update(equilibrium_to_stellarator_params(imported, current_B0=base["B0"]))
    base.pop("geometry_variants", None)
    base["cyclotron_B_nonuniform"] = 1.0
    run = run_case(base, config="stellarator")
    assert "errors" not in run, run.get("errors")
    assert run["outputs"]["cyclotron_B25_factor"] == pytest.approx(
        imported["metrics"]["b25_real"], rel=1e-9
    )


def test_desc_import_reads_final_equilibrium_surface_axis_and_profile():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test_output.h5")
        _desc_fixture(path)
        out = parse_equilibrium_file(path)

    assert out["source"]["format"] == "desc"
    assert out["source"]["version"] == "0.14.0"
    assert out["nfp"] == 4
    assert out["metrics"]["R0_m"] == 5.0
    assert out["iota"]["axis"] == pytest.approx(0.4)
    assert out["iota"]["rho_2_3"] == pytest.approx(0.44)
    assert out["iota"]["edge"] == pytest.approx(0.49)
    assert out["shape"]["axis_rc"] == pytest.approx([5.0, 0.1])
    assert out["shape"]["axis_zs"] == pytest.approx([0.0, -0.1])
    assert out["B0_T"] is None


def test_imported_equilibrium_maps_to_readonly_stellarator_geometry_params():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test_output.h5")
        _desc_fixture(path)
        imported = parse_equilibrium_file(path)
        params = equilibrium_to_stellarator_params(imported, current_B0=3.2)

    assert params["_geom_mode"] == "equilibrium"
    assert params["R0"] == imported["metrics"]["R0_m"]
    assert params["a"] == imported["metrics"]["boundary_scale_m"]
    assert params["N_fp"] == 4
    assert params["iota"] == pytest.approx(abs(imported["iota"]["rho_2_3"]))
    assert params["Vp_override"] == pytest.approx(imported["metrics"]["Vp_m3"])
    assert params["Sw_override"] == 0.0
    assert params["B0"] == 3.2
    assert params["equilibrium"] == imported


def test_parse_bytes_preserves_original_filename_and_hash():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wout_test.nc")
        _vmec_fixture(path)
        data = open(path, "rb").read()
    out = parse_equilibrium_bytes(data, "wout_original.nc")
    assert out["source"]["filename"] == "wout_original.nc"
    assert len(out["source"]["sha256"]) == 64


def test_equilibrium_preview_http_endpoint_accepts_raw_binary(monkeypatch):
    # this test exercises the equilibrium-parsing path, not auth; disable the
    # login gate so we don't have to run a full register/login dance here.
    import app.server as srv

    monkeypatch.setattr(srv, "REQUIRE_AUTH", False)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "wout_test.nc")
        _vmec_fixture(path)
        data = open(path, "rb").read()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/stellarator/equilibrium/preview",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Filename": "wout_uploaded.nc",
            },
        )
        with urllib.request.urlopen(req) as response:
            out = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert out["source"]["filename"] == "wout_uploaded.nc"
    assert out["source"]["format"] == "vmec"


def test_runtime_dependencies_include_equilibrium_readers():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    requirements = open(os.path.join(root, "requirements.txt"), encoding="utf-8").read()
    assert "netCDF4" in requirements
    assert "h5py" in requirements
    assert MAX_FILE_BYTES == 128 * 1024 * 1024


def test_imported_equilibrium_runs_as_independent_stellarator_geometry_mode():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test_output.h5")
        _desc_fixture(path)
        imported = parse_equilibrium_file(path)
    base = dict(load_presets("stellarator")[0]["W7-X"])
    base.update(equilibrium_to_stellarator_params(imported, current_B0=base["B0"]))
    base.pop("geometry_variants", None)
    run = run_case(base, config="stellarator")
    assert "errors" not in run, run.get("errors")
    assert run["inputs"]["equilibrium"]["source"]["format"] == "desc"
    assert run["outputs"]["iota"] == pytest.approx(abs(imported["iota"]["rho_2_3"]))
    assert run["outputs"]["Vp"] == pytest.approx(imported["metrics"]["Vp_m3"])
    assert run["shape"]["mode"] == "equilibrium"


def _extract_js_function(src, name):
    start = src.index(f"function {name}(")
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(name)


def test_frontend_exposes_equilibrium_mode_upload_and_readonly_geometry():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    html = open(os.path.join(root, "app", "index.html"), encoding="utf-8").read()
    assert "VMEC/DESC 平衡" in html
    assert 'id="equilibriumFileIn"' in html
    assert "/api/stellarator/equilibrium/preview" in html
    assert "applyImportedEquilibrium" in html
    assert "equilibriumLockedParam" in html
    assert "equilibrium" in html.split("OPAQUE_PARAMS", 1)[1].split("\n", 1)[0]
    avol_fn = _extract_js_function(html, "stellAVolDisplay")
    assert "(mode==='boundary'||mode==='equilibrium')" in avol_fn


def test_frontend_import_application_preserves_operating_inputs_and_b0_fallback():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    html = open(os.path.join(root, "app", "index.html"), encoding="utf-8").read()
    fn = _extract_js_function(html, "applyImportedEquilibrium")
    imported = {
        "nfp": 5,
        "shape": {
            "kind": "equilibrium_fourier",
            "nfp": 5,
            "R": [[1, 0, 1]],
            "Z": [[-1, 0, 1]],
        },
        "iota": {"rho_2_3": -0.88},
        "metrics": {"R0_m": 5.5, "boundary_scale_m": 0.6, "Vp_m3": 31},
        "B0_T": None,
        "source": {"format": "desc", "filename": "x.h5"},
    }
    js = f"""
let VALS={{B0:3.1,Ti0:15,ni0:2e20,delta_h:0.2,rc:[5,0.2]}};
{fn}
applyImportedEquilibrium({json.dumps(imported)});
console.log(JSON.stringify(VALS));
"""
    vals = json.loads(subprocess.check_output(["node", "-e", js], cwd=root, text=True))
    assert vals["B0"] == 3.1
    assert vals["Ti0"] == 15
    assert vals["ni0"] == 2e20
    assert vals["_geom_mode"] == "equilibrium"
    assert vals["R0"] == 5.5
    assert vals["a"] == 0.6
    assert vals["iota"] == 0.88
    assert vals["Vp_override"] == 31
    assert "delta_h" not in vals and "rc" not in vals


def test_import_rejects_more_than_mode_limit():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test_output.h5")
        _desc_fixture(path)
        with h5py.File(path, "a") as f:
            surf = f["_equilibria/0/_surface"]
            del surf["_R_basis/_modes"]
            del surf["_R_lmn"]
            surf["_R_basis"].create_dataset(
                "_modes", data=np.zeros((4097, 3), dtype=int)
            )
            surf.create_dataset("_R_lmn", data=np.ones(4097))
        with pytest.raises(ValueError, match="4096"):
            parse_equilibrium_file(path)
