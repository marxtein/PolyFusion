"""JSON-friendly boundary between the compute core and any front-end.

Every UI (local web, PySide, plain JS, or a script) drives the core through
the narrow ``dict -> dict`` interface here.  Config-agnostic: route to any
configuration in :data:`polyfusion.configs.REGISTRY` via the ``config`` arg
(default ``"tokamak"`` for backward compatibility).
"""

from __future__ import annotations

import json
from typing import Any

from .configs.base import get, REGISTRY


def run_case(params: dict, *, preset: str | None = None,
             config: str = "tokamak") -> dict[str, Any]:
    """Evaluate one operating point of a configuration.

    Parameters
    ----------
    params : dict
        Parameter overrides (keys from the config's ``params``).
    preset : str, optional
        Preset name to use as the base; ``params`` overrides it.
    config : str
        Configuration name (``"tokamak"``, ``"mirror"``, …).

    Returns
    -------
    dict
        ``{"config", "inputs", "outputs"}`` or ``{"config", "errors", "inputs"}``.
    """
    spec = get(config)
    base = dict(spec.presets[preset]) if preset else {}
    base.update(params or {})
    errors = spec.validate(base)
    if errors:
        return {"config": config, "errors": errors, "inputs": base}
    try:
        outputs = spec.solve(base)
    except Exception as e:  # solver-level domain guard (audit P0)
        return {"config": config, "errors": [f"{type(e).__name__}: {e}"],
                "inputs": base}
    result = {"config": config, "inputs": base, "outputs": outputs}
    if spec.shape_fn is not None:
        try:
            result["shape"] = spec.shape_fn(base)
        except Exception:
            pass  # shape view is cosmetic — never fail the physics result
    return result


def run_preset(name: str, config: str = "tokamak") -> dict[str, Any]:
    """Evaluate a named preset of a configuration unchanged."""
    return run_case({}, preset=name, config=config)


def list_configs() -> dict[str, dict]:
    """Metadata for every registered configuration (for UIs)."""
    return {
        c.name: {
            "label": c.label, "params": c.params, "presets": list(c.presets),
            "preset_groups": c.preset_groups,
            "contour_fields": c.contour_fields, "scan_defaults": c.scan_defaults,
            "best_window": c.best_window, "optional_window": c.optional_window,
            "contour_spec": c.contour_spec,
        }
        for c in REGISTRY.values()
    }


def to_json(obj: dict, **kw) -> str:
    return json.dumps(obj, ensure_ascii=False, **kw)


def from_json(text: str) -> dict:
    return json.loads(text)
