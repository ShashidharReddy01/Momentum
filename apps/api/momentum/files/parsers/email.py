"""Email: .eml (stdlib ``email``) and Outlook .msg (extract-msg): headers, the plain body (an
HTML-only body as text) and attachment names. Attachments inside an email aren't opened."""

from __future__ import annotations

import io
from email import policy
from email.parser import BytesParser
from typing import Any

from momentum.files.model import EmailInfo, ParseResult
from momentum.files.parsers.base import Builder
from momentum.files.parsers.text import html_to_text


def _addresses(value: object) -> list[str]:
    if not value:
        return []
    return [a.strip() for a in str(value).split(",") if a.strip()]


def parse_eml(data: bytes, filename: str, mime: str) -> ParseResult:
    b = Builder(data, filename, mime, "email")
    msg = BytesParser(policy=policy.default).parse(io.BytesIO(data))
    attachments: list[dict[str, str | int]] = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        attachments.append({"name": part.get_filename() or "attachment", "size": len(payload)})
    b.model.email = EmailInfo(
        sender=str(msg["from"]) if msg["from"] else None,
        to=_addresses(msg["to"]),
        cc=_addresses(msg["cc"]),
        subject=str(msg["subject"]) if msg["subject"] else None,
        date=str(msg["date"]) if msg["date"] else None,
        attachments=attachments,
    )
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        text = html_to_text(content) if body.get_content_type() == "text/html" else content
        b.text(text, "body")
    return b.done()


def parse_msg(data: bytes, filename: str, mime: str) -> ParseResult:
    import extract_msg

    b = Builder(data, filename, mime, "email")
    msg: Any = extract_msg.openMsg(data)  # a Message: its fields aren't on the base type
    try:
        attachments: list[dict[str, str | int]] = []
        for a in getattr(msg, "attachments", []) or []:
            name = (
                getattr(a, "longFilename", None)
                or getattr(a, "shortFilename", None)
                or "attachment"
            )
            raw = getattr(a, "data", None)
            attachments.append(
                {"name": str(name), "size": len(raw) if isinstance(raw, bytes) else 0}
            )
        b.model.email = EmailInfo(
            sender=msg.sender or None,
            to=_addresses(msg.to),
            cc=_addresses(msg.cc),
            subject=msg.subject or None,
            date=str(msg.date) if getattr(msg, "date", None) else None,
            attachments=attachments,
        )
        body = msg.body
        if not body and getattr(msg, "htmlBody", None):
            raw = msg.htmlBody
            body = html_to_text(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        if body:
            b.text(body, "body")
    finally:
        msg.close()
    return b.done()
