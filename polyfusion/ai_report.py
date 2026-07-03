"""AI analysis helper for simulation reports."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://api.codexzh.com/v1"
DEFAULT_MODEL = "gpt-5.4"
MAX_PROMPT_CHARS = 24000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _project_env_path() -> str:
    return os.path.join(ROOT, ".env")


def _load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            if key == "SUPABASE_SERVICE_ROLE_KEY":
                continue
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _load_project_env() -> None:
    _load_env_file(_project_env_path())


class AiReportError(RuntimeError):
    pass


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _safe_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json_value(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json_value(v) for v in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _compact_report_data(data: dict) -> dict:
    clean = dict(data or {})
    clean.pop("images", None)
    return _safe_json_value(clean)


def _extract_text(response: dict) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    if parts:
        return "\n".join(parts).strip()
    raise AiReportError("AI response did not contain text")


def _post_json(
    base_url: str, path: str, payload: dict, api_key: str, timeout: float
) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _responses_payload(model: str, prompt: str) -> dict:
    return {
        "model": model,
        "input": prompt,
        "reasoning": {
            "effort": os.getenv("OPENAI_REASONING_EFFORT", "high"),
            "summary": os.getenv("OPENAI_REASONING_SUMMARY", "auto"),
        },
        "text": {"verbosity": os.getenv("OPENAI_TEXT_VERBOSITY", "low")},
    }


def _chat_payload(model: str, prompt: str, *, minimal: bool = False) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if not minimal:
        payload["reasoning_effort"] = os.getenv("OPENAI_REASONING_EFFORT", "high")
        payload["verbosity"] = os.getenv("OPENAI_TEXT_VERBOSITY", "low")
    return payload


def generate_ai_report_analysis(data: dict) -> str:
    _load_project_env()
    api_key = os.getenv("CODEX_API_KEY")
    if not api_key:
        raise AiReportError("CODEX_API_KEY is not configured")

    base_url = (
        os.getenv("CODEX_BASE_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    )
    model = os.getenv("CODEX_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    compact = json.dumps(
        _compact_report_data(data), ensure_ascii=False, separators=(",", ":")
    )
    if len(compact) > MAX_PROMPT_CHARS:
        compact = compact[:MAX_PROMPT_CHARS] + "...[truncated]"

    prompt = (
        "你是聚变 0-D 初筛报告分析助手。请只基于下面 JSON 数据做工程解读，"
        "不要编造未提供的数值。用中文输出，结构包括：\n"
        "1. 核心结论\n2. 关键指标解读\n3. 风险与不确定性\n4. 下一步建议\n"
        "保持专业、简洁，适合作为报告附录。\n\n"
        f"报告数据 JSON：{compact}"
    )
    timeout = float(os.getenv("OPENAI_TIMEOUT", "120"))
    endpoint = os.getenv("OPENAI_ENDPOINT", "auto").lower()
    errors: list[str] = []
    requests = []
    if endpoint in ("responses", "auto"):
        requests.append(("/responses", _responses_payload(model, prompt), "responses"))
    if endpoint in ("chat", "chat_completions", "chat-completions", "auto"):
        requests.append(("/chat/completions", _chat_payload(model, prompt), "chat"))
        requests.append(
            (
                "/chat/completions",
                _chat_payload(model, prompt, minimal=True),
                "chat-minimal",
            )
        )

    for path, payload, label in requests:
        try:
            return _extract_text(_post_json(base_url, path, payload, api_key, timeout))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            errors.append(f"{label} {path} HTTP {error.code}: {body}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            errors.append(f"{label} {path}: {error}")

    raise AiReportError("AI API request failed: " + " | ".join(errors))
