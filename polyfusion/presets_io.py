"""Preset data loader: machine presets live in JSON, not Python source.

Each magnetic configuration has a packaged ``presets/<config>.json`` of shape::

    {"presets": {"<name>": {<param>: <value>, ...}, ...},
     "groups":  {"<group label>": ["<name>", ...], ...}}

Non-developers add or tweak presets by editing those JSON files (or by dropping
a ``<config>.json`` into ``~/.polyfusion/presets/``, which is merged on top of
the packaged data so user presets override/extend the shipped ones).
"""

import json
import os
import warnings

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.join(_HERE, "presets")
_USER_DIR = os.path.join(os.path.expanduser("~"), ".polyfusion", "presets")


def load_presets(config):
    """Return ``(presets, groups)`` for a config.

    Packaged JSON is loaded first, then any ``~/.polyfusion/presets/<config>.json``
    is merged on top: user presets override/extend packaged ones and user groups
    merge with packaged groups.  A missing user dir (or file) is fine.
    """
    presets, groups = {}, {}
    for d in (_PKG_DIR, _USER_DIR):
        path = os.path.join(d, f"{config}.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            presets.update(data.get("presets", {}))
            groups.update(data.get("groups", {}))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            # a corrupt user-dir file must not crash the whole app at import;
            # packaged files are always valid, so this only guards user data.
            warnings.warn(f"skipping unreadable preset file {path}: {e}")
    return presets, groups
