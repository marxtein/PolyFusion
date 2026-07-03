#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://api.codexzh.com/v1"
DEFAULT_MODEL = "gpt-5.4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask a question through an OpenAI-compatible API."
    )
    parser.add_argument("question", nargs="*", help="Question text. Reads stdin if omitted.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY"),
        help="API key. Prefer CODEX_API_KEY or OPENAI_API_KEY env vars.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help=f"Model name. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--endpoint",
        choices=("responses", "chat"),
        default=os.getenv("OPENAI_ENDPOINT", "responses"),
        help="Use /responses or /chat/completions. Default: responses.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=os.getenv("OPENAI_REASONING_EFFORT", "high"),
        choices=("minimal", "low", "medium", "high"),
        help="Reasoning effort for supported models. Default: high.",
    )
    parser.add_argument(
        "--text-verbosity",
        default=os.getenv("OPENAI_TEXT_VERBOSITY", "low"),
        choices=("low", "medium", "high"),
        help="Text verbosity for supported models. Default: low.",
    )
    parser.add_argument(
        "--reasoning-summary",
        default=os.getenv("OPENAI_REASONING_SUMMARY", "auto"),
        choices=("auto", "concise", "detailed"),
        help="Reasoning summary setting for supported models. Default: auto.",
    )
    parser.add_argument(
        "--system",
        default=os.getenv("OPENAI_SYSTEM_PROMPT", ""),
        help="Optional system prompt.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("OPENAI_TIMEOUT", "120")),
        help="Request timeout in seconds. Default: 120.",
    )
    return parser.parse_args()


def read_question(args: argparse.Namespace) -> str:
    question = " ".join(args.question).strip()
    if question:
        return question
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return input("Question: ").strip()


def build_payload(args: argparse.Namespace, question: str) -> dict:
    if args.endpoint == "chat":
        messages = []
        if args.system:
            messages.append({"role": "system", "content": args.system})
        messages.append({"role": "user", "content": question})
        return {
            "model": args.model,
            "messages": messages,
            "reasoning_effort": args.reasoning_effort,
            "verbosity": args.text_verbosity,
        }

    payload = {
        "model": args.model,
        "input": question,
        "reasoning": {
            "effort": args.reasoning_effort,
            "summary": args.reasoning_summary,
        },
        "text": {"verbosity": args.text_verbosity},
    }
    if args.system:
        payload["instructions"] = args.system
    return payload


def extract_text(data: dict) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    if parts:
        return "\n".join(parts).strip()

    return json.dumps(data, ensure_ascii=False, indent=2)


def call_api(args: argparse.Namespace, question: str) -> dict:
    base_url = args.base_url.rstrip("/")
    path = "/chat/completions" if args.endpoint == "chat" else "/responses"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(build_payload(args, question)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print(
            "Missing API key. Set CODEX_API_KEY or OPENAI_API_KEY, or pass --api-key.",
            file=sys.stderr,
        )
        return 2

    question = read_question(args)
    if not question:
        print("Question is empty.", file=sys.stderr)
        return 2

    try:
        data = call_api(args, question)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"HTTP {error.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"Request failed: {error.reason}", file=sys.stderr)
        return 1

    print(extract_text(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
