# DigitalFusion

Multi-configuration 0-D fusion system code with web GUI.

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
python -m etsc_core              # CLI single-point
python app/server.py             # Web GUI → http://127.0.0.1:8765
```

## Structure

```
etsc_core/        Compute core (tokamak 0-D solver, reactivity, presets)
etsc_core/configs/ Per-configuration models (mirror, FRC, dipole, stellarator)
app/              Web GUI (stdlib HTTP server + Plotly-based SPA)
```

## License

MIT
