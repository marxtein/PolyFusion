from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_report_corpus import build_corpus, strip_large_arrays  # noqa: E402
from scripts.generate_ai_report_corpus import (  # noqa: E402
    _backup_api_profile,
    _choose_api_profile,
    _reconcile_completed_reports,
)
from scripts.analyze_report_corpus import _audit_corpus  # noqa: E402


def test_strip_large_arrays_matches_frontend_scan_contract():
    compact = strip_large_arrays(
        {
            "config": "tokamak",
            "xkey": "Ti0",
            "ykey": "ni0",
            "x": [10.0, 20.0],
            "y": [1e20, 2e20],
            "fields": {"Qfus": [[0.5, 1.5], [2.0, 3.0]]},
            "best": [[0, 1], [1, 0]],
            "valid": [[1, 1], [1, 1]],
            "n_invalid": 0,
            "scan_errors": {},
        }
    )
    assert compact == {
        "config": "tokamak",
        "xkey": "Ti0",
        "ykey": "ni0",
        "best": [[0, 1], [1, 0]],
        "n_invalid": 0,
    }
    assert "nx" not in compact
    assert "ny" not in compact
    assert "best_fraction" not in compact


def test_replace_refuses_to_delete_archived_ai_reports(tmp_path):
    output = tmp_path / "corpus"
    report = output / "ai-reports" / "tokamak" / "tokamak-001.md"
    report.parent.mkdir(parents=True)
    report.write_text("archived", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to delete 1 archived AI reports"):
        build_corpus(output, 8, replace=True)

    assert report.read_text(encoding="utf-8") == "archived"


def test_sixth_concurrent_request_uses_backup_profile():
    primary = {"name": "primary"}
    backup = {"name": "backup-brioi"}
    enabled = {"primary": True, "backup-brioi": True}
    active = Counter({"primary": 5})

    assert _choose_api_profile(primary, backup, enabled, active, 5) is backup
    active["primary"] = 4
    assert _choose_api_profile(primary, backup, enabled, active, 5) is primary


def test_disabled_profile_falls_back_to_remaining_api():
    primary = {"name": "primary"}
    backup = {"name": "backup-brioi"}
    active = Counter()
    assert _choose_api_profile(
        primary,
        backup,
        {"primary": False, "backup-brioi": True},
        active,
        5,
    ) is backup
    assert _choose_api_profile(
        primary,
        backup,
        {"primary": False, "backup-brioi": False},
        active,
        5,
    ) is None


def test_backup_profile_reads_only_brioi_files(tmp_path):
    (tmp_path / "config.toml.brioi").write_text(
        'model = "gpt-test"\n'
        'model_provider = "OpenAI"\n'
        'model_reasoning_effort = "xhigh"\n'
        '[model_providers.OpenAI]\n'
        'base_url = "https://backup.example"\n'
        'wire_api = "responses"\n',
        encoding="utf-8",
    )
    (tmp_path / "auth.json.brioi").write_text(
        '{"OPENAI_API_KEY":"backup-secret"}', encoding="utf-8"
    )

    profile = _backup_api_profile(tmp_path)
    assert profile == {
        "name": "backup-brioi",
        "api_key": "backup-secret",
        "base_url": "https://backup.example",
        "model": "gpt-test",
        "endpoint": "responses",
        "reasoning_effort": "xhigh",
        "reasoning_summary": "auto",
        "text_verbosity": "low",
    }


def test_reconcile_migrates_legacy_primary_metadata(tmp_path):
    corpus = tmp_path / "corpus"
    report = corpus / "ai-reports" / "tokamak" / "tokamak-001.md"
    report.parent.mkdir(parents=True)
    report.write_text("report\n", encoding="utf-8")
    report_hash = hashlib.sha256(b"report").hexdigest()
    metadata = report.with_suffix(".json")
    metadata.write_text(
        '{"base_url":"https://primary.example","case_id":"tokamak-001",'
        '"model":"gpt-primary","payload_sha256":"payload",'
        f'"report_sha256":"{report_hash}"}}',
        encoding="utf-8",
    )
    manifest = {
        "cases": [
            {
                "case_id": "tokamak-001",
                "config": "tokamak",
                "payload_sha256": "payload",
                "ai_report_status": "failed",
            }
        ]
    }
    primary = {
        "name": "primary",
        "model": "gpt-primary",
        "base_url": "https://primary.example",
        "endpoint": "auto",
    }

    assert _reconcile_completed_reports(corpus, manifest, [primary]) == 1
    migrated = json.loads(metadata.read_text(encoding="utf-8"))
    assert migrated["api_profile"] == "primary"
    assert migrated["endpoint"] == "auto"
    assert manifest["cases"][0]["ai_report_status"] == "complete"


def test_reconcile_rejects_report_from_disallowed_profile(tmp_path):
    corpus = tmp_path / "corpus"
    report = corpus / "ai-reports" / "tokamak" / "tokamak-001.md"
    report.parent.mkdir(parents=True)
    report.write_text("report\n", encoding="utf-8")
    report_hash = hashlib.sha256(b"report").hexdigest()
    report.with_suffix(".json").write_text(
        '{"api_profile":"backup","base_url":"https://backup.example",'
        '"case_id":"tokamak-001","model":"gpt-backup",'
        '"payload_sha256":"payload",'
        f'"report_sha256":"{report_hash}"}}',
        encoding="utf-8",
    )
    case = {
        "case_id": "tokamak-001",
        "config": "tokamak",
        "payload_sha256": "payload",
        "ai_report_status": "complete",
        "ai_report": "ai-reports/tokamak/tokamak-001.md",
    }
    primary = {
        "name": "primary",
        "model": "gpt-primary",
        "base_url": "https://primary.example",
        "endpoint": "auto",
    }

    assert _reconcile_completed_reports(corpus, {"cases": [case]}, [primary]) == 0
    assert case["ai_report_status"] == "pending"
    assert "ai_report" not in case


def test_reconcile_clears_complete_case_with_missing_metadata(tmp_path):
    case = {
        "case_id": "tokamak-001",
        "config": "tokamak",
        "payload_sha256": "payload",
        "ai_report_status": "complete",
        "ai_report": "ai-reports/tokamak/tokamak-001.md",
        "ai_report_metadata": "ai-reports/tokamak/tokamak-001.json",
    }

    assert _reconcile_completed_reports(tmp_path, {"cases": [case]}, []) == 0
    assert case == {
        "case_id": "tokamak-001",
        "config": "tokamak",
        "payload_sha256": "payload",
        "ai_report_status": "pending",
    }


def test_corpus_audit_rejects_incomplete_case(tmp_path):
    manifest = {
        "cases": [
            {
                "case_id": "tokamak-001",
                "payload": "payloads/tokamak-001.json",
                "payload_sha256": "missing",
                "scan": "scans/tokamak.json",
                "scan_sha256": "missing",
                "ai_report_status": "pending",
            }
        ]
    }

    audit = _audit_corpus(tmp_path, manifest)

    assert audit["passed"] is False
    assert audit["failure_count"] == 1
    assert "AI report is not complete" in audit["failures"][0]["problems"]
