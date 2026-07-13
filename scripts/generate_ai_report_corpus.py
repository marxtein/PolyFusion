#!/usr/bin/env python3
"""Generate and archive AI analyses for a deterministic-report corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SITE_ROOT = ROOT.parent
if (SITE_ROOT / "velo_shared").is_dir() and str(SITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SITE_ROOT))

try:
    from velo_shared.ai import load_brioi_profile
except ImportError:
    load_brioi_profile = None

from polyfusion.ai_report import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    AiReportError,
    _load_project_env,
    generate_ai_report_analysis,
)
from polyfusion.report_templates import AI_REPORT_PROMPT_TEMPLATE  # noqa: E402


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _primary_api_profile() -> dict[str, Any]:
    _load_project_env()
    api_key = os.getenv("CODEX_API_KEY")
    if not api_key:
        raise AiReportError("CODEX_API_KEY is not configured")
    return {
        "name": "primary",
        "api_key": api_key,
        "base_url": (
            os.getenv("CODEX_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or DEFAULT_BASE_URL
        ),
        "model": os.getenv("CODEX_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
        "endpoint": os.getenv("OPENAI_ENDPOINT", "auto"),
        "reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT", "high"),
        "reasoning_summary": os.getenv("OPENAI_REASONING_SUMMARY", "auto"),
        "text_verbosity": os.getenv("OPENAI_TEXT_VERBOSITY", "low"),
    }


def _backup_api_profile(config_dir: Path) -> dict[str, Any]:
    if load_brioi_profile is not None:
        profile = load_brioi_profile(config_dir)
        return {
            "name": profile.name,
            "api_key": profile.api_key,
            "base_url": profile.base_url,
            "model": profile.model,
            "endpoint": profile.endpoint,
            "reasoning_effort": profile.reasoning_effort,
            "reasoning_summary": "auto",
            "text_verbosity": "low",
        }
    config_path = config_dir / "config.toml.brioi"
    auth_path = config_dir / "auth.json.brioi"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    auth = _load_json(auth_path)
    provider_name = str(config.get("model_provider") or "OpenAI")
    provider = (config.get("model_providers") or {}).get(provider_name, {})
    api_key = auth.get("OPENAI_API_KEY")
    if not isinstance(api_key, str) or not api_key:
        raise AiReportError(f"backup OPENAI_API_KEY is missing in {auth_path}")
    base_url = provider.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise AiReportError(f"backup base_url is missing in {config_path}")
    wire_api = str(provider.get("wire_api") or "responses")
    return {
        "name": "backup-brioi",
        "api_key": api_key,
        "base_url": base_url,
        "model": str(config.get("model") or DEFAULT_MODEL),
        "endpoint": "responses" if wire_api == "responses" else "chat",
        "reasoning_effort": str(config.get("model_reasoning_effort") or "high"),
        "reasoning_summary": "auto",
        "text_verbosity": "low",
    }


def _profile_environment(profile: dict[str, Any]) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "CODEX_API_KEY": profile["api_key"],
            "CODEX_BASE_URL": profile["base_url"],
            "CODEX_MODEL": profile["model"],
            "OPENAI_ENDPOINT": profile["endpoint"],
            "OPENAI_REASONING_EFFORT": profile["reasoning_effort"],
            "OPENAI_REASONING_SUMMARY": profile["reasoning_summary"],
            "OPENAI_TEXT_VERBOSITY": profile["text_verbosity"],
        }
    )
    return environment


def _choose_api_profile(
    primary_profile: dict[str, Any],
    backup_profile: dict[str, Any],
    profile_enabled: dict[str, bool],
    active_by_profile: Counter[str],
    primary_concurrency: int,
) -> dict[str, Any] | None:
    primary_name = primary_profile["name"]
    backup_name = backup_profile["name"]
    if (
        profile_enabled[primary_name]
        and active_by_profile[primary_name] < primary_concurrency
    ):
        return primary_profile
    if profile_enabled[backup_name]:
        return backup_profile
    return None


def _write_json(path: Path, value: Any) -> None:
    payload = _canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _write_text(path: Path, value: str) -> str:
    payload = value.strip().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(path)
    return _sha256(payload)


def _validate_payload(corpus_dir: Path, case: dict[str, Any]) -> dict[str, Any]:
    path = corpus_dir / case["payload"]
    raw = path.read_bytes().rstrip(b"\n")
    actual_hash = _sha256(raw)
    if actual_hash != case["payload_sha256"]:
        raise ValueError(
            f"payload hash mismatch for {case['case_id']}: "
            f"expected {case['payload_sha256']}, got {actual_hash}"
        )
    return json.loads(raw)


def _profile_matches_metadata(
    metadata: dict[str, Any], profile: dict[str, Any]
) -> bool:
    metadata_profile = metadata.get("api_profile")
    return (
        (metadata_profile is None or metadata_profile == profile["name"])
        and metadata.get("model") == profile["model"]
        and metadata.get("base_url") == profile["base_url"]
    )


def _clear_report_status(case: dict[str, Any]) -> None:
    case["ai_report_status"] = "pending"
    for key in (
        "ai_report",
        "ai_report_metadata",
        "ai_report_sha256",
        "ai_report_error",
    ):
        case.pop(key, None)


def _reconcile_completed_reports(
    corpus_dir: Path,
    manifest: dict[str, Any],
    allowed_profiles: list[dict[str, Any]],
) -> int:
    """Recover completed cases from immutable report metadata after interruption."""
    recovered = 0
    for case in manifest["cases"]:
        report_relative = Path("ai-reports") / case["config"] / f"{case['case_id']}.md"
        metadata_relative = report_relative.with_suffix(".json")
        report_path = corpus_dir / report_relative
        metadata_path = corpus_dir / metadata_relative
        if not report_path.is_file() or not metadata_path.is_file():
            _clear_report_status(case)
            continue
        try:
            metadata = _load_json(metadata_path)
            report_hash = _sha256(report_path.read_bytes().rstrip(b"\n"))
        except (OSError, json.JSONDecodeError):
            continue
        if not (
            metadata.get("case_id") == case["case_id"]
            and metadata.get("payload_sha256") == case["payload_sha256"]
            and metadata.get("report_sha256") == report_hash
        ):
            _clear_report_status(case)
            continue
        matching_profile = next(
            (
                profile
                for profile in allowed_profiles
                if _profile_matches_metadata(metadata, profile)
            ),
            None,
        )
        if matching_profile is None:
            _clear_report_status(case)
            continue
        if metadata.get("api_profile") is None:
            metadata["api_profile"] = matching_profile["name"]
            metadata.setdefault("endpoint", matching_profile["endpoint"])
            _write_json(metadata_path, metadata)
        was_complete = case.get("ai_report_status") == "complete"
        case.update(
            {
                "ai_report_status": "complete",
                "ai_report": report_relative.as_posix(),
                "ai_report_metadata": metadata_relative.as_posix(),
                "ai_report_sha256": report_hash,
            }
        )
        case.pop("ai_report_error", None)
        recovered += int(not was_complete)
    return recovered


def _generate_case_report(
    corpus_dir: Path,
    case: dict[str, Any],
    *,
    retries: int,
    retry_delay: float,
    profile: dict[str, Any],
    prompt_hash: str,
    hard_timeout: float,
) -> dict[str, Any]:
    payload = _validate_payload(corpus_dir, case)
    payload_path = corpus_dir / case["payload"]
    report_relative = Path("ai-reports") / case["config"] / f"{case['case_id']}.md"
    report_path = corpus_dir / report_relative
    started = time.perf_counter()
    error_message = ""
    for attempt in range(1, retries + 2):
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--single-payload",
                    str(payload_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=hard_timeout if hard_timeout > 0 else None,
                env=_profile_environment(profile),
            )
            if completed.returncode:
                raise AiReportError(completed.stderr.strip() or "AI subprocess failed")
            report = completed.stdout.strip()
            report_hash = _write_text(report_path, report)
            metadata_relative = (
                Path("ai-reports") / case["config"] / f"{case['case_id']}.json"
            )
            completed_at = datetime.now(timezone.utc).isoformat()
            metadata = {
                "case_id": case["case_id"],
                "config": case["config"],
                "preset": case["preset"],
                "api_profile": profile["name"],
                "model": profile["model"],
                "base_url": profile["base_url"],
                "endpoint": profile["endpoint"],
                "prompt_sha256": prompt_hash,
                "payload_sha256": case["payload_sha256"],
                "report_sha256": report_hash,
                "attempts": attempt,
                "runtime_seconds": round(time.perf_counter() - started, 6),
                "completed_at": completed_at,
            }
            _write_json(corpus_dir / metadata_relative, metadata)
            return {
                "status": "complete",
                "ai_report": report_relative.as_posix(),
                "ai_report_metadata": metadata_relative.as_posix(),
                "ai_report_sha256": report_hash,
                "runtime_seconds": metadata["runtime_seconds"],
                "api_profile": profile["name"],
            }
        except (AiReportError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            error_message = str(error)
            fatal_markers = (
                "HTTP 401",
                "额度已用尽",
                "insufficient_quota",
                "invalid token",
                "无效的令牌",
            )
            if any(marker in error_message for marker in fatal_markers):
                return {
                    "status": "failed",
                    "error": error_message.splitlines()[-1][:2000],
                    "fatal": True,
                    "api_profile": profile["name"],
                }
            if attempt <= retries:
                time.sleep(max(retry_delay, 1.0) * attempt)
    return {
        "status": "failed",
        "error": error_message[:2000],
        "fatal": False,
        "api_profile": profile["name"],
    }


def generate_reports(
    corpus_dir: Path,
    *,
    limit: int | None,
    delay: float,
    retries: int,
    force: bool,
    workers: int,
    configs: set[str] | None,
    hard_timeout: float,
    primary_profile: dict[str, Any],
    backup_profile: dict[str, Any],
    primary_concurrency: int,
    backup_enabled: bool,
) -> dict[str, int]:
    manifest_path = corpus_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    allowed_profiles = [primary_profile]
    if backup_enabled:
        allowed_profiles.append(backup_profile)
    recovered = _reconcile_completed_reports(corpus_dir, manifest, allowed_profiles)
    if recovered:
        print(f"recovered={recovered} completed reports from metadata", flush=True)
        _write_json(manifest_path, manifest)
    prompt_hash = _sha256(AI_REPORT_PROMPT_TEMPLATE.encode("utf-8"))
    counts = {"selected": 0, "generated": 0, "skipped": 0, "failed": 0}
    profile_generated: Counter[str] = Counter()
    profiles = {
        primary_profile["name"]: primary_profile,
        backup_profile["name"]: backup_profile,
    }
    profile_enabled = {name: True for name in profiles}
    profile_enabled[backup_profile["name"]] = backup_enabled
    active_by_profile: Counter[str] = Counter()

    candidates: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        if configs and case["config"] not in configs:
            continue
        report_relative = Path("ai-reports") / case["config"] / f"{case['case_id']}.md"
        report_path = corpus_dir / report_relative
        if not force and case.get("ai_report_status") == "complete" and report_path.is_file():
            counts["skipped"] += 1
            continue
        candidates.append(case)
    grouped = {
        config: [case for case in candidates if case["config"] == config]
        for config in ("tokamak", "mirror", "frc", "dipole", "stellarator")
    }
    selected: list[dict[str, Any]] = []
    while any(grouped.values()) and (limit is None or len(selected) < limit):
        for config in grouped:
            if grouped[config] and (limit is None or len(selected) < limit):
                selected.append(grouped[config].pop(0))
    counts["selected"] = len(selected)

    futures: dict[
        concurrent.futures.Future[dict[str, Any]], tuple[dict[str, Any], str]
    ] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        selected_iter = iter(selected)

        def choose_profile() -> dict[str, Any] | None:
            return _choose_api_profile(
                primary_profile,
                backup_profile,
                profile_enabled,
                active_by_profile,
                primary_concurrency,
            )

        def submit_next() -> bool:
            profile = choose_profile()
            if profile is None:
                return False
            try:
                case = next(selected_iter)
            except StopIteration:
                return False
            future = executor.submit(
                _generate_case_report,
                corpus_dir,
                dict(case),
                retries=retries,
                retry_delay=delay,
                profile=profile,
                prompt_hash=prompt_hash,
                hard_timeout=hard_timeout,
            )
            futures[future] = (case, profile["name"])
            active_by_profile[profile["name"]] += 1
            if delay > 0:
                time.sleep(delay)
            return True

        for _ in range(min(workers, len(selected))):
            submit_next()
        completed = 0
        all_profiles_failed = False
        while futures and not all_profiles_failed:
            done, _pending = concurrent.futures.wait(
                tuple(futures), return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                case, profile_name = futures.pop(future)
                active_by_profile[profile_name] -= 1
                completed += 1
                try:
                    result = future.result()
                except Exception as error:
                    result = {
                        "status": "failed",
                        "error": str(error)[:2000],
                        "fatal": False,
                        "api_profile": profile_name,
                    }
                if result["status"] == "complete":
                    case.update(
                        {
                            "ai_report_status": "complete",
                            "ai_report": result["ai_report"],
                            "ai_report_metadata": result["ai_report_metadata"],
                            "ai_report_sha256": result["ai_report_sha256"],
                        }
                    )
                    case.pop("ai_report_error", None)
                    counts["generated"] += 1
                    profile_generated[result["api_profile"]] += 1
                    print(
                        f"[{completed}/{len(selected)}] {case['case_id']} complete "
                        f"({result['runtime_seconds']:.2f}s)",
                        flush=True,
                    )
                else:
                    case["ai_report_status"] = "failed"
                    case["ai_report_error"] = result["error"]
                    counts["failed"] += 1
                    print(
                        f"[{completed}/{len(selected)}] {case['case_id']} failed: "
                        f"{result['error']}",
                        file=sys.stderr,
                        flush=True,
                    )
                _write_json(manifest_path, manifest)
                if result.get("fatal"):
                    failed_profile = result["api_profile"]
                    profile_enabled[failed_profile] = False
                    for pending_future, (_pending_case, pending_profile) in list(
                        futures.items()
                    ):
                        if pending_profile == failed_profile and pending_future.cancel():
                            futures.pop(pending_future)
                            active_by_profile[pending_profile] -= 1
                    print(
                        f"fatal error disabled API profile {failed_profile}",
                        file=sys.stderr,
                    )
                    if not any(profile_enabled.values()):
                        all_profiles_failed = True
                        for pending_future in futures:
                            pending_future.cancel()
                        print("all API profiles disabled; batch stopped", file=sys.stderr)
                        break
                while len(futures) < workers and submit_next():
                    pass

    recovered = _reconcile_completed_reports(corpus_dir, manifest, allowed_profiles)
    if recovered:
        counts["generated"] += recovered
        _write_json(manifest_path, manifest)

    manifest["ai_generation"] = {
        "profiles": {
            name: {
                "base_url": profile["base_url"],
                "model": profile["model"],
                "endpoint": profile["endpoint"],
                "enabled_at_finish": profile_enabled[name],
                "generated_this_run": profile_generated[name],
            }
            for name, profile in profiles.items()
        },
        "primary_concurrency": primary_concurrency,
        "prompt_sha256": prompt_hash,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "complete_count": sum(
            case.get("ai_report_status") == "complete" for case in manifest["cases"]
        ),
        "failed_count": sum(
            case.get("ai_report_status") == "failed" for case in manifest["cases"]
        ),
        "total_count": len(manifest["cases"]),
    }
    _write_json(manifest_path, manifest)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "artifacts" / "deterministic-report-corpus",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--config",
        action="append",
        choices=("tokamak", "mirror", "frc", "dipole", "stellarator"),
        dest="configs",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--hard-timeout", type=float, default=240.0)
    parser.add_argument("--primary-concurrency", type=int, default=5)
    parser.add_argument(
        "--enable-backup",
        action="store_true",
        help="force backup availability even below the primary concurrency limit",
    )
    parser.add_argument(
        "--backup-config-dir",
        type=Path,
        default=Path.home() / ".codex" / "brioi",
    )
    parser.add_argument("--single-payload", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single_payload:
        payload = _load_json(args.single_payload)
        print(generate_ai_report_analysis(payload))
        return 0
    corpus_dir = args.corpus.resolve()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    lock_path = corpus_dir / ".ai-batch.lock"
    lock_file = lock_path.open("a+")
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"another AI batch owns {lock_path}", file=sys.stderr)
            return 2
        primary_profile = _primary_api_profile()
        primary_concurrency = max(0, min(args.primary_concurrency, 5))
        requested_workers = max(1, min(args.workers, 16))
        backup_enabled = args.enable_backup or requested_workers > primary_concurrency
        if backup_enabled:
            backup_profile = _backup_api_profile(args.backup_config_dir.expanduser())
        else:
            backup_profile = {**primary_profile, "name": "backup-disabled"}
        counts = generate_reports(
            corpus_dir,
            limit=args.limit,
            delay=max(args.delay, 0),
            retries=max(args.retries, 0),
            force=args.force,
            workers=requested_workers,
            configs=set(args.configs) if args.configs else None,
            hard_timeout=max(args.hard_timeout, 0),
            primary_profile=primary_profile,
            backup_profile=backup_profile,
            primary_concurrency=primary_concurrency,
            backup_enabled=backup_enabled,
        )
    finally:
        lock_file.close()
        lock_path.unlink(missing_ok=True)
    print(" ".join(f"{key}={value}" for key, value in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
