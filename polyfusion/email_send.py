"""Stdlib-only SMTP sender for PolyFusion verification emails.

This module is intentionally separate from ``polyfusion.auth`` so that
``auth.py`` does not absorb SMTP/MIME concerns. It uses only standard-library
modules (``smtplib``, ``ssl``, ``email.message``) so the ``app/server.py``
"stdlib-only" contract is preserved when ``server.py`` imports this lazily.

Configuration is read from environment variables; see ``.env.example``:
  - ``POLYFUSION_SMTP_ENABLED`` (truthy → opt in)
  - ``POLYFUSION_SMTP_HOST`` (default: ``smtp.mail.suyuexinghen.cn``)
  - ``POLYFUSION_SMTP_PORT`` (default: ``465``)
  - ``POLYFUSION_SMTP_USER`` (default: ``veloalpha@mail.suyuexinghen.cn``)
  - ``POLYFUSION_SMTP_PASSWORD`` (required when enabled)
  - ``POLYFUSION_SMTP_FROM_NAME`` (default: ``PolyFusion``)

Tests inject a stub sender via the ``sender`` keyword on
``send_verification_email`` so no real network I/O occurs.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Callable, Optional

_DEFAULT_HOST = "smtp.mail.suyuexinghen.cn"
_DEFAULT_PORT = 465
_DEFAULT_USER = "veloalpha@mail.suyuexinghen.cn"
_DEFAULT_FROM_NAME = "PolyFusion"
_CONNECT_TIMEOUT = 10.0

_SMTP_ENABLED_ENV = "POLYFUSION_SMTP_ENABLED"
_SMTP_HOST_ENV = "POLYFUSION_SMTP_HOST"
_SMTP_PORT_ENV = "POLYFUSION_SMTP_PORT"
_SMTP_USER_ENV = "POLYFUSION_SMTP_USER"
_SMTP_PASSWORD_ENV = "POLYFUSION_SMTP_PASSWORD"
_SMTP_FROM_NAME_ENV = "POLYFUSION_SMTP_FROM_NAME"

_TRUTHY = {"1", "true", "yes", "on"}


class EmailSendError(Exception):
    """Raised for any configuration or delivery failure.

    Wraps the underlying SMTP/SSL exception text so callers can surface a
    generic message without leaking credentials or transport detail.
    """


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def smtp_enabled() -> bool:
    return _truthy(os.environ.get(_SMTP_ENABLED_ENV, "0"))


def _smtp_config() -> dict:
    host = (os.environ.get(_SMTP_HOST_ENV) or _DEFAULT_HOST).strip()
    user = (os.environ.get(_SMTP_USER_ENV) or _DEFAULT_USER).strip()
    from_name = (os.environ.get(_SMTP_FROM_NAME_ENV) or _DEFAULT_FROM_NAME).strip()
    password = os.environ.get(_SMTP_PASSWORD_ENV) or ""
    port_raw = (os.environ.get(_SMTP_PORT_ENV) or str(_DEFAULT_PORT)).strip()
    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise EmailSendError("invalid SMTP port") from exc
    if not user:
        raise EmailSendError("SMTP user is not configured")
    if not password:
        raise EmailSendError("SMTP password is not configured")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from_name": from_name,
    }


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def _render_verification_text(verify_url: str) -> str:
    return (
        "欢迎使用 PolyFusion。\n\n"
        "请点击下面的链接完成邮箱验证：\n"
        f"{verify_url}\n\n"
        "该链接在 24 小时后失效。如果您没有注册 PolyFusion，请忽略此邮件。\n"
    )


def _render_verification_html(verify_url: str) -> str:
    return (
        "<div style='font-family:system-ui,sans-serif;line-height:1.6;color:#222'>"
        "<h2 style='margin-bottom:8px'>欢迎使用 PolyFusion</h2>"
        "<p>请点击下面的按钮完成邮箱验证：</p>"
        "<p style='margin:24px 0'>"
        f"<a href='{verify_url}' "
        "style='display:inline-block;padding:10px 20px;background:#2563eb;"
        "color:#fff;border-radius:6px;text-decoration:none'>验证邮箱</a></p>"
        "<p style='font-size:13px;color:#666'>"
        f"或复制以下链接到浏览器：<br><code>{verify_url}</code></p>"
        "<p style='font-size:13px;color:#666'>该链接在 24 小时后失效。"
        "如果您没有注册 PolyFusion，请忽略此邮件。</p>"
        "</div>"
    )


Sender = Callable[[str, str, str, str, str], None]


def _default_sender(
    to_email: str, from_addr: str, subject: str, text_body: str, html_body: str
) -> None:
    cfg = _smtp_config()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP_SSL(
            cfg["host"], cfg["port"], timeout=_CONNECT_TIMEOUT, context=_ssl_ctx()
        ) as smtp:
            smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["user"], [to_email], msg.as_string())
    except EmailSendError:
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise EmailSendError("verification email could not be sent") from exc


def send_verification_email(
    to_email: str, verify_url: str, *, sender: Optional[Sender] = None
) -> None:
    """Send the verification email for ``to_email`` with link ``verify_url``.

    ``sender`` is a callable
    ``(to_email, from_addr, subject, text_body, html_body) -> None`` used in
    tests to record the call instead of opening a real SMTP connection.
    """
    cfg = _smtp_config()
    from_addr = f"{cfg['from_name']} <{cfg['user']}>"
    subject = "【PolyFusion】请验证您的邮箱"
    text_body = _render_verification_text(verify_url)
    html_body = _render_verification_html(verify_url)
    send = sender or _default_sender
    send(to_email, from_addr, subject, text_body, html_body)
