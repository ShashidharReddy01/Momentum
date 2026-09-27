"""S4.2.1: form management (create, edit, delete) and submission.

Who may manage a project's forms: project admins, same as rules (``domain/rules/service.py``).
Any visible role may see and submit the *internal* (logged-in) link; the *public* link (no
session) is served by its own unauthenticated endpoints in ``router.py`` and never touches
``CtxDep``.

A submission always creates the task as the **form's owner** (S4.2.1 carry-over decision): the
public link has no session to build a real actor from, and using the same actor for the internal
link keeps the two paths identical below ``submit_form`` — intake is a controlled channel, not a
grant of the submitter's own edit rights. ``submitted_by`` on the ``form_submissions`` row is the
only place the logged-in submitter's identity is kept.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Diff, record_activity
from momentum.core.context import Actor, Ctx
from momentum.core.errors import (
    Forbidden,
    NotFound,
    TooManyRequests,
    ValidationFailed,
    VersionConflict,
)
from momentum.core.events import emit
from momentum.core.mutation import Mutation
from momentum.core.settings import Settings
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.fields.models import FieldDef, ProjectField
from momentum.domain.fields.service import set_task_field_value, validate_value
from momentum.domain.forms.models import Form, FormSubmission
from momentum.domain.forms.schemas import (
    FIXED_TARGETS,
    MAX_ANSWER_TEXT,
    FormIn,
    FormPatchIn,
    FormSpec,
    PublicFormOut,
    PublicOption,
    PublicQuestionOut,
    SubmitFormIn,
    is_custom_field,
)
from momentum.domain.projects.models import Project
from momentum.domain.projects.service import project_members
from momentum.domain.sections.models import Section
from momentum.domain.tasks.service import create_task, update_task
from momentum.domain.users.models import User

MAX_TEXT = 500  # task title


def _channels(project_id: uuid.UUID) -> list[str]:
    return [f"project:{project_id}"]


def _text_doc(text: str) -> dict[str, Any]:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in lines
            if line
        ],
    }


async def authorize_manage(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID) -> Project:
    project, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "admin", "manage forms")
    return project


async def _load(
    session: AsyncSession, ctx: Ctx, form_id: uuid.UUID, needed: str, what: str
) -> Form:
    form = await session.get(Form, form_id)
    if form is None or form.workspace_id != ctx.workspace_id or form.deleted_at is not None:
        raise NotFound("Form not found")
    _project, role = await get_visible_project(session, ctx, form.project_id)
    require_project_role(role, needed, what)
    return form


async def _project_fields(
    session: AsyncSession, project_id: uuid.UUID
) -> dict[uuid.UUID, FieldDef]:
    """A project's attached custom fields, by id — no ctx needed: the public endpoint (no
    session) reads this too, for the fields a form's own admin already chose to ask about."""
    rows = await session.execute(
        select(FieldDef)
        .join(ProjectField, ProjectField.field_id == FieldDef.id)
        .where(ProjectField.project_id == project_id, FieldDef.deleted_at.is_(None))
    )
    return {f.id: f for f in rows.scalars()}


async def _check_targets(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, spec: FormSpec
) -> None:
    attached = await _project_fields(session, project_id)
    for q in spec.questions:
        if q.maps_to in FIXED_TARGETS:
            continue
        field = attached.get(uuid.UUID(q.maps_to))
        if field is None:
            raise ValidationFailed("A question's field isn't attached to this project")
        if field.type == "people":
            raise ValidationFailed("A form can't ask for a people field directly")


async def list_forms(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID) -> list[Form]:
    await get_visible_project(session, ctx, project_id)
    rows = await session.execute(
        select(Form)
        .where(
            Form.workspace_id == ctx.workspace_id,
            Form.project_id == project_id,
            Form.deleted_at.is_(None),
        )
        .order_by(Form.created_at, Form.id)
    )
    return list(rows.scalars())


async def get_form(session: AsyncSession, ctx: Ctx, form_id: uuid.UUID) -> Form:
    return await _load(session, ctx, form_id, "editor", "see this form")


