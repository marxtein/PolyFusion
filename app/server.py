"""Minimal local web server for the PolyFusion (option A, confirmed stack).

Stdlib only (no Flask): serves a single Plotly page and exposes the
config-agnostic compute core over a narrow JSON API.  Works for every
configuration in ``polyfusion.configs.REGISTRY`` (tokamak, mirror, …).

    python app/server.py            # then open http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

# Cap BLAS threads BEFORE numpy loads.  On this Windows numpy build the OpenBLAS
# threaded path is pathologically slow for medium matrices — a 121x121
# linalg.solve (near-axis r2) took ~0.6 s multi-threaded vs ~0.4 ms
# single-threaded (~1300x).  Every matrix here is tiny, so single-threaded BLAS
# is strictly faster and numerically identical.  setdefault keeps any user override.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from polyfusion.io import run_case, list_configs   # noqa: E402
from polyfusion.configs.base import get             # noqa: E402
from polyfusion.scan import scan2d, best_region_mask  # noqa: E402
from polyfusion.equilibrium_import import (  # noqa: E402
    MAX_FILE_BYTES,
    parse_equilibrium_bytes,
)
from polyfusion import eqdsk                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8765))


def _floatify(d: dict) -> dict:
    """Coerce incoming numerics to float (keep icase int).

    JS serialises large values like 6.81e19 as integer literals; Python's json
    parses those as arbitrary-precision ints exceeding int64, which makes numpy
    build object-dtype arrays and breaks float ops.  Cast at the boundary.
    """
    out = {}
    for k, v in (d or {}).items():
        if k == "icase":
            out[k] = int(v)
        elif isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _do_scan(req: dict) -> dict:
    config = req.get("config", "tokamak")
    spec = get(config)
    base = dict(spec.presets[req["preset"]]) if req.get("preset") else {}
    base.update(_floatify(req.get("overrides")))
    xk, yk = req["xkey"], req["ykey"]
    xv = np.linspace(float(req["xmin"]), float(req["xmax"]), int(req["nx"]))
    yv = np.linspace(float(req["ymin"]), float(req["ymax"]), int(req["ny"]))
    g = scan2d(spec, base, xk, yk, xv, yv)
    win = req.get("window")
    if win and (win.get("ge") or win.get("le")):
        ge = {k: float(v) for k, v in (win.get("ge") or {}).items()}
        le = {k: float(v) for k, v in (win.get("le") or {}).items()}
        mask = best_region_mask(g, ge=ge, le=le)
    else:
        mask = best_region_mask(g, **spec.best_window)
    fields = [c["f"] for c in spec.contour_spec if c["f"] in g]

    def _jsonsafe(arr):
        """NaN/inf -> null: invalid points render as holes, and strict JSON
        parsers (the browser) do not choke on bare NaN tokens."""
        a = np.real(np.asarray(arr, dtype=float))
        return np.where(np.isfinite(a), a.astype(object), None).tolist()

    n_invalid = int(np.sum(np.asarray(g["valid"]) < 0.5)) if "valid" in g else 0
    return {
        "config": config, "xkey": xk, "ykey": yk, "x": xv.tolist(), "y": yv.tolist(),
        # transpose (nx,ny)->(ny,nx) so Plotly reads z[y][x]
        "fields": {k: _jsonsafe(g[k].T) for k in fields},
        "best": mask.T.astype(int).tolist(),
        "valid": _jsonsafe(g["valid"].T) if "valid" in g else None,
        "n_invalid": n_invalid,
        "scan_errors": g.get("scan_errors", {}),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # local dev tool: never let the browser cache a stale index.html/API
        # response (edited files must show on a plain reload)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if self.path == "/api/meta":
            return self._send(200, json.dumps({"configs": list_configs()}))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if self.path == "/api/stellarator/equilibrium/preview":
            if n > MAX_FILE_BYTES:
                limit_mib = MAX_FILE_BYTES // (1024 * 1024)
                return self._send(
                    413, json.dumps({"error": f"equilibrium file exceeds {limit_mib} MiB limit"}))
            filename = unquote(self.headers.get("X-Filename", ""))
            try:
                out = parse_equilibrium_bytes(self.rfile.read(n), filename)
                body = json.dumps(out)
            except Exception as e:
                return self._send(400, json.dumps({"error": f"{type(e).__name__}: {e}"}))
            return self._send(200, body)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._send(400, json.dumps({"error": f"bad json: {e}"}))
        try:
            if self.path == "/api/tokamak/parse_eqdsk":
                g = eqdsk.parse_geqdsk(req.get("eqdsk") or "")
                out = {"config": "tokamak", "eq": eqdsk.equilibrium_geometry(g)}
            elif self.path == "/api/run":
                out = run_case(_floatify(req.get("overrides")), preset=req.get("preset"),
                               config=req.get("config", "tokamak"))
            elif self.path == "/api/scan":
                out = _do_scan(req)
            else:
                return self._send(404, json.dumps({"error": "not found"}))
            # numpy-safe: serialise inside the try so any encoding bug -> 400, not a crash
            body = json.dumps(out, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        except Exception as e:
            return self._send(400, json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return self._send(200, body)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"PolyFusion serving at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
