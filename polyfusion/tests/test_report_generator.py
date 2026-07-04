"""Tests for polyfusion.report_generator."""

from __future__ import annotations

import os
import re
import sys
import threading
import urllib.error
import urllib.request
import json as jsonlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion import ai_report  # noqa: E402
from polyfusion.report_generator import generate_report  # noqa: E402
from polyfusion.report_templates import build_ai_report_prompt  # noqa: E402


def _sample_data():
    return {
        "config": "tokamak",
        "config_label": "Tokamak",
        "preset": "DEMO",
        "params": {"R0": 5.5, "a": 1.0, "BT0": 5.0, "ni0": 1e20, "Ti0": 15.0},
        "last_run": {
            "config": "tokamak",
            "outputs": {
                "Pfus": 500.0,
                "Qfus": 10.0,
                "Pwall": 2.4,
                "betaN": 2.5,
                "H98": 1.2,
                "tau_E": 3.1,
            },
        },
        "last_scan": {
            "xkey": "ni0",
            "ykey": "Ti0",
            "x": [1e20, 2e20],
            "y": [10.0, 20.0],
            "best": [[1, 0], [0, 1]],
            "n_invalid": 0,
        },
        "images": {
            "popcon": "data:image/png;base64,iVBORw0KGgoAAA==",
            "shape": "data:image/png;base64,iVBORw0KGgoAAA==",
        },
        "user": "tester",
        "lang": "zh",
    }


def test_report_is_self_contained_html():
    html = generate_report(_sample_data())
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    # CSS is inline — no external stylesheet
    assert "<link" not in html
    assert "<style>" in html


def test_report_contains_version_stamp():
    html = generate_report(_sample_data())
    # version is non-empty (either env, git short hash, or "unknown")
    m = re.search(r"PolyFusion · ([^ <·]+) ·", html)
    assert m
    assert m.group(1)


def test_report_version_respects_env_var(monkeypatch):
    monkeypatch.setenv("POLYFUSION_VERSION", "v9.9.9-test")
    html = generate_report(_sample_data())
    assert "v9.9.9-test" in html


def test_report_highlights_key_outputs():
    html = generate_report(_sample_data())
    # Pfus, Qfus, Pwall, betaN should be highlighted rows
    for key in ("Pfus", "Qfus", "Pwall", "betaN"):
        # highlight class appears on the same row as the key
        idx = html.find(key)
        assert idx != -1
        # a class="hl" appears within 200 chars before the key cell
        assert 'class="hl"' in html[max(0, idx - 250) : idx]


def test_report_embeds_images():
    data = _sample_data()
    html = generate_report(data)
    assert 'src="data:image/png;base64,iVBORw0KGgoAAA=="' in html
    assert "<img" in html