async def create_form(session: AsyncSession, ctx: Ctx, data: FormIn) -> Mutation[Form]:
    if ctx.actor.id is None:
        raise Forbidden("Forms need a person to act as")
    await authorize_manage(session, ctx, data.project_id)
    spec = FormSpec.model_validate({"questions": [q.model_dump() for q in data.questions]})
    await _check_targets(session, ctx, data.project_id, spec)
    if data.section_id is not None:
        section = await session.get(Section, data.section_id)
        if (
            section is None
            or section.deleted_at is not None
            or section.project_id != data.project_id
        ):
            raise ValidationFailed("That section isn't in this project")
    form = Form(
        workspace_id=ctx.workspace_id,
        project_id=data.project_id,
        section_id=data.section_id,
        name=data.name,
        description=data.description,
        questions=[q.model_dump() for q in data.questions],
        enabled=data.enabled,
        public_enabled=data.public_enabled,
        public_token=secrets.token_urlsafe(24),
        created_by=ctx.actor.id,
    )
    session.add(form)
    await session.flush()
    act = await record_activity(
        session,
        ctx,
        entity_type="form",
        entity_id=form.id,
        verb="form.created",
        changes={"name": (None, form.name)},
    )
    await emit(
        session,
        ctx,
        type="form.created",
        entity_type="form",
        entity_id=form.id,
        data={"project_id": str(form.project_id)},
        channels=_channels(form.project_id),
        activity_id=act.id,
    )
    return Mutation(form, act.id, version=form.version)


async def update_form(
    session: AsyncSession, ctx: Ctx, form_id: uuid.UUID, data: FormPatchIn
) -> Mutation[Form]:
    form = await _load(session, ctx, form_id, "admin", "manage forms")
    if data.expected_version is not None and data.expected_version != form.version:
        raise VersionConflict("This form was changed by someone else", version=form.version)
    sent = data.model_fields_set
    if "questions" in sent:
        spec = FormSpec.model_validate(
            {"questions": [q.model_dump() for q in data.questions or []]}
        )
        await _check_targets(session, ctx, form.project_id, spec)
    if "section_id" in sent and data.section_id is not None:
        section = await session.get(Section, data.section_id)
        if (
            section is None
            or section.deleted_at is not None
            or section.project_id != form.project_id
        ):
            raise ValidationFailed("That section isn't in this project")
    changes: Diff = {}
    for key in ("name", "description", "section_id", "enabled", "public_enabled"):
        if key not in sent:
            continue
        value = getattr(data, key)
        if getattr(form, key) != value:
            changes[key] = (getattr(form, key), value)
            setattr(form, key, value)
    if "questions" in sent:
        new_questions = [q.model_dump() for q in data.questions or []]
        if form.questions != new_questions:
            changes["questions"] = (form.questions, new_questions)
            form.questions = new_questions
    if not changes:
        return Mutation(form, version=form.version)
    form.version += 1
    form.updated_at = datetime.now(UTC)
    act = await record_activity(
        session, ctx, entity_type="form", entity_id=form.id, verb="form.updated", changes=changes
    )
    await emit(
        session,
        ctx,
        type="form.updated",
        entity_type="form",
        entity_id=form.id,
        data={"changes": sorted(changes), "version": form.version},
        channels=_channels(form.project_id),
        activity_id=act.id,
    )
    return Mutation(form, act.id, version=form.version)


async def delete_form(session: AsyncSession, ctx: Ctx, form_id: uuid.UUID) -> Mutation[Form]:
    form = await _load(session, ctx, form_id, "admin", "manage forms")
    form.deleted_at = datetime.now(UTC)
    form.version += 1
    act = await record_activity(
        session, ctx, entity_type="form", entity_id=form.id, verb="form.deleted"
    )
    await emit(
        session,
        ctx,
        type="form.deleted",
        entity_type="form",
        entity_id=form.id,
        data={"project_id": str(form.project_id)},
        channels=_channels(form.project_id),
        activity_id=act.id,
    )
    return Mutation(form, act.id, version=form.version)


# ---------------- public view ----------------


