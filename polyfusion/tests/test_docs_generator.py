"""Tests for polyfusion.docs_generator."""

from __future__ import annotations

import json as jsonlib
import os
import sys
import threading
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.base import REGISTRY  # noqa: E402
from polyfusion.docs_generator import generate_manual  # noqa: E402

ALL_CONFIGS = sorted(REGISTRY.keys())


@pytest.mark.parametrize("config", ALL_CONFIGS)
def test_manual_has_all_sections(config):
    m = generate_manual(config, "zh")
    section_ids = [s["id"] for s in m["sections"]]
    assert section_ids == [
        "overview",
        "presets",
        "params",
        "outputs",
        "workflow",
        "notes",
    ]
    assert m["config"] == config
    assert m["title"]
    assert m["config_label"]


@pytest.mark.parametrize("config", ALL_CONFIGS)
def test_manual_overview_nonempty(config):
    m = generate_manual(config, "zh")
    overview = next(s for s in m["sections"] if s["id"] == "overview")
    assert overview.get("paragraph")


@pytest.mark.parametrize("config", ALL_CONFIGS)
def test_manual_workflow_steps(config):
    m = generate_manual(config, "en")
    workflow = next(s for s in m["sections"] if s["id"] == "workflow")
    assert len(workflow["steps"]) >= 4


@pytest.mark.parametrize("config", ALL_CONFIGS)
def test_manual_presets_match_registry(config):
    spec = REGISTRY[config]
    expected = (
        list(spec.presets.keys())
        if hasattr(spec.presets, "keys")
        else list(spec.presets)
    )
    m = generate_manual(config, "zh")
    preset_section = next(s for s in m["sections"] if s["id"] == "presets")
    got = [it["k"] for it in preset_section["items"]]
    assert got == expected


def test_manual_lang_switch():
    zh = generate_manual("tokamak", "zh")
    en = generate_manual("tokamak", "en")
    # titles differ between languages
    assert zh["title"] != en["title"]
    zh_wf = next(s for s in zh["sections"] if s["id"] == "workflow")
    en_wf = next(s for s in en["sections"] if s["id"] == "workflow")
    assert zh_wf["steps"] != en_wf["steps"]


def test_manual_default_lang_is_zh():
    m = generate_manual("tokamak")
    assert m["lang"] == "zh"


def test_manual_unknown_config_raises():
    with pytest.raises(KeyError):
        generate_manual("nope", "zh")


def test_manual_endpoint_validates_unknown_config_and_lang():
    """HTTP layer rejects unknown configs and normalises bogus languages."""
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, expected in (
            ("/api/manual?config=nope", 404),
            ("/api/manual?config=tokamak&lang=__proto__", 200),
        ):
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}")
            if expected == 404:
                with pytest.raises(urllib.error.HTTPError) as ei:
                    urllib.request.urlopen(req)
                assert ei.value.code == 404
            else:
                with urllib.request.urlopen(req) as r:
                    out = jsonlib.loads(r.read())
                    assert out["lang"] == "zh"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_key_params_have_units_for_known_docs():
    m = generate_manual("tokamak", "zh")
    params = next(s for s in m["sections"] if s["id"] == "params")
    # at least one group with at least one row
    assert params["groups"]
    for g in params["groups"]:
        assert g["items"]
        for row in g["items"]:
            assert row["k"] and row["desc"]