def test_report_escapes_malicious_param_value():
    data = _sample_data()
    data["params"]["evil"] = "<script>alert(1)</script>"
    html = generate_report(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_report_rejects_malicious_image_uris():
    data = _sample_data()
    data["images"] = {
        "popcon": "data:image/png;base64,iVBORw0KGgoAAA==",
        "shape": "javascript:alert(1)",
        "profile": "data:text/html,<script>alert(1)</script>",
    }
    html = generate_report(data)
    # only the valid png URI survives; dangerous ones are dropped
    assert "data:image/png;base64,iVBORw0KGgoAAA==" in html
    assert "javascript:alert" not in html
    assert "data:text/html" not in html
    # exactly one img tag rendered
    assert html.count("<img") == 1


def test_report_area_frac_computed_without_numpy():
    """Ensure _summary_text no longer imports numpy for the best-region mean."""
    import sys

    # numpy must not appear as a newly loaded module from this call
    before = set(sys.modules.keys())
    html = generate_report(_sample_data())
    after = set(sys.modules.keys())
    assert "numpy" not in (after - before)
    assert "最佳区占扫描网格 50.0%" in html


def test_report_escapes_malicious_user_field():
    data = _sample_data()
    data["user"] = '"><img src=x onerror=alert(1)>'
    html = generate_report(data)
    # the < > must be escaped so the payload cannot become a real tag;
    # html.escape does not strip attribute-looking text, but without angle
    # brackets the browser renders it as inert text inside the span.
    assert "&lt;img" in html
    assert "&gt;" in html
    # double-quote in the payload must also be escaped so it cannot close
    # the surrounding attribute value
    assert data["user"] not in html


def test_report_lang_switch_changes_section_titles():
    zh = generate_report(_sample_data())
    en_data = _sample_data()
    en_data["lang"] = "en"
    en = generate_report(en_data)
    assert "结论摘要" in zh
    assert "Summary" in en
    assert zh != en


def test_report_includes_basic_and_ai_sections():
    html = generate_report(_sample_data())
    assert "基础报告" in html
    assert "AI 分析报告" in html
    assert "id='aiReport'" in html
    assert "加载中" in html


def test_report_embeds_markdown_export_and_ai_renderer():
    html = generate_report(_sample_data())
    assert "id='exportMarkdown'" in html
    assert "id='saveReport'" in html
    assert "saveReportStatus" in html
    assert "POLYFUSION_REPORT_MARKDOWN" in html
    assert "POLYFUSION_SET_AI_REPORT" in html
    assert "POLYFUSION_SAVE_REPORT" in html
    assert "renderMarkdown" in html
    assert "text/markdown;charset=utf-8" in html


def test_report_handles_minimal_input():
    html = generate_report({})
    assert "<!DOCTYPE html>" in html
    # empty inputs render graceful placeholders, not crashes
    assert "无" in html or "no" in html


def test_report_handles_nan_outputs():
    data = _sample_data()
    data["last_run"]["outputs"]["Pfus"] = float("nan")
    html = generate_report(data)
    # NaN renders as a dash, not "NaN" leaking into the HTML
    assert "NaN" not in html


def test_report_summary_mentions_q_and_pfus():
    html = generate_report(_sample_data())
    assert "Q=" in html
    assert "P_fus=" in html or "P_fus" in html


def test_report_includes_solver_errors_block_when_present():
    data = _sample_data()
    data["last_run"]["errors"] = ["mirror ratio out of range", "wall gap too small"]
    html = generate_report(data)
    assert "mirror ratio out of range" in html
    assert "Solver warnings" in html or "求解器警告" in html


def test_report_default_lang_is_zh():
    data = _sample_data()
    data.pop("lang")
    html = generate_report(data)
    assert "结论摘要" in html
    assert "lang='zh'" in html or 'lang="zh"' in html


def test_report_skips_internal_underscore_params():
    data = _sample_data()
    data["params"]["_geom_mode"] = "equilibrium"
    data["params"]["_internal_cache"] = [1, 2, 3]
    html = generate_report(data)
    assert "_geom_mode" not in html
    assert "_internal_cache" not in html


def test_report_endpoint_serves_html(monkeypatch):
    """End-to-end: POSTing report data to /api/report returns rendered HTML."""
    import app.server as srv

    monkeypatch.setattr(srv, "REQUIRE_AUTH", False)
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = jsonlib.dumps(_sample_data()).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            ctype = response.headers.get("Content-Type", "")
            payload = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert ctype.startswith("text/html")
    assert "<!DOCTYPE html>" in payload
    assert "结论摘要" in payload


def test_ai_report_loads_codex_api_key_from_project_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CODEX_API_KEY=sk-from-env-file\nOPENAI_ENDPOINT=chat\n", encoding="utf-8"
    )
    calls = []

    def fake_post_json(base_url, path, payload, api_key, timeout):
        calls.append(api_key)
        return {"choices": [{"message": {"content": "env ok"}}]}

    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ENDPOINT", raising=False)
    monkeypatch.setattr(ai_report, "_project_env_path", lambda: str(env_file))
    monkeypatch.setattr(ai_report, "_post_json", fake_post_json)
    assert ai_report.generate_ai_report_analysis(_sample_data()) == "env ok"
    assert calls == ["sk-from-env-file"]


def test_ai_report_prompt_uses_strict_template():
    prompt = build_ai_report_prompt('{"config":"tokamak"}')
    assert "PolyFusion 0-D 初筛报告分析助手" in prompt
    assert "当前运行点和 POPCON 扫描" in prompt
    assert '{"config":"tokamak"}' in prompt


def test_ai_report_falls_back_to_minimal_chat_payload(monkeypatch):
    calls = []

    def fake_post_json(base_url, path, payload, api_key, timeout):
        calls.append((path, payload))
        if len(calls) < 3:
            raise urllib.error.HTTPError(
                url="http://example.test",
                code=400,
                msg="bad",
                hdrs=None,
                fp=None,
            )
        return {"choices": [{"message": {"content": "minimal ok"}}]}

    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_ENDPOINT", "auto")
    monkeypatch.setattr(ai_report, "_post_json", fake_post_json)
    assert ai_report.generate_ai_report_analysis(_sample_data()) == "minimal ok"
    assert [path for path, _payload in calls] == [
        "/responses",
        "/chat/completions",
        "/chat/completions",
    ]
    assert "verbosity" in calls[1][1]
    assert "verbosity" not in calls[2][1]


