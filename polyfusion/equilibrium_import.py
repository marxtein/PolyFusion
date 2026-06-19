"""Lightweight VMEC wout / DESC equilibrium import for stellarator geometry."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from collections import defaultdict

import h5py
import numpy as np
from netCDF4 import Dataset

MAX_MODES = 4096
MAX_FILE_BYTES = 128 * 1024 * 1024


def _scalar(value):
    arr = np.asarray(value)
    return arr.reshape(-1)[0].item()


def _finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _rows(mapping):
    return [[int(m), int(n), float(c)] for (m, n), c in sorted(mapping.items())
            if abs(float(c)) > 1e-14]


def _add(mapping, m, n, value):
    if abs(value) > 1e-14:
        mapping[(int(m), int(n))] += float(value)


def _expand_cos(mapping, m, n, value):
    """cos(m theta - n*NFP phi) in the product basis used by PolyFusion."""
    if m == 0 or n == 0:
        _add(mapping, abs(m), abs(n), value)
    else:
        _add(mapping, abs(m), abs(n), value)
        _add(mapping, -abs(m), -abs(n), value)


def _expand_sin(mapping, m, n, value):
    """sin(m theta - n*NFP phi) in the product basis used by PolyFusion."""
    if m == 0:
        _add(mapping, 0, -abs(n), -math.copysign(value, n))
    elif n == 0:
        _add(mapping, -abs(m), 0, math.copysign(value, m))
    else:
        sign_m = 1.0 if m >= 0 else -1.0
        sign_n = 1.0 if n >= 0 else -1.0
        _add(mapping, -abs(m), abs(n), sign_m * value)
        _add(mapping, abs(m), -abs(n), -sign_n * value)


def _axis_lists(rc, zs):
    nmax = max([0, *rc.keys(), *zs.keys()])
    return ([float(rc.get(n, 0.0)) for n in range(nmax + 1)],
            [float(zs.get(n, 0.0)) for n in range(nmax + 1)])


def _normalise_shape(nfp, r_phys, z_phys, axis_rc, axis_zs, source):
    r00 = float(r_phys.pop((0, 0), 0.0))
    if r00 <= 0:
        raise ValueError("equilibrium boundary has no positive R(0,0) major radius")
    amplitudes = [abs(v) for v in r_phys.values()] + [abs(v) for v in z_phys.values()]
    scale = max(amplitudes, default=0.0)
    if scale <= 0:
        raise ValueError("equilibrium boundary has no non-axis Fourier modes")
    r_rows, z_rows = _rows(r_phys), _rows(z_phys)
    if max(len(r_rows), len(z_rows)) > MAX_MODES:
        raise ValueError(
            f"converted equilibrium has more than {MAX_MODES} modes; limit is {MAX_MODES}")
    shape = {
        "kind": "equilibrium_fourier",
        "nfp": int(nfp),
        "R": [[m, n, c / scale] for m, n, c in r_rows],
        "Z": [[m, n, c / scale] for m, n, c in z_rows],
        "axis_rc": [float(x) for x in axis_rc],
        "axis_zs": [float(x) for x in axis_zs],
        "source": source,
    }
    return r00, scale, shape


def _geometry_metrics(R0, a, shape):
    from .configs.stellarator import _shape_boundary_fn, boundary_metrics

    boundary_fn, nfp = _shape_boundary_fn(R0, a, shape)
    volume, _, plasma_surface = boundary_metrics(boundary_fn, nfp, g=0.0)
    return float(volume), float(plasma_surface)


def _source(path, fmt, version):
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {
        "format": fmt,
        "filename": os.path.basename(path),
        "sha256": digest,
        "version": version,
    }


def _read_vmec(path):
    with Dataset(path, "r") as ds:
        def required(name):
            if name not in ds.variables:
                raise ValueError(f"VMEC wout missing variable {name}")
            return np.asarray(ds.variables[name][:])

        nfp = int(_scalar(required("nfp")))
        xm = required("xm").astype(int)
        xn_raw = required("xn")
        xn = np.rint(xn_raw / nfp).astype(int)
        if not np.allclose(xn * nfp, xn_raw):
            raise ValueError("VMEC xn values must be integer multiples of nfp")
        rmnc_all = required("rmnc")
        zmns_all = required("zmns")
        rmns_all = np.asarray(ds.variables["rmns"][:]) if "rmns" in ds.variables else None
        zmnc_all = np.asarray(ds.variables["zmnc"][:]) if "zmnc" in ds.variables else None
        rmnc = rmnc_all[-1]
        zmns = zmns_all[-1]
        if len(xm) > MAX_MODES:
            raise ValueError(f"equilibrium has {len(xm)} modes; limit is {MAX_MODES}")

        r_phys, z_phys = defaultdict(float), defaultdict(float)
        for m, n, c in zip(xm, xn, rmnc):
            _expand_cos(r_phys, int(m), int(n), _finite(c, "rmnc"))
        for m, n, c in zip(xm, xn, zmns):
            _expand_sin(z_phys, int(m), int(n), _finite(c, "zmns"))
        if "rmns" in ds.variables:
            for m, n, c in zip(xm, xn, np.asarray(ds.variables["rmns"][:])[-1]):
                _expand_sin(r_phys, int(m), int(n), _finite(c, "rmns"))
        if "zmnc" in ds.variables:
            for m, n, c in zip(xm, xn, np.asarray(ds.variables["zmnc"][:])[-1]):
                _expand_cos(z_phys, int(m), int(n), _finite(c, "zmnc"))

        rc = {i: float(v) for i, v in enumerate(
            np.asarray(ds.variables["raxis_cc"][:]).reshape(-1))} if "raxis_cc" in ds.variables else {}
        zs = {i: float(v) for i, v in enumerate(
            np.asarray(ds.variables["zaxis_cs"][:]).reshape(-1))} if "zaxis_cs" in ds.variables else {}
        axis_rc, axis_zs = _axis_lists(rc, zs)
        R0, scale, shape = _normalise_shape(
            nfp, r_phys, z_phys, axis_rc, axis_zs, "VMEC wout LCFS")

        # Real interior flux surfaces from the wout (rmnc/zmns at several radial
        # surfaces, NOT just the LCFS), kept in native VMEC Fourier so the shape
        # view can draw the equilibrium's actual nested surfaces instead of a
        # synthesized cartoon.  Each surface is LABELLED by the VOLUME radius
        # rho = sqrt(V_enclosed/V_plasma) so it matches the 0-D profile/volume-
        # average coordinate exactly (a flux-surface label, Shafranov-independent).
        # The VMEC radial index is the normalized toroidal flux s = j/(ns-1); we
        # map a target volume fraction -> s via the wout dV/ds profile ``vp``
        # (V(s) is only ~s for these equilibria, but this keeps it exact).
        ns = rmnc_all.shape[0]
        s_grid_full = np.linspace(0.0, 1.0, ns)
        if "vp" in ds.variables:
            vp = np.abs(np.asarray(ds.variables["vp"][:]).reshape(-1))
            if vp.size == ns and np.all(np.isfinite(vp)):
                Vcum = np.concatenate([[0.0], np.cumsum(0.5 * (vp[1:] + vp[:-1]))])
                Vfrac_of_s = Vcum / Vcum[-1] if Vcum[-1] > 0 else s_grid_full
            else:
                Vfrac_of_s = s_grid_full
        else:
            Vfrac_of_s = s_grid_full

        def _native_modes(coeffs):
            return [[int(m), int(n), float(c)]
                    for m, n, c in zip(xm, xn, coeffs) if abs(float(c)) > 1e-9]

        interior = []
        for rho in (0.18, 0.344, 0.508, 0.672, 0.836, 1.0):
            # volume fraction = rho^2 -> s (via V(s)) -> nearest radial index
            s_target = float(np.interp(rho * rho, Vfrac_of_s, s_grid_full))
            j = min(ns - 1, max(1, int(round(s_target * (ns - 1)))))
            surf = {"rho": float(rho),
                    "R_c": _native_modes(rmnc_all[j]),
                    "Z_s": _native_modes(zmns_all[j])}
            if rmns_all is not None:
                surf["R_s"] = _native_modes(rmns_all[j])
            if zmnc_all is not None:
                surf["Z_c"] = _native_modes(zmnc_all[j])
            interior.append(surf)
        shape["interior_surfaces"] = interior

        iota_values = required("iotaf").reshape(-1)
        s_grid = np.linspace(0.0, 1.0, len(iota_values))
        iota = {
            "axis": float(iota_values[0]),
            "rho_2_3": float(np.interp(4.0 / 9.0, s_grid, iota_values)),
            "edge": float(iota_values[-1]),
        }
        volume_geom, surface_geom = _geometry_metrics(R0, scale, shape)

        def optional_scalar(*names):
            for name in names:
                if name in ds.variables:
                    return _finite(_scalar(ds.variables[name][:]), name)
            return None

        Rmajor = optional_scalar("Rmajor_p") or R0
        aminor = optional_scalar("Aminor_p")
        volume = optional_scalar("volume_p") or volume_geom
        if aminor is None:
            aminor = math.sqrt(volume / (2 * math.pi**2 * Rmajor))
        B0 = optional_scalar("b0", "B0")
        version = str(getattr(ds, "version_", getattr(ds, "VMEC_version", "")))

    return {
        "schema_version": 1,
        "source": _source(path, "vmec", version),
        "nfp": nfp,
        "shape": shape,
        "iota": iota,
        "metrics": {
            "R0_m": R0,
            "Rmajor_vmec_m": float(Rmajor),
            "a_vol_m": float(aminor),
            "boundary_scale_m": scale,
            "Vp_m3": float(volume),
            "Vp_integral_m3": volume_geom,
            "Sp_m2": surface_geom,
        },
        "B0_T": B0,
        "mode_count": int(max(len(shape["R"]), len(shape["Z"]))),
        "warnings": [],
    }


def _decode(value):
    value = _scalar(value)
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _read_desc(path):
    with h5py.File(path, "r") as f:
        if "_equilibria" not in f:
            raise ValueError("unsupported DESC HDF5: missing _equilibria")
        keys = sorted((key for key in f["_equilibria"].keys() if key.isdigit()),
                      key=lambda x: int(x))
        if not keys:
            raise ValueError("DESC file contains no equilibria")
        eq = f["_equilibria"][keys[-1]]
        surf = eq["_surface"]
        nfp = int(_scalar(surf["_NFP"][()]))
        r_modes = np.asarray(surf["_R_basis/_modes"][()])
        z_modes = np.asarray(surf["_Z_basis/_modes"][()])
        r_coeff = np.asarray(surf["_R_lmn"][()])
        z_coeff = np.asarray(surf["_Z_lmn"][()])
        if max(len(r_modes), len(z_modes)) > MAX_MODES:
            raise ValueError(
                f"equilibrium has more than {MAX_MODES} modes; limit is {MAX_MODES}")

        r_phys, z_phys = defaultdict(float), defaultdict(float)
        for mode, coeff in zip(r_modes, r_coeff):
            _, m, n = [int(x) for x in mode]
            _add(r_phys, m, n, _finite(coeff, "DESC R_lmn"))
        for mode, coeff in zip(z_modes, z_coeff):
            _, m, n = [int(x) for x in mode]
            _add(z_phys, m, n, _finite(coeff, "DESC Z_lmn"))

        axis = eq["_axis"]
        rc, zs = {}, {}
        for mode, coeff in zip(np.asarray(axis["_R_basis/_modes"][()]),
                               np.asarray(axis["_R_n"][()])):
            n = int(mode[2])
            if n >= 0:
                rc[n] = float(coeff)
        for mode, coeff in zip(np.asarray(axis["_Z_basis/_modes"][()]),
                               np.asarray(axis["_Z_n"][()])):
            n = int(mode[2])
            if n < 0:
                zs[-n] = float(coeff)
        axis_rc, axis_zs = _axis_lists(rc, zs)
        R0, scale, shape = _normalise_shape(
            nfp, r_phys, z_phys, axis_rc, axis_zs, "DESC native LCFS")

        profile = eq["_iota"]
        powers = np.asarray(profile["_basis/_modes"][()])[:, 0].astype(int)
        params = np.asarray(profile["_params"][()], dtype=float)

        def eval_iota(rho):
            return float(np.sum(params * float(rho) ** powers))

        iota = {"axis": eval_iota(0.0), "rho_2_3": eval_iota(2.0 / 3.0),
                "edge": eval_iota(1.0)}
        volume, surface = _geometry_metrics(R0, scale, shape)
        a_vol = math.sqrt(volume / (2 * math.pi**2 * R0))
        version = _decode(f["__version__"][()]) if "__version__" in f else ""

    return {
        "schema_version": 1,
        "source": _source(path, "desc", version),
        "nfp": nfp,
        "shape": shape,
        "iota": iota,
        "metrics": {
            "R0_m": R0,
            "a_vol_m": a_vol,
            "boundary_scale_m": scale,
            "Vp_m3": volume,
            "Vp_integral_m3": volume,
            "Sp_m2": surface,
        },
        "B0_T": None,
        "mode_count": int(max(len(shape["R"]), len(shape["Z"]))),
        "warnings": ["DESC native file does not provide a validated B0 scalar; current B0 is preserved."],
    }


def parse_equilibrium_file(path):
    """Parse a VMEC wout NetCDF or native DESC HDF5 file."""
    lower = os.path.basename(path).lower()
    if lower.endswith(".nc"):
        return _read_vmec(path)
    if lower.endswith((".h5", ".hdf5")):
        return _read_desc(path)
    raise ValueError("equilibrium file must be .nc, .h5, or .hdf5")


def parse_equilibrium_bytes(data, filename):
    """Parse uploaded equilibrium bytes without retaining the original file."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("equilibrium upload must be bytes")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"equilibrium file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MiB limit")
    suffix = os.path.splitext(filename or "")[1].lower()
    if suffix not in (".nc", ".h5", ".hdf5"):
        raise ValueError("equilibrium file must be .nc, .h5, or .hdf5")
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(data)
            path = fh.name
        out = parse_equilibrium_file(path)
        out["source"]["filename"] = os.path.basename(filename)
        out["source"]["sha256"] = hashlib.sha256(data).hexdigest()
        return out
    finally:
        if path and os.path.isfile(path):
            os.remove(path)


def equilibrium_to_stellarator_params(imported, current_B0):
    """Map a parsed equilibrium to the existing stellarator solver inputs."""
    metrics = imported["metrics"]
    params = {
        "_geom_mode": "equilibrium",
        "R0": float(metrics["R0_m"]),
        "a": float(metrics["boundary_scale_m"]),
        "N_fp": int(imported["nfp"]),
        "shape": imported["shape"],
        "iota": abs(float(imported["iota"]["rho_2_3"])),
        "Vp_override": float(metrics["Vp_m3"]),
        "Sw_override": 0.0,
        "equilibrium": imported,
    }
    B0 = imported.get("B0_T")
    params["B0"] = float(B0) if B0 is not None else float(current_B0)
    return params
