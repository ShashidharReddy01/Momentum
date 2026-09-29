"""S5.3.2: custom fields as the model sees and sets them. The model works in names and labels
("Risk" = "High", a person's name), never ids; these helpers translate both ways. Used by
``get_task`` (a task's fields, their choices and current values) and ``set_field_value``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from momentum.ai.tools.base import ToolContext, ToolError
from momentum.ai.tools.refs import resolve_person
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.fields.service import validate_value
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User

MAX_TEXT = 2000


async def project_fields(tc: ToolContext, task: Task) -> list[FieldDef]:
    """The custom fields of the task's home project, in the project's order."""
    placement = (
        (await tc.session.execute(select(TaskProject).where(TaskProject.task_id == task.id)))
        .scalars()
        .first()
    )
    if placement is None:
        return []
    rows = await tc.session.execute(
        select(FieldDef)
        .join(ProjectField, ProjectField.field_id == FieldDef.id)
        .where(ProjectField.project_id == placement.project_id, FieldDef.deleted_at.is_(None))
        .order_by(ProjectField.position)
    )
    return list(rows.scalars())


def _choices(field: FieldDef) -> list[str]:
    return [
        str(o["label"])
        for o in (field.options or [])
        if isinstance(o, dict) and not o.get("archived")
    ]


def _label(field: FieldDef, option_id: Any) -> str:
    for o in field.options or []:
        if isinstance(o, dict) and o.get("id") == option_id:
            return str(o["label"])
    return "(unknown option)"


async def fields_view(tc: ToolContext, task: Task) -> list[dict[str, Any]]:
    """Each field with its type, its choices (select fields) and the task's value as labels."""
    fields = await project_fields(tc, task)
    if not fields:
        return []
    values = {
        v.field_id: v.value
        for v in (
            await tc.session.execute(select(FieldValue).where(FieldValue.task_id == task.id))
        ).scalars()
    }
    out = []
    for f in fields:
        value = values.get(f.id)
        entry: dict[str, Any] = {"name": f.name, "type": f.type}
        if f.type in ("single_select", "multi_select"):
            entry["choices"] = _choices(f)
        if value is not None:
            if f.type == "single_select":
                value = _label(f, value)
            elif f.type == "multi_select":
                value = [_label(f, v) for v in value]
            elif f.type == "people":
                names = {
                    str(u.id): u.name
                    for u in (
                        await tc.session.execute(
                            select(User).where(User.id.in_([uuid.UUID(v) for v in value]))
                        )
                    ).scalars()
                }
                value = [names.get(str(v), "unknown") for v in value]
            entry["value"] = value
        out.append(entry)
    return out


def _option_id(field: FieldDef, label: Any) -> str:
    want = str(label).strip().lower()
    for o in field.options or []:
        if (
            isinstance(o, dict)
            and not o.get("archived")
            and str(o["label"]).strip().lower() == want
        ):
            return str(o["id"])
    choices = ", ".join(_choices(field))
    raise ToolError(
        "invalid_arguments", f"“{label}” isn't one of {field.name}'s choices ({choices})"
    )


async def to_stored(tc: ToolContext, field: FieldDef, raw: Any) -> Any:
    """The model's value (labels, names, plain values) → what the field stores; ``None`` clears."""
    if raw is None:
        return None
    if field.type == "single_select":
        stored: Any = _option_id(field, raw)
    elif field.type == "multi_select":
        stored = [_option_id(field, v) for v in (raw if isinstance(raw, list) else [raw])]
    elif field.type == "people":
        people = raw if isinstance(raw, list) else [raw]
        stored = [str((await resolve_person(tc, str(p))).id) for p in people]
    elif field.type in ("text", "url"):
        stored = str(raw)[:MAX_TEXT]
    else:
        stored = raw
    try:
        return validate_value(field, stored)
    except Exception as e:  # ValidationFailed: say what the field expects
        raise ToolError("invalid_arguments", f"{field.name}: {getattr(e, 'detail', e)}") from e


def find_field(fields: list[FieldDef], name: str) -> FieldDef:
    want = name.strip().lower()
    for f in fields:
        if f.name.strip().lower() == want:
            return f
    known = ", ".join(f.name for f in fields) or "none"
    raise ToolError("not_found", f"This task's project has no field “{name}” (fields: {known})")