async def get_public_form(session: AsyncSession, token: str) -> Form:
    """Not found covers every reason the link doesn't work (bad token, disabled, public link
    off, project archived) so no response ever hints at which one it was."""
    form = (
        await session.execute(
            select(Form).where(
                Form.public_token == token, Form.deleted_at.is_(None), Form.enabled.is_(True)
            )
        )
    ).scalar_one_or_none()
    if form is None or not form.public_enabled:
        raise NotFound("This form isn't available")
    project = await session.get(Project, form.project_id)
    if project is None or project.deleted_at is not None or project.archived_at is not None:
        raise NotFound("This form isn't available")
    return form


def _base_fields(q: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": q["id"],
        "label": q["label"],
        "help_text": q.get("help_text"),
        "required": q["required"],
        "show_if": q.get("show_if"),
    }


async def _question_view(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: dict[str, Any],
    fields: dict[uuid.UUID, FieldDef],
) -> PublicQuestionOut:
    base = _base_fields(q)
    maps_to = q["maps_to"]
    if maps_to == "title":
        return PublicQuestionOut(kind="short_text", **base)
    if maps_to == "description":
        return PublicQuestionOut(kind="long_text", **base)
    if maps_to == "due_on":
        return PublicQuestionOut(kind="date", **base)
    if maps_to == "priority":
        priority_options = [
            PublicOption(id=p, label=p.capitalize()) for p in ("urgent", "high", "medium", "low")
        ]
        return PublicQuestionOut(kind="select", options=priority_options, **base)
    if maps_to == "assignee":
        members = await project_members(session, project_id)
        people = [PublicOption(id=str(u.id), label=u.name) for u, _role in members]
        return PublicQuestionOut(kind="person", people=people, **base)
    field = fields[uuid.UUID(maps_to)]
    if field.type in ("text", "url"):
        return PublicQuestionOut(kind="short_text", **base)
    if field.type in ("number", "currency", "percent"):
        return PublicQuestionOut(kind="number", **base)
    if field.type == "date":
        return PublicQuestionOut(kind="date", **base)
    if field.type == "checkbox":
        return PublicQuestionOut(kind="checkbox", **base)
    field_options = [
        PublicOption(id=o["id"], label=o["label"])
        for o in (field.options or [])
        if not o.get("archived")
    ]
    if field.type == "multi_select":
        return PublicQuestionOut(kind="multi_select", options=field_options, **base)
    return PublicQuestionOut(kind="select", options=field_options, **base)


async def public_form_view(session: AsyncSession, form: Form) -> PublicFormOut:
    fields = await _project_fields(session, form.project_id)
    questions = [await _question_view(session, form.project_id, q, fields) for q in form.questions]
    return PublicFormOut(name=form.name, description=form.description, questions=questions)


# ---------------- submission ----------------


def hash_ip(settings: Settings, ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"{settings.forms_ip_hash_salt}:{ip}".encode()).hexdigest()


async def _rate_limit(
    session: AsyncSession, settings: Settings, form_id: uuid.UUID, ip_hash: str | None
) -> None:
    since = datetime.now(UTC) - timedelta(minutes=settings.forms_rate_limit_window_minutes)
    total = (
        await session.execute(
            select(func.count())
            .select_from(FormSubmission)
            .where(FormSubmission.form_id == form_id, FormSubmission.created_at >= since)
        )
    ).scalar_one()
    if total >= settings.forms_rate_limit_per_form:
        raise TooManyRequests("This form has received a lot of submissions. Try again later.")
    if ip_hash is not None:
        from_ip = (
            await session.execute(
                select(func.count())
                .select_from(FormSubmission)
                .where(
                    FormSubmission.form_id == form_id,
                    FormSubmission.ip_hash == ip_hash,
                    FormSubmission.created_at >= since,
                )
            )
        ).scalar_one()
        if from_ip >= settings.forms_rate_limit_per_ip:
            raise TooManyRequests(
                "You've submitted this form a few times already. Try again later."
            )


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == []


