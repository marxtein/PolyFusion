#!/usr/bin/env python3
"""Analyze AI report patterns and replay deterministic reports over a corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from polyfusion.deterministic_report import (  # noqa: E402
    REPORT_ENGINE_VERSION,
    generate_deterministic_report_analysis,
)


REQUIRED_SECTIONS = ("核心结论", "关键指标解读", "风险与不确定性", "下一步建议")
FORBIDDEN_CLAIMS = ("工程可行", "保证进入 H 模", "稳健运行窗口")
SIGNALS = {
    "fixed_tauE": "固定约束时间假设",
    "simplified_geometry": "几何模型较简化",
    "empty_best": "当前准则下未找到最佳区",
    "run_scan_separation": "不能替代 POPCON 工作窗证据",
    "missing_coordinates": "不能给出最佳区实际边界或敏感性方向",
    "radiation_caveat": "不能外推为线辐射始终可忽略",
}
CONFIG_METRICS = {
    "tokamak": ("H98", "betaN", "q95", "nbar_o_nGw"),
    "mirror": ("beta", "coll_ratio", "tau_Past", "tauC_eff"),
    "frc": ("beta", "s_param", "s_over_E", "tau_Bohm"),
    "dipole": ("beta_in", "beta_out", "tauC_eff", "cyclotron_model"),
    "stellarator": ("H_ISS04", "betaT", "nbar_o_Sudo", "iota"),
}
EXPECTED_AI_MODEL = "gpt-5.4"
EXPECTED_AI_PROFILE = "primary"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(value) + b"\n")


def _write_report(path: Path, report: str) -> str:
    payload = report.strip().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + b"\n")
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().rstrip(b"\n")).hexdigest()


def _audit_corpus(corpus_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    prompt_hashes: Counter[str] = Counter()
    for case in manifest["cases"]:
        problems: list[str] = []
        payload_path = corpus_dir / case["payload"]
        scan_path = corpus_dir / case["scan"]
        report_path = corpus_dir / str(case.get("ai_report") or "")
        metadata_path = corpus_dir / str(case.get("ai_report_metadata") or "")
        if not payload_path.is_file() or _file_hash(payload_path) != case["payload_sha256"]:
            problems.append("payload hash mismatch")
        if not scan_path.is_file() or _file_hash(scan_path) != case["scan_sha256"]:
            problems.append("scan hash mismatch")
        if case.get("ai_report_status") != "complete":
            problems.append("AI report is not complete")
        if not report_path.is_file():
            problems.append("AI report file missing")
        if not metadata_path.is_file():
            problems.append("AI report metadata missing")
        if report_path.is_file() and metadata_path.is_file():
            report_hash = _file_hash(report_path)
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {}
                problems.append("AI report metadata is invalid JSON")
            if report_hash != case.get("ai_report_sha256"):
                problems.append("manifest AI report hash mismatch")
            if report_hash != metadata.get("report_sha256"):
                problems.append("metadata AI report hash mismatch")
            if metadata.get("case_id") != case["case_id"]:
                problems.append("metadata case ID mismatch")
            if metadata.get("payload_sha256") != case["payload_sha256"]:
                problems.append("metadata payload hash mismatch")
            if metadata.get("model") != EXPECTED_AI_MODEL:
                problems.append("unexpected AI model")
            if metadata.get("api_profile") != EXPECTED_AI_PROFILE:
                problems.append("unexpected API profile")
            prompt_hash = metadata.get("prompt_sha256")
            if isinstance(prompt_hash, str):
                prompt_hashes[prompt_hash] += 1
            else:
                problems.append("metadata prompt hash missing")
        if problems:
            failures.append({"case_id": case["case_id"], "problems": problems})
    return {
        "case_count": len(manifest["cases"]),
        "expected_model": EXPECTED_AI_MODEL,
        "expected_api_profile": EXPECTED_AI_PROFILE,
        "prompt_hash_counts": dict(prompt_hashes),
        "failure_count": len(failures),
        "failures": failures,
        "passed": not failures and len(manifest["cases"]) == 320,
    }


def _section_coverage(report: str) -> dict[str, bool]:
    return {section: section in report for section in REQUIRED_SECTIONS}


def _best_count(payload: dict[str, Any]) -> int | None:
    matrix = (payload.get("last_scan") or {}).get("best")
    if not isinstance(matrix, list):
        return None
    return sum(int(bool(value)) for row in matrix if isinstance(row, list) for value in row)


def _quality_score(report: str, payload: dict[str, Any]) -> dict[str, Any]:
    outputs = (payload.get("last_run") or {}).get("outputs") or {}
    params = payload.get("params") or {}
    best_count = _best_count(payload)
    checks: dict[str, bool] = {}
    checks["required_sections"] = all(_section_coverage(report).values())
    identity_tokens = [
        str(payload.get("config") or ""),
        str(payload.get("preset") or ""),
        *(key for key in ("valid", "ignited", "Pfus", "Qfus", "Pheat", "Pwall") if key in outputs),
    ]
    checks["core_identity_and_fields"] = all(token in report for token in identity_tokens)
    checks["run_scan_separation"] = (
        "运行点" in report
        and "POPCON" in report
        and ("不等" in report or "不代表" in report)
    )
    checks["best_verdict"] = best_count != 0 or SIGNALS["empty_best"] in report
    checks["fixed_tauE"] = params.get("use_tauE") not in (1, 1.0) or SIGNALS["fixed_tauE"] in report
    checks["simplified_geometry"] = (
        params.get("geom_model") not in (0, 0.0) or SIGNALS["simplified_geometry"] in report
    )
    checks["actionable_tasks"] = "扫描" in report and "监控" in report
    available_metrics = [
        key for key in CONFIG_METRICS[payload["config"]] if key in outputs
    ]
    checks["configuration_metrics"] = not available_metrics or sum(
        key in report for key in available_metrics
    ) >= min(2, len(available_metrics))
    checks["no_forbidden_claims"] = not any(claim in report for claim in FORBIDDEN_CLAIMS)
    passed = sum(checks.values())
    return {
        "score": passed / len(checks),
        "passed_checks": passed,
        "total_checks": len(checks),
        "checks": checks,
    }


def analyze(corpus_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = corpus_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pattern_counts: Counter[str] = Counter()
    ai_section_pass = 0
    ai_forbidden: list[dict[str, str]] = []
    ai_lengths: list[int] = []
    ai_by_config: Counter[str] = Counter()
    ai_quality: list[dict[str, Any]] = []
    corpus_integrity = _audit_corpus(corpus_dir, manifest)

    completed_ai = [
        case
        for case in manifest["cases"]
        if case.get("ai_report_status") == "complete" and case.get("ai_report")
    ]
    for case in completed_ai:
        report = (corpus_dir / case["ai_report"]).read_text(encoding="utf-8")
        payload = json.loads((corpus_dir / case["payload"]).read_text(encoding="utf-8"))
        ai_quality.append({"case_id": case["case_id"], **_quality_score(report, payload)})
        ai_by_config[case["config"]] += 1
        ai_lengths.append(len(report))
        if all(_section_coverage(report).values()):
            ai_section_pass += 1
        for name, phrase in SIGNALS.items():
            if phrase in report:
                pattern_counts[name] += 1
        for claim in FORBIDDEN_CLAIMS:
            if claim in report:
                ai_forbidden.append({"case_id": case["case_id"], "claim": claim})

    replay_failures: list[dict[str, Any]] = []
    replay_by_config: Counter[str] = Counter()
    replay_signals: Counter[str] = Counter()
    zero_best_cases = 0
    generated = 0
    deterministic_quality: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        payload = json.loads((corpus_dir / case["payload"]).read_text(encoding="utf-8"))
        report = generate_deterministic_report_analysis(payload)
        relative = Path("deterministic-reports") / case["config"] / f"{case['case_id']}.md"
        report_hash = _write_report(corpus_dir / relative, report)
        deterministic_quality.append(
            {"case_id": case["case_id"], **_quality_score(report, payload)}
        )
        generated += 1
        replay_by_config[case["config"]] += 1
        problems: list[str] = []
        missing_sections = [
            section for section, present in _section_coverage(report).items() if not present
        ]
        if missing_sections:
            problems.append("missing sections: " + ", ".join(missing_sections))
        outputs = (payload.get("last_run") or {}).get("outputs") or {}
        for key in ("Pfus", "Qfus", "Pheat", "Pwall"):
            if key in outputs and key not in report:
                problems.append(f"missing core field {key}")
        for claim in FORBIDDEN_CLAIMS:
            if claim in report:
                problems.append(f"forbidden claim {claim}")
        best_count = _best_count(payload)
        if best_count == 0:
            zero_best_cases += 1
            if SIGNALS["empty_best"] not in report:
                problems.append("empty best region not disclosed")
        params = payload.get("params") or {}
        if params.get("use_tauE") in (1, 1.0) and SIGNALS["fixed_tauE"] not in report:
            problems.append("fixed tauE dependency not disclosed")
        if params.get("geom_model") in (0, 0.0) and SIGNALS["simplified_geometry"] not in report:
            problems.append("simplified geometry not disclosed")
        for name, phrase in SIGNALS.items():
            if phrase in report:
                replay_signals[name] += 1
        if problems:
            replay_failures.append(
                {"case_id": case["case_id"], "problems": problems, "report_sha256": report_hash}
            )

    now = datetime.now(timezone.utc).isoformat()
    pattern_report = {
        "generated_at": now,
        "completed_ai_reports": len(completed_ai),
        "pending_ai_reports": len(manifest["cases"]) - len(completed_ai),
        "ai_reports_by_config": dict(ai_by_config),
        "required_sections_pass": ai_section_pass,
        "required_sections_rate": ai_section_pass / len(completed_ai) if completed_ai else None,
        "mean_ai_report_chars": sum(ai_lengths) / len(ai_lengths) if ai_lengths else None,
        "observed_signal_counts": dict(pattern_counts),
        "forbidden_claim_findings": ai_forbidden,
        "quality": {
            "mean_score": (
                sum(item["score"] for item in ai_quality) / len(ai_quality)
                if ai_quality
                else None
            ),
            "perfect_count": sum(item["score"] == 1 for item in ai_quality),
            "case_count": len(ai_quality),
            "cases": ai_quality,
        },
        "interpretation": {
            "common_structure": list(REQUIRED_SECTIONS),
            "shared_rules": list(SIGNALS),
            "configuration_specific_routing": True,
            "evidence_boundary": (
                "Full-corpus structural comparison over 320 archived AI reports; "
                "AI prose is treated as pattern evidence, not scientific ground truth."
            ),
            "source_overclaim_count": len(ai_forbidden),
            "deterministic_policy": (
                "Preserve recurring structure and parameter-sensitive caveats while "
                "rejecting unsupported engineering or operating-window guarantees."
            ),
        },
        "corpus_integrity": corpus_integrity,
        "passed": (
            len(completed_ai) == len(manifest["cases"])
            and corpus_integrity["passed"]
            and ai_section_pass == len(completed_ai)
        ),
    }
    replay_report = {
        "generated_at": now,
        "engine_version": REPORT_ENGINE_VERSION,
        "total_payloads": len(manifest["cases"]),
        "generated_reports": generated,
        "reports_by_config": dict(replay_by_config),
        "zero_best_cases": zero_best_cases,
        "signal_counts": dict(replay_signals),
        "failure_count": len(replay_failures),
        "failures": replay_failures,
        "quality": {
            "mean_score": sum(item["score"] for item in deterministic_quality)
            / len(deterministic_quality),
            "perfect_count": sum(item["score"] == 1 for item in deterministic_quality),
            "case_count": len(deterministic_quality),
            "cases": deterministic_quality,
        },
        "passed": generated == len(manifest["cases"]) and not replay_failures,
    }
    _write_json(corpus_dir / "analysis" / "report-patterns.json", pattern_report)
    _write_json(corpus_dir / "analysis" / "replay-validation.json", replay_report)
    return pattern_report, replay_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "artifacts" / "deterministic-report-corpus",
    )
    args = parser.parse_args()
    patterns, replay = analyze(args.corpus.resolve())
    print(
        f"AI reports={patterns['completed_ai_reports']} pending={patterns['pending_ai_reports']} "
        f"replay={replay['generated_reports']}/{replay['total_payloads']} "
        f"failures={replay['failure_count']}"
    )
    return 0 if replay["passed"] and patterns["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
