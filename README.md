# PolyFusion Zero-D Platform

多位形零维聚变系统设计平台 — Multi-configuration 0-D fusion system design platform with web GUI.

## Supported Configurations

| Configuration | Status |
|---|---|
| Tokamak | Verified (golden test ✓) |
| Magnetic Mirror | Preliminary integration |
| FRC (Field-Reversed) | Preliminary integration |
| Dipole | Framework only |
| Stellarator | Framework only |

## Quick Start

```bash
pip install -r requirements.txt
python -m polyfusion              # CLI single-point
python app/server.py             # Web GUI → http://127.0.0.1:8765
```

## Structure

```
polyfusion/        Compute core (tokamak 0-D solver, reactivity, presets)
polyfusion/configs/ Per-configuration models (mirror, FRC, dipole, stellarator)
app/              Web GUI (stdlib HTTP server + Plotly-based SPA)
```

## License

MIT
