"""Pure Asana → Momentum value mappings (`docs/integrations/asana-import.md §2-4`). No I/O, no
session — kept separate from `service.py` so the mapping rules themselves are unit-testable
without a fake client or a database."""

from __future__ import annotations

TASK_APPROVAL_STATES = ("pending", "approved", "changes_requested", "rejected")


def map_privacy(privacy_setting: str | None) -> str:
    """`public_to_workspace`/`private_to_team` -> `team`; `private` -> `private`; anything else
    (an Asana value this importer doesn't recognize yet) defaults to the safer `private`."""
    if privacy_setting in ("public_to_workspace", "private_to_team"):
        return "team"
    return "private"


def map_task_type(resource_subtype: str | None) -> str | None:
    """`None` means "skip this task" — Asana's legacy `section`-as-task rows aren't real tasks."""
    return {
        "default_task": "task",
        "milestone": "milestone",
        "approval": "approval",
    }.get(resource_subtype or "default_task", "task" if resource_subtype is None else None)


def map_approval_state(approval_status: str | None) -> str | None:
    return approval_status if approval_status in TASK_APPROVAL_STATES else None


def html_to_plain(html_or_notes: str | None) -> str:
    """A deliberately plain fallback, not the spec's full HTML → Tiptap converter (disclosed in
    STATUS.md as this slice's biggest scope cut): strips Asana's `<body>`/`<p>` wrapper tags it
    always emits and returns the inner text as-is. Rich formatting (bold, links, lists, mentions)
    is lost; the text itself is not."""
    import re

    text = html_or_notes or ""
    text = re.sub(r"</p>\s*<p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