def _visible_questions(
    questions: list[dict[str, Any]], answers: dict[str, Any]
) -> list[dict[str, Any]]:
    """Branching v1: a question whose ``show_if`` doesn't match its answer isn't shown, so it's
    neither required nor written even if the caller sent a value for it anyway."""
    out = []
    for q in questions:
        show_if = q.get("show_if")
        if show_if is not None and answers.get(show_if["question_id"]) != show_if["equals"]:
            continue
        out.append(q)
    return out


async def submit_form(
    session: AsyncSession,
    settings: Settings,
    form: Form,
    body: SubmitFormIn,
    *,
    submitted_by: uuid.UUID | None,
    ip_hash: str | None,
    rate_limited: bool,
) -> uuid.UUID | None:
    """Create the task the answers describe, as the form's owner. Returns the new task's id, or
    ``None`` when the honeypot field was filled in (a real success is faked to the caller without
    creating anything, so a bot never learns the trap tripped)."""
    if body.website.strip():
        return None
    if not form.enabled or form.deleted_at is not None:
        raise NotFound("This form isn't accepting submissions")
    if rate_limited:
        await _rate_limit(session, settings, form.id, ip_hash)
    visible = _visible_questions(form.questions, body.answers)
    for q in visible:
        if q["required"] and _is_blank(body.answers.get(q["id"])):
            raise ValidationFailed(f"“{q['label']}” is required")
    owner = await session.get(User, form.created_by)
    if owner is None or owner.status != "active":
        raise Forbidden("This form's owner is no longer active")
    ctx = Ctx(
        actor=Actor(
            id=owner.id,
            workspace_id=owner.workspace_id,
            role=owner.role,
            is_agent=owner.is_agent,
            email=owner.email,
            name=owner.name,
            timezone=owner.timezone,
        ),
        settings=settings,
        via="form",
        request_id=f"form:{form.id}",
    )
    visible_ids = {q["id"] for q in visible}
    title_q = next(q for q in form.questions if q["maps_to"] == "title")
    title = str(body.answers.get(title_q["id"]) or "")[:MAX_TEXT]
    if not title.strip():
        raise ValidationFailed("Title is required")

    def answer(maps_to: str) -> Any:
        q = next((q for q in form.questions if q["maps_to"] == maps_to), None)
        if q is None or q["id"] not in visible_ids:
            return None
        return body.answers.get(q["id"])

    due_raw = answer("due_on")
    due_on = None
    if due_raw:
        try:
            due_on = date.fromisoformat(str(due_raw))
        except ValueError:
            raise ValidationFailed("Invalid due date") from None
    assignee_raw = answer("assignee")
    assignee_id = None
    if assignee_raw:
        try:
            assignee_id = uuid.UUID(str(assignee_raw))
        except ValueError:
            raise ValidationFailed("Invalid assignee") from None

    m = await create_task(
        session,
        ctx,
        form.project_id,
        title,
        section_id=form.section_id,
        assignee_id=assignee_id,
        due_on=due_on,
        priority=answer("priority"),
    )
    task = m.entity[0]
    description_raw = answer("description")
    if description_raw:
        text = str(description_raw)[:MAX_ANSWER_TEXT]
        await update_task(session, ctx, task.id, {"description": _text_doc(text)})
    for q in visible:
        if not is_custom_field(q["maps_to"]):
            continue
        value = body.answers.get(q["id"])
        if _is_blank(value):
            continue
        field = await session.get(FieldDef, uuid.UUID(q["maps_to"]))
        if field is None:
            continue
        clean = validate_value(field, value)
        await set_task_field_value(session, ctx, task.id, field.id, clean)

    session.add(
        FormSubmission(
            workspace_id=form.workspace_id,
            form_id=form.id,
            task_id=task.id,
            answers=dict(body.answers),
            submitted_by=submitted_by,
            ip_hash=ip_hash,
        )
    )
    await session.flush()
    await emit(
        session,
        ctx,
        type="form.submitted",
        entity_type="task",
        entity_id=task.id,
        data={"form_id": str(form.id), "project_id": str(form.project_id)},
        channels=_channels(form.project_id),
    )
    return task.id