def test_report_cache_lookup_endpoint_serves_hit(monkeypatch):
    import app.server as srv

    calls = []

    def fake_get_report(user_id, cache_key):
        calls.append((user_id, cache_key))
        return {
            "id": "r1",
            "cache_key": cache_key,
            "html": "<!DOCTYPE html><html></html>",
            "ai_analysis": "ok",
        }

    monkeypatch.setattr(srv.Handler, "_require_auth", lambda self: "u1")
    monkeypatch.setattr(srv.report_cache_mod, "get_report", fake_get_report)
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = jsonlib.dumps({"cache_key": "pf-report-v1-a"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report/cache/lookup",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            payload = jsonlib.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert payload["hit"] is True
    assert payload["report"]["ai_analysis"] == "ok"
    assert calls == [("u1", "pf-report-v1-a")]


def test_report_cache_save_endpoint_serves_row(monkeypatch):
    import app.server as srv

    calls = []

    def fake_save_report(user_id, **kwargs):
        calls.append((user_id, kwargs))
        return {"id": "r1", "cache_key": kwargs["cache_key"]}

    monkeypatch.setattr(srv.Handler, "_require_auth", lambda self: "u1")
    monkeypatch.setattr(srv.report_cache_mod, "save_report", fake_save_report)
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = jsonlib.dumps(
            {
                "cache_key": "pf-report-v1-a",
                "config": "tokamak",
                "inputs": {"config": "tokamak"},
                "html": "<!DOCTYPE html><html></html>",
                "ai_analysis": "ok",
            }
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report/cache/save",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            status = response.status
            payload = jsonlib.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert status == 201
    assert payload == {"id": "r1", "cache_key": "pf-report-v1-a"}
    assert calls[0][0] == "u1"
    assert calls[0][1]["cache_key"] == "pf-report-v1-a"


def test_ai_report_endpoint_serves_json(monkeypatch):
    import app.server as srv

    monkeypatch.setattr(srv, "REQUIRE_AUTH", False)
    monkeypatch.setattr(srv, "generate_ai_report_analysis", lambda _req: "AI ok")
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = jsonlib.dumps(_sample_data()).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report/ai",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            payload = jsonlib.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert payload == {"analysis": "AI ok"}


def test_report_endpoint_rejects_oversized_body(monkeypatch):
    import app.server as srv

    monkeypatch.setattr(srv, "REQUIRE_AUTH", False)
    monkeypatch.setattr(srv, "MAX_REPORT_BYTES", 1024)
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # build a body just over 1 KiB
        pad = {"params": {"pad": "x" * 2048}}
        body = jsonlib.dumps(pad).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
        assert ei.value.code == 413
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_frontend_exposes_report_buttons_and_handlers():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    html = open(os.path.join(root, "app", "index.html"), encoding="utf-8").read()
    # header quick-report button
    assert 'id="reportBtn"' in html
    # export-panel full-report button
    assert 'id="genReport"' in html
    # backend endpoints wired
    assert "/api/report" in html
    assert "/api/report/ai" in html
    assert "/api/report/cache/lookup" in html
    assert "/api/report/cache/save" in html
    # JS entry points exist
    assert "function generateSimulationReport" in html
    assert "requestAiReport" in html
    assert "POLYFUSION_SET_AI_REPORT" in html
    assert "reportCacheKey" in html
    assert "lookupReportCache" in html
    assert "saveReportCache" in html
    assert "capturePlotImage" in html
    # size-limit helper: dense arrays must be stripped before upload
    assert "function stripLargeArrays" in html


def test_report_endpoint_requires_auth_in_strict_mode(monkeypatch):
    """When guest mode is off, /api/report must 401 without a session."""
    import app.server as srv

    monkeypatch.setattr(srv, "REQUIRE_AUTH", True)
    monkeypatch.setattr(srv, "GUEST_MODE", False)
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = jsonlib.dumps({}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
        assert ei.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_report_endpoint_allows_guest_current_report(monkeypatch):
    """Guest mode may view the current generated report without history access."""
    import app.server as srv

    monkeypatch.setattr(srv, "REQUIRE_AUTH", True)
    monkeypatch.setattr(srv, "GUEST_MODE", True)
    from app.server import Handler, ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = jsonlib.dumps(_sample_data()).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/report",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            ctype = response.headers.get("Content-Type", "")
            payload = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert ctype.startswith("text/html")
    assert "<!DOCTYPE html>" in payload
    assert "结论摘要" in payload
