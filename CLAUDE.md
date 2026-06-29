# PolyFusion — Developer Guide

This file is loaded automatically by Claude Code. Read it before making any changes.

---

## Code Style

### Tooling

| Tool | Command | Purpose |
|------|---------|---------|
| ruff | `ruff check --fix .` | Lint + auto-fix |
| ruff | `ruff format .` | Format |
| pytest | `pytest polyfusion/tests` | Run tests |

**Always run `ruff check --fix .` and `pytest polyfusion/tests` before committing.**

Ruff and pytest are expected to be installed in the active environment:

```bash
pip install -r requirements.txt   # runtime deps
pip install pytest ruff           # dev deps
```

### Key Rules

- Python: ≥ 3.10
- Line length: 88 (ruff default; configure via `pyproject.toml` if the project later adopts a different limit)
- Imports: sorted by ruff (isort-compatible I001)
- Naming: `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` module-level constants only
- Type hints: prefer annotations on public functions and class methods
- NumPy/BLAS: cap threads before importing numpy to avoid pathological OpenBLAS slowdown on small matrices. `polyfusion/__init__.py` and `app/server.py` already do this; preserve the pattern when adding entry points.

### Common `# noqa` Patterns

- `E402` — imports after `sys.path.insert(...)` or after BLAS-env setup are intentional. Tag those lines with `# noqa: E402`.
- `N803` — keep camelCase names when they mirror an external API contract or JSON field, and add `# noqa: N803`.

### Commit Format (Conventional Commits)

```
<type>(<scope>): <short summary>
```

Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`

```
feat(tokamak): add q95 engineering edge safety factor
fix(scan): best_region_mask excluded invalid scan points
chore: bump numpy lower bound
test(stellarator): add W7-X boundary geometry golden case
```

---

## Project Layout

```
PolyFusion/
├── polyfusion/              # Compute core
│   ├── tokamak.py          # Tokamak 0-D power-balance solver (funsc)
│   ├── io.py               # Config-agnostic JSON API boundary
│   ├── scan.py             # 2-D parameter scan + best-region mask
│   ├── eqdsk.py            # G-EQDSK parser + equilibrium geometry
│   ├── presets.py          # Tokamak presets (Python)
│   ├── presets_io.py       # JSON preset loader for non-tokamak configs
│   ├── presets/            # JSON preset files (mirror, frc, dipole, stellarator)
│   ├── configs/
│   │   ├── base.py         # ConfigSpec registry + ConfigSpec dataclass
│   │   ├── mirror.py       # Magnetic mirror solver
│   │   ├── frc.py          # Field-reversed configuration solver
│   │   ├── dipole.py       # Levitated dipole solver
│   │   └── stellarator.py  # Stellarator / near-axis solver
│   ├── geometry/           # Boundary/section outline helpers
│   ├── tests/              # pytest suite + golden JSON references
│   └── ...                 # physics modules (cyclotron, reactivity, etc.)
├── app/                    # Web GUI
│   ├── server.py           # Stdlib-only HTTP server (no Flask)
│   ├── index.html          # Plotly.js front-end
│   └── equilibria/         # Bundled real-equilibrium files
├── docs/                   # Design/audit reports (Chinese)
└── requirements.txt        # Runtime dependencies
```

---

## Adding a Configuration

1. Add a solver module at `polyfusion/configs/<name>.py` with a `solve_<name>(**kwargs) -> dict` function.
2. Declare its parameters, presets, and scan metadata in `polyfusion/configs/base.py` by registering a `ConfigSpec` in `REGISTRY`.
3. Add JSON presets to `polyfusion/presets/<name>.json` (optional for tokamak, which uses Python presets).
4. Add tests under `polyfusion/tests/test_<name>_*.py`.

Front-ends (`app/server.py`, `polyfusion/io.py`, `polyfusion/scan.py`) discover the new configuration through `REGISTRY` automatically.

---

## Testing

```bash
pytest polyfusion/tests              # full suite
pytest polyfusion/tests/test_foo.py  # single file
pytest -k "tokamak" polyfusion/tests # filter by keyword
```

- Golden/reference comparisons use JSON files in `polyfusion/tests/`.
- Some audit-style tests are also runnable as scripts (e.g. `python polyfusion/tests/test_validation.py`); pytest collects any function named `test_*`.
- Do not make real network/API calls from tests.

---

## What NOT to Do

- Don't add heavy framework dependencies to `app/server.py` — keep it stdlib-only unless explicitly agreed.
- Don't import numpy at module top-level before capping BLAS threads in entry-point files.
- Don't put business logic in `app/server.py` — route through `polyfusion.io.run_case` and `polyfusion.scan.scan2d`.
- Don't silently swallow solver errors in the public API; return `"errors": [...]` via `run_case` instead.
- Don't check in large binary equilibrium files without updating `app/server.py` path restrictions and the `equilibria/manifest.json`.
