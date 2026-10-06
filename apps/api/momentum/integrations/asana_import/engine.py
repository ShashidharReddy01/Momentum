"""S7.4.2: the full Asana import (`docs/integrations/asana-import.md`), as resumable steps.

**Why steps.** A whole workspace is tens of thousands of API calls (every task's comments and
attachments are calls of their own); App Service ends a request after ~230 s, and the token must
never be stored. So an import is a queue of small work items kept in its ``import_jobs`` row
(``log``): each ``run_step`` call takes the token from its caller (the browser or the CLI, which
hold it in memory only), works through items until its time budget is spent, and saves the queue,
the maps it has built and the counts, all in the caller's one transaction: a step that fails or is
cut off leaves the job exactly as the previous step did, and the next call resumes there.

**Idempotent.** Every imported object has an ``external_links(asana, <type>, <gid>)`` row; an
object already linked is reused, never created twice (a task found again in another project gets
that project's placement: multi-homing). Re-running a finished import adds what is new in Asana.

**Dry run.** The same walk without writing anything but the job: counts per type, users that
would be matched or invited, custom fields and how each maps, and everything that can't be
imported, with the reason. Comments and attachments are counted by the real run (each is a call
per task).

**Writes.** Rows are written directly, not through the domain services: an import is history,
not new activity. Going through ``tasks.service`` would notify every assignee, run rules and
agents, and record ~10 activity rows per task. The import records one ``import.finished``
activity and event instead, ``created_via="import"`` on every row it makes, and keeps the original
authors and timestamps.
"""

from __future__ import annotations

import hashlib
import mimetypes
import time
import uuid
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import record_activity
from momentum.core.context import Ctx
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.core.ordering import key_between, keys_between
from momentum.core.richtext import plain_text
from momentum.core.storage import StorageBackend
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment, Reaction
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectField
from momentum.domain.integrations.models import ExternalLink, ImportJob
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Follower, Task, TaskDependency, TaskProject
from momentum.domain.tasks.service import _next_number
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User
from momentum.integrations.asana_import.mapping import (
    map_approval_state,
    map_privacy,
    map_task_type,
)
from momentum.integrations.asana_import.richtext import html_to_doc

STEP_SECONDS = 40.0  # well inside App Service's ~230 s request limit
MAX_SKIPPED = 500  # reasons kept word for word; the rest only counted
LIKE = "\U0001f44d"  # Asana's hearts/likes become a thumbs-up reaction
TEXT_SNAPSHOT = ("formula", "custom_id", "time_tracking", "time_tracking_estimate", "reference")
FIELD_TYPE = {
    "text": "text",
    "enum": "single_select",
    "multi_enum": "multi_select",
    "date": "date",
    "people": "people",
}
STATUS_MAP = {
    "on_track": "on_track",
    "at_risk": "at_risk",
    "off_track": "off_track",
    "on_hold": "on_hold",
    "complete": "complete",
    "achieved": "complete",
    "partial": "at_risk",
    "missed": "off_track",
    "dropped": "on_hold",
}
# Asana's colour names → the nearest project palette token and option colour
PROJECT_COLOR = {
    "dark-red": "proj-1",
    "dark-orange": "proj-2",
    "light-orange": "proj-2",
    "dark-brown": "proj-3",
    "light-green": "proj-4",
    "dark-green": "proj-4",
    "light-teal": "proj-5",
    "dark-teal": "proj-5",
    "light-blue": "proj-6",
    "dark-blue": "proj-6",
    "light-purple": "proj-7",
    "dark-purple": "proj-7",
    "light-pink": "proj-8",
    "dark-pink": "proj-8",
    "light-red": "proj-1",
    "light-yellow": "proj-9",
    "light-warm-gray": "proj-10",
    "dark-warm-gray": "proj-10",
}
OPTION_HEX = {
    "red": "#e5484d",
    "orange": "#f76b15",
    "yellow-orange": "#f5a524",
    "yellow": "#e9c400",
    "yellow-green": "#8db600",
    "green": "#30a46c",
    "blue-green": "#12a594",
    "aqua": "#05a2c2",
    "blue": "#3e63dd",
    "indigo": "#6e56cf",
    "purple": "#8e4ec6",
    "magenta": "#d6409f",
    "hot-pink": "#e93d82",
    "pink": "#f2a7c3",
    "cool-gray": "#8b8d98",
}
DEFAULT_OPTION_HEX = "#94a3b8"


class Source(Protocol):
    """What the engine reads from Asana (the real ``AsanaClient``, or a test fake)."""

    async def workspace_users(self, workspace_gid: str) -> list[dict[str, Any]]: ...
    async def team_users(self, team_gid: str) -> list[dict[str, Any]]: ...
    async def projects(self, team_gid: str) -> list[dict[str, Any]]: ...
    async def custom_field_settings(self, project_gid: str) -> list[dict[str, Any]]: ...
    async def sections(self, project_gid: str) -> list[dict[str, Any]]: ...
    async def tasks(self, section_gid: str) -> list[dict[str, Any]]: ...
    async def subtasks(self, task_gid: str) -> list[dict[str, Any]]: ...
    async def tags(self, workspace_gid: str) -> list[dict[str, Any]]: ...
    async def stories(self, task_gid: str) -> list[dict[str, Any]]: ...
    async def attachments(self, task_gid: str) -> list[dict[str, Any]]: ...
    async def status_updates(self, project_gid: str) -> list[dict[str, Any]]: ...
    async def download(self, url: str, max_bytes: int) -> bytes | None: ...


def _option_id(gid: str) -> str:
    return f"a{gid}"[:32]


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _email(obj: Any) -> str:
    return ((obj or {}).get("email") or "").strip().lower() if isinstance(obj, dict) else ""


class _Run:
    """One step's view of the job: its saved state, the counts, and the helpers that write."""

    def __init__(
        self,
        session: AsyncSession,
        ctx: Ctx,
        source: Source,
        job: ImportJob,
        storage: StorageBackend | None,
        max_upload_bytes: int,
    ) -> None:
        self.s = session
        self.ctx = ctx
        self.src = source
        self.job = job
        self.storage = storage
        self.max_bytes = max_upload_bytes
        self.log: dict[str, Any] = dict(job.log or {})
        self.stats: dict[str, Any] = dict(job.stats or {})
        self.dry: bool = bool(self.log.get("dry_run"))
        self.queue: list[dict[str, Any]] = list(self.log.get("queue") or [])
        self.users: dict[str, str] = dict(self.log.get("users") or {})  # email -> user id
        self.tags: dict[str, str] = dict(self.log.get("tags") or {})  # asana gid -> tag id
        self.fields: dict[str, dict[str, Any]] = dict(self.log.get("fields") or {})
        self.deps: list[list[str]] = list(self.log.get("pending_deps") or [])
        # a dry run links nothing, so it remembers the tasks it has counted (multi-homing)
        self.seen: set[str] = set(self.log.get("dry_seen") or [])

    # ---- state ----

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = int(self.stats.get(key, 0)) + n

    def skip(self, reason: str) -> None:
        self.count("skipped")
        kept: list[str] = self.stats.setdefault("skipped_items", [])
        if len(kept) < MAX_SKIPPED:
            kept.append(reason)

    def unmapped(self, what: str) -> None:
        notes: dict[str, int] = self.stats.setdefault("unmapped", {})
        notes[what] = notes.get(what, 0) + 1

    def save(self) -> None:
        self.log.update(
            queue=self.queue,
            users=self.users,
            tags=self.tags,
            fields=self.fields,
            pending_deps=self.deps,
            dry_seen=sorted(self.seen),
        )
        self.stats["remaining"] = len(self.queue)
        self.job.log = self.log
        self.job.stats = self.stats

    def push_front(self, items: list[dict[str, Any]]) -> None:
        self.queue[:0] = items  # depth-first: a project's sections and tasks before the next

    # ---- links ----

    async def linked(self, entity_type: str, gid: str) -> uuid.UUID | None:
        return (
            await self.s.execute(
                select(ExternalLink.entity_id).where(
                    ExternalLink.workspace_id == self.ctx.workspace_id,
                    ExternalLink.provider == "asana",
                    ExternalLink.entity_type == entity_type,
                    ExternalLink.external_id == gid,
                )
            )
        ).scalar_one_or_none()

    def link(
        self, entity_type: str, gid: str, entity_id: uuid.UUID, url: str | None = None
    ) -> None:
        self.s.add(
            ExternalLink(
                workspace_id=self.ctx.workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                provider="asana",
                external_id=gid,
                url=url[:500] if url else None,
            )
        )

    def user_id(self, obj: Any) -> uuid.UUID | None:
        uid = self.users.get(_email(obj))
        return uuid.UUID(uid) if uid else None

    # ---- the walk ----

    async def item(self, it: dict[str, Any]) -> None:
        handler = {
            "start": self.start,
            "project": self.project,
            "section": self.section,
            "subtasks": self.subtasks,
            "stories": self.stories,
            "attachments": self.attachments,
            "status": self.status_updates,
            "deps": self.dependencies,
            "finish": self.finish,
        }[it["k"]]
        await handler(it)

    async def start(self, it: dict[str, Any]) -> None:
        p = self.log["params"]
        # the team
        team_id = await self.linked("team", p["team_gid"])
        if team_id is None:
            self.count("teams")
            if not self.dry:
                team = Team(
                    workspace_id=self.ctx.workspace_id,
                    name=p["team_name"][:120],
                    created_by=self.ctx.actor.id,
                )
                self.s.add(team)
                await self.s.flush()
                team_id = team.id
                self.link("team", p["team_gid"], team_id)
        self.log["team_id"] = str(team_id) if team_id else None

        # people: matched by email; the rest invited (they sign in later and are the same user)
        existing = {
            e.lower(): str(i)
            for i, e in await self.s.execute(
                select(User.id, User.email).where(User.workspace_id == self.ctx.workspace_id)
            )
        }
        for u in await self.src.workspace_users(p["workspace_gid"]):
            email = _email(u)
            if not email:
                self.count("users_unmatched")
                self.skip(f"person {u.get('name') or u.get('gid')}: no email visible to the token")
                continue
            if email in existing:
                self.users[email] = existing[email]
                self.count("users_matched")
            elif p.get("invite_unmatched", True):
                self.count("users_invited")
                if not self.dry:
                    user = User(
                        workspace_id=self.ctx.workspace_id,
                        email=email,
                        name=(u.get("name") or email.split("@")[0])[:200],
                        role="member",
                        status="invited",
                    )
                    self.s.add(user)
                    await self.s.flush()
                    self.users[email] = str(user.id)
            else:
                self.count("users_unmatched")
        if team_id is not None and not self.dry:
            for u in await self.src.team_users(p["team_gid"]):
                uid = self.users.get(_email(u))
                if uid and await self.s.get(TeamMember, (team_id, uuid.UUID(uid))) is None:
                    self.s.add(TeamMember(team_id=team_id, user_id=uuid.UUID(uid)))

        # tags
        for tg in await self.src.tags(p["workspace_gid"]):
            tag_id = await self.linked("tag", tg["gid"])
            if tag_id is None:
                self.count("tags")
                if not self.dry:
                    tag = Tag(
                        workspace_id=self.ctx.workspace_id,
                        name=(tg.get("name") or "Tag")[:50],
                        color=OPTION_HEX.get(
                            str(tg.get("color") or "").removeprefix("dark-").removeprefix("light-"),
                            DEFAULT_OPTION_HEX,
                        ),
                    )
                    self.s.add(tag)
                    await self.s.flush()
                    tag_id = tag.id
                    self.link("tag", tg["gid"], tag_id)
            if tag_id is not None:
                self.tags[tg["gid"]] = str(tag_id)

        # the projects, then the relations that need everything imported, then the summary
        projects = await self.src.projects(p["team_gid"])
        wanted = set(p.get("project_gids") or [])
        items = [
            {"k": "project", "gid": pr["gid"], "data": _project_data(pr)}
            for pr in projects
            if not wanted or pr["gid"] in wanted
        ]
        missing = wanted - {pr["gid"] for pr in projects}
        for gid in sorted(missing):
            self.skip(f"project {gid}: not in this team (or archived)")
        self.queue.extend([*items, {"k": "deps"}, {"k": "finish"}])

    async def project(self, it: dict[str, Any]) -> None:
        d = it["data"]
        team_id = self.log.get("team_id")
        project_id = await self.linked("project", it["gid"])
        if project_id is None:
            self.count("projects")
            if not self.dry:
                assert team_id is not None and self.ctx.actor.id is not None
                brief = html_to_doc(d.get("html_notes"), d.get("notes"))
                project = Project(
                    workspace_id=self.ctx.workspace_id,
                    team_id=uuid.UUID(team_id),
                    name=(d.get("name") or "Untitled project")[:200],
                    color=PROJECT_COLOR.get(str(d.get("color") or "")),
                    privacy=map_privacy(d.get("privacy_setting")),
                    owner_id=self.user_id(d.get("owner")) or self.ctx.actor.id,
                    default_view=d.get("default_view")
                    if d.get("default_view") in ("list", "board", "calendar", "timeline")
                    else "list",
                    brief=brief,
                    brief_text=plain_text(brief) or None if brief else None,
                    start_on=_date(d.get("start_on")),
                    due_on=_date(d.get("due_on")),
                    archived_at=datetime.now(UTC) if d.get("archived") else None,
                    created_by=self.ctx.actor.id,
                    created_via="import",
                )
                self.s.add(project)
                await self.s.flush()
                project_id = project.id
                self.link("project", it["gid"], project_id, d.get("permalink_url"))
                members = {self.ctx.actor.id: "admin"}
                if project.owner_id:
                    members[project.owner_id] = "admin"
                for uid, role in members.items():
                    self.s.add(ProjectMember(project_id=project_id, user_id=uid, role=role))

        # custom fields: one field per Asana field, attached to each project that uses it
        for cfs in await self.src.custom_field_settings(it["gid"]):
            cf = cfs.get("custom_field") or {}
            if cf.get("gid"):
                await self.field(cf, project_id)

        sections = await self.src.sections(it["gid"])
        items: list[dict[str, Any]] = []
        last: str | None = None
        if project_id is not None:
            last = (
                await self.s.execute(
                    select(func.max(Section.position)).where(Section.project_id == project_id)
                )
            ).scalar_one_or_none()
        for sec in sections:
            section_id = await self.linked("section", sec["gid"])
            if section_id is None:
                self.count("sections")
                if not self.dry:
                    assert project_id is not None
                    last = key_between(last, None)
                    section = Section(
                        workspace_id=self.ctx.workspace_id,
                        project_id=project_id,
                        name=(sec.get("name") or "Untitled section")[:200],
                        position=last,
                    )
                    self.s.add(section)
                    await self.s.flush()
                    section_id = section.id
                    self.link("section", sec["gid"], section_id)
            items.append(
                {
                    "k": "section",
                    "gid": sec["gid"],
                    "project_id": str(project_id) if project_id else None,
                    "section_id": str(section_id) if section_id else None,
                }
            )
        if not self.dry and project_id is not None:
            items.append({"k": "status", "gid": it["gid"], "project_id": str(project_id)})
        self.push_front(items)

    async def field(self, cf: dict[str, Any], project_id: uuid.UUID | None) -> None:
        gid = cf["gid"]
        subtype = cf.get("resource_subtype") or "text"
        known = self.fields.get(gid)
        if known is None:
            if subtype == "number":
                fmt = cf.get("format")
                ftype = (
                    "currency"
                    if fmt == "currency"
                    else "percent"
                    if fmt == "percentage"
                    else "number"
                )
            elif subtype in FIELD_TYPE:
                ftype = FIELD_TYPE[subtype]
            else:
                ftype = "text"  # formulas, ids, time tracking: their shown value, as text
                self.unmapped(f"{subtype} fields imported as a text snapshot")
            field_id = await self.linked("field", gid)
            # an option's id is derived from its Asana id, so a re-run finds it again
            wanted = [
                {
                    "id": _option_id(o["gid"]),
                    "label": (o.get("name") or "Option")[:80],
                    "color": OPTION_HEX.get(str(o.get("color") or ""), DEFAULT_OPTION_HEX),
                    "archived": not o.get("enabled", True),
                }
                for o in cf.get("enum_options") or []
                if o.get("gid")
            ]
            options = {o["gid"]: _option_id(o["gid"]) for o in cf.get("enum_options") or []}
            if field_id is not None:
                existing = await self.s.get(FieldDef, field_id)
                if existing is not None and isinstance(existing.options, list) and wanted:
                    have = {str(o.get("id")) for o in existing.options}
                    added = [o for o in wanted if o["id"] not in have]
                    if added and not self.dry:  # options added in Asana since the last run
                        existing.options = [*existing.options, *added]
            else:
                self.count("custom_fields")
                field_options: Any = None
                if ftype in ("single_select", "multi_select"):
                    field_options = wanted
                elif ftype in ("number", "currency", "percent"):
                    field_options = {"precision": int(cf.get("precision") or 0)}
                    if ftype == "currency" and cf.get("currency_code"):
                        field_options["unit"] = str(cf["currency_code"])[:8]
                if not self.dry:
                    fd = FieldDef(
                        workspace_id=self.ctx.workspace_id,
                        name=(cf.get("name") or "Field")[:100],
                        type=ftype,
                        options=field_options,
                        description=(cf.get("description") or None),
                        is_library=bool(cf.get("is_global_to_workspace", True)),
                        created_by=self.ctx.actor.id,
                    )
                    self.s.add(fd)
                    await self.s.flush()
                    field_id = fd.id
                    self.link("field", gid, field_id)
            known = {
                "id": str(field_id) if field_id else None,
                "type": ftype,
                "subtype": subtype,
                "options": options,
            }
            self.fields[gid] = known
        if not self.dry and project_id is not None and known["id"]:
            fid = uuid.UUID(known["id"])
            if await self.s.get(ProjectField, (project_id, fid)) is None:
                last = (
                    await self.s.execute(
                        select(func.max(ProjectField.position)).where(
                            ProjectField.project_id == project_id
                        )
                    )
                ).scalar_one_or_none()
                self.s.add(
                    ProjectField(
                        project_id=project_id,
                        field_id=fid,
                        position=key_between(last, None),
                        is_visible=True,
                    )
                )
                await self.s.flush()

    async def section(self, it: dict[str, Any]) -> None:
        tasks = await self.src.tasks(it["gid"])
        project_id = uuid.UUID(it["project_id"]) if it.get("project_id") else None
        section_id = uuid.UUID(it["section_id"]) if it.get("section_id") else None
        last: str | None = None
        if section_id is not None:
            last = (
                await self.s.execute(
                    select(func.max(TaskProject.position)).where(
                        TaskProject.section_id == section_id
                    )
                )
            ).scalar_one_or_none()
        follow: list[dict[str, Any]] = []
        keys = keys_between(last, None, len(tasks)) if tasks else []
        for t, pos in zip(tasks, keys, strict=True):
            follow += await self.task(t, project_id, section_id, pos, parent_id=None)
        self.push_front(follow)

    async def subtasks(self, it: dict[str, Any]) -> None:
        subs = await self.src.subtasks(it["gid"])
        parent_id = uuid.UUID(it["task_id"]) if it.get("task_id") else None
        follow: list[dict[str, Any]] = []
        keys = keys_between(None, None, len(subs)) if subs else []
        for st, pos in zip(subs, keys, strict=True):
            follow += await self.task(st, None, None, pos, parent_id=parent_id, subtask=True)
        self.push_front(follow)

    async def task(
        self,
        t: dict[str, Any],
        project_id: uuid.UUID | None,
        section_id: uuid.UUID | None,
        position: str,
        *,
        parent_id: uuid.UUID | None,
        subtask: bool = False,
    ) -> list[dict[str, Any]]:
        """Import one task (or find it again); returns the follow-up items for it."""
        task_type = map_task_type(t.get("resource_subtype"))
        if task_type is None:
            self.skip(f"task {t.get('gid')}: a legacy section row, not a task")
            return []
        task_id = await self.linked("task", t["gid"])
        if self.dry and t["gid"] in self.seen:
            self.count("placements")
            return []
        if self.dry:
            self.seen.add(t["gid"])
        if task_id is not None:
            # found again: another project's list (multi-homing), placed there too
            if (
                not self.dry
                and project_id is not None
                and section_id is not None
                and await self.s.get(TaskProject, (task_id, project_id)) is None
            ):
                self.s.add(
                    TaskProject(
                        task_id=task_id,
                        project_id=project_id,
                        section_id=section_id,
                        position=position,
                        added_by=self.ctx.actor.id,
                    )
                )
                self.count("placements")
            return []

        self.count("subtasks" if subtask else "tasks")
        if task_type == "milestone":
            self.count("milestones")
        elif task_type == "approval":
            self.count("approvals")
        if t.get("assignee") and not self.user_id(t.get("assignee")):
            self.unmapped("assignees not matched to a person")
        follow: list[dict[str, Any]] = []
        if self.dry:
            for dep in t.get("dependencies") or []:
                self.deps.append([t["gid"], dep["gid"] if isinstance(dep, dict) else str(dep)])
            if (t.get("num_subtasks") or 0) > 0:
                follow.append({"k": "subtasks", "gid": t["gid"], "task_id": None})
            self.dry_values(t)
            return follow

        title = (t.get("name") or "Untitled").strip() or "Untitled"
        doc = html_to_doc(t.get("html_notes"), t.get("notes"))
        if len(title) > 500 and doc is None:
            doc = html_to_doc(None, title)
        completed = bool(t.get("completed"))
        task = Task(
            workspace_id=self.ctx.workspace_id,
            number=await _next_number(self.s, self.ctx.workspace_id),
            title=title[:500],
            description=doc,
            description_text=plain_text(doc) or None if doc else None,
            type=task_type,
            approval_state=map_approval_state(t.get("approval_status"))
            if task_type == "approval"
            else None,
            assignee_id=self.user_id(t.get("assignee")),
            start_on=_date(t.get("start_on")),
            due_on=_date(t.get("due_on")) or _date(t.get("due_at")),
            due_at=_datetime(t.get("due_at")),
            completed_at=(_datetime(t.get("completed_at")) or datetime.now(UTC))
            if completed
            else None,
            parent_id=parent_id,
            parent_position=position if parent_id else None,
            created_by=self.user_id(t.get("created_by")),
            created_via="import",
        )
        created_at = _datetime(t.get("created_at"))
        if created_at:
            task.created_at = created_at
        self.s.add(task)
        await self.s.flush()
        self.link("task", t["gid"], task.id, t.get("permalink_url"))
        if project_id is not None and section_id is not None:
            self.s.add(
                TaskProject(
                    task_id=task.id,
                    project_id=project_id,
                    section_id=section_id,
                    position=position,
                    added_by=self.ctx.actor.id,
                )
            )
        for tg in t.get("tags") or []:
            gid = tg["gid"] if isinstance(tg, dict) else str(tg)
            if gid in self.tags:
                self.s.add(TaskTag(task_id=task.id, tag_id=uuid.UUID(self.tags[gid])))
                self.count("tag_links")
        followers = {self.user_id(f) for f in t.get("followers") or []} - {None}
        for uid in followers:
            assert uid is not None
            self.s.add(Follower(task_id=task.id, user_id=uid))
        self.count("followers", len(followers))
        likers = {self.user_id((lk or {}).get("user")) for lk in t.get("likes") or []} - {None}
        for uid in likers:
            assert uid is not None
            self.s.add(
                Reaction(
                    workspace_id=self.ctx.workspace_id,
                    entity_type="task",
                    entity_id=task.id,
                    user_id=uid,
                    emoji=LIKE,
                )
            )
        self.count("likes", len(likers))
        await self.values(task.id, t)
        for dep in t.get("dependencies") or []:
            dgid = dep["gid"] if isinstance(dep, dict) else str(dep)
            self.deps.append([t["gid"], dgid])
        await self.s.flush()
        tid = str(task.id)
        if (t.get("num_subtasks") or 0) > 0:
            follow.append({"k": "subtasks", "gid": t["gid"], "task_id": tid})
        follow.append({"k": "stories", "gid": t["gid"], "task_id": tid})
        follow.append({"k": "attachments", "gid": t["gid"], "task_id": tid})
        return follow

    def _value(self, cf: dict[str, Any], known: dict[str, Any]) -> Any:
        ftype = known["type"]
        if known["subtype"] in TEXT_SNAPSHOT or (ftype == "text" and known["subtype"] != "text"):
            text = cf.get("display_value")
            return str(text)[:2000] if text not in (None, "") else None
        if ftype == "text":
            return (cf.get("text_value") or None) and str(cf["text_value"])[:2000]
        if ftype in ("number", "currency", "percent"):
            n = cf.get("number_value")
            return n if isinstance(n, int | float) and not isinstance(n, bool) else None
        if ftype == "single_select":
            ev = cf.get("enum_value") or {}
            oid = known["options"].get(ev.get("gid") or "")
            if ev and oid is None:
                self.unmapped("select values whose option wasn't found")
            return oid
        if ftype == "multi_select":
            ids = [known["options"].get(v.get("gid")) for v in cf.get("multi_enum_values") or []]
            return [i for i in ids if i] or None
        if ftype == "date":
            dv = cf.get("date_value") or {}
            return (dv.get("date") or (dv.get("date_time") or "")[:10]) or None
        if ftype == "people":
            ids = [str(u) for u in (self.user_id(p) for p in cf.get("people_value") or []) if u]
            return ids or None
        return None

    async def values(self, task_id: uuid.UUID, t: dict[str, Any]) -> None:
        for cf in t.get("custom_fields") or []:
            known = self.fields.get(cf.get("gid") or "")
            if known is None:
                await self.field(cf, None)  # a field the project settings didn't list
                known = self.fields.get(cf.get("gid") or "")
            if known is None or not known.get("id"):
                continue
            value = self._value(cf, known)
            if value is None:
                continue
            self.s.add(
                FieldValue(
                    task_id=task_id,
                    field_id=uuid.UUID(known["id"]),
                    value=value,
                    updated_by=self.ctx.actor.id,
                )
            )
            self.count("field_values")

    def dry_values(self, t: dict[str, Any]) -> None:
        for cf in t.get("custom_fields") or []:
            known = self.fields.get(cf.get("gid") or "")
            if known is not None and self._value(cf, known) is not None:
                self.count("field_values")

    async def stories(self, it: dict[str, Any]) -> None:
        task_id = uuid.UUID(it["task_id"])
        for st in await self.src.stories(it["gid"]):
            if (st.get("resource_subtype") or st.get("type")) not in ("comment_added", "comment"):
                self.count("history_skipped")  # "assigned to", "changed the due date"…
                continue
            if await self.linked("comment", st["gid"]) is not None:
                continue
            author = self.user_id(st.get("created_by"))
            doc = html_to_doc(st.get("html_text"), st.get("text"))
            if doc is None:
                continue
            if author is None:
                who = (st.get("created_by") or {}).get("name") or "someone"
                doc["content"].insert(
                    0,
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": f"From Asana, by {who}:",
                                "marks": [{"type": "italic"}],
                            }
                        ],
                    },
                )
            comment = Comment(
                workspace_id=self.ctx.workspace_id,
                task_id=task_id,
                author_id=author,
                body=doc,
                body_text=plain_text(doc),
                created_via="import",
            )
            when = _datetime(st.get("created_at"))
            if when:
                comment.created_at = when
            self.s.add(comment)
            await self.s.flush()
            self.link("comment", st["gid"], comment.id)
            self.count("comments")
            likers = {self.user_id((lk or {}).get("user")) for lk in st.get("likes") or []} - {None}
            for uid in likers:
                assert uid is not None
                self.s.add(
                    Reaction(
                        workspace_id=self.ctx.workspace_id,
                        entity_type="comment",
                        entity_id=comment.id,
                        user_id=uid,
                        emoji=LIKE,
                    )
                )
            self.count("likes", len(likers))

    async def attachments(self, it: dict[str, Any]) -> None:
        task_id = uuid.UUID(it["task_id"])
        for a in await self.src.attachments(it["gid"]):
            if await self.linked("attachment", a["gid"]) is not None:
                continue
            name = (a.get("name") or "file")[:300]
            data: bytes | None = None
            if a.get("host") == "asana" and a.get("download_url") and self.storage is not None:
                if int(a.get("size") or 0) > self.max_bytes:
                    self.skip(f"attachment {name}: larger than the upload limit, kept as a link")
                else:
                    try:
                        data = await self.src.download(a["download_url"], self.max_bytes)
                    except Exception:  # an expired or unreachable link: keep it as a link
                        data = None
            if data:
                assert self.storage is not None and self.ctx.actor.id is not None
                key = f"{self.ctx.workspace_id}/{new_id()}"

                async def chunks(payload: bytes = data) -> Any:
                    yield payload

                await self.storage.save_stream(key, chunks())
                att = Attachment(
                    workspace_id=self.ctx.workspace_id,
                    task_id=task_id,
                    storage_key=key,
                    filename=name,
                    mime=mimetypes.guess_type(name)[0] or "application/octet-stream",
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    extract_status="pending",
                    uploaded_by=self.ctx.actor.id,
                    source="import",
                )
                when = _datetime(a.get("created_at"))
                if when:
                    att.created_at = when
                self.s.add(att)
                await self.s.flush()
                self.link("attachment", a["gid"], att.id)
                self.count("attachments")
                continue
            # a file kept elsewhere (Drive, Dropbox…), or one we couldn't fetch: a link comment
            url = a.get("view_url") or a.get("permanent_url") or a.get("download_url")
            if not url:
                self.skip(f"attachment {name}: no link to keep")
                continue
            doc = {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Attachment from Asana: "},
                            {
                                "type": "text",
                                "text": name,
                                "marks": [{"type": "link", "attrs": {"href": url}}],
                            },
                        ],
                    }
                ],
            }
            comment = Comment(
                workspace_id=self.ctx.workspace_id,
                task_id=task_id,
                author_id=None,
                body=doc,
                body_text=f"Attachment from Asana: {name}",
                created_via="import",
            )
            self.s.add(comment)
            await self.s.flush()
            self.link("attachment", a["gid"], comment.id, url)
            self.count("attachment_links")

    async def status_updates(self, it: dict[str, Any]) -> None:
        project_id = uuid.UUID(it["project_id"])
        latest: tuple[datetime, str] | None = None
        for su in await self.src.status_updates(it["gid"]):
            status = STATUS_MAP.get(su.get("status_type") or "")
            if status is None:
                self.skip(f"status update {su.get('gid')}: unknown status {su.get('status_type')}")
                continue
            when = _datetime(su.get("created_at")) or datetime.now(UTC)
            if latest is None or when > latest[0]:
                latest = (when, status)
            if await self.linked("status_update", su["gid"]) is not None:
                continue
            doc = html_to_doc(su.get("html_text"), su.get("text")) or {"type": "doc", "content": []}
            update = StatusUpdate(
                workspace_id=self.ctx.workspace_id,
                entity_type="project",
                entity_id=project_id,
                status=status,
                title=(su.get("title") or "Status update")[:200],
                body=doc,
                body_text=plain_text(doc),
                author_id=self.user_id(su.get("created_by")),
            )
            update.created_at = when
            self.s.add(update)
            await self.s.flush()
            self.link("status_update", su["gid"], update.id)
            self.count("status_updates")
        if latest is not None:
            project = await self.s.get(Project, project_id)
            if project is not None:
                project.status = latest[1]

    async def dependencies(self, it: dict[str, Any]) -> None:
        if self.dry:
            for task_gid, dep_gid in self.deps:
                if dep_gid in self.seen and dep_gid != task_gid:
                    self.count("dependencies")
                else:
                    self.skip(f"dependency {task_gid} → {dep_gid}: the other task isn't imported")
            self.deps = []
            return
        for task_gid, dep_gid in self.deps:
            a, b = await self.linked("task", task_gid), await self.linked("task", dep_gid)
            if a is None or b is None or a == b:
                self.skip(f"dependency {task_gid} → {dep_gid}: the other task isn't imported")
                continue
            if await self.s.get(TaskDependency, (a, b)) is None:
                self.s.add(TaskDependency(task_id=a, depends_on_id=b, created_by=self.ctx.actor.id))
                self.count("dependencies")
        self.deps = []

    async def finish(self, it: dict[str, Any]) -> None:
        self.job.status = "done"
        self.job.finished_at = datetime.now(UTC)
        if self.dry:
            return
        act = await record_activity(
            self.s,
            self.ctx,
            entity_type="import",
            entity_id=self.job.id,
            verb="import.finished",
            changes={"source": (None, "asana")},
        )
        await emit(
            self.s,
            self.ctx,
            type="import.finished",
            entity_type="import",
            entity_id=self.job.id,
            data={"source": "asana", "projects": self.stats.get("projects", 0)},
            channels=[f"user:{self.ctx.actor.id}"],
            activity_id=act.id,
        )


def _project_data(p: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "name",
        "archived",
        "color",
        "html_notes",
        "notes",
        "owner",
        "privacy_setting",
        "default_view",
        "start_on",
        "due_on",
        "permalink_url",
    )
    out = {k: p.get(k) for k in keep if p.get(k) is not None}
    if isinstance(out.get("owner"), dict):
        out["owner"] = {"email": _email(out["owner"])}
    for k in ("html_notes", "notes"):
        text = out.get(k)
        if isinstance(text, str):
            out[k] = text[:20_000]
    return out


def new_job(
    ctx: Ctx,
    *,
    workspace_gid: str,
    team_gid: str,
    team_name: str,
    project_gids: list[str] | None,
    dry_run: bool,
    invite_unmatched: bool = True,
) -> ImportJob:
    """A job ready to run: its plan, with no token in it."""
    return ImportJob(
        workspace_id=ctx.workspace_id,
        source="asana",
        status="pending",
        started_by=ctx.actor.id,
        stats={"dry_run": dry_run},
        log={
            "version": 2,
            "dry_run": dry_run,
            "params": {
                "workspace_gid": workspace_gid,
                "team_gid": team_gid,
                "team_name": team_name,
                "project_gids": project_gids or [],
                "invite_unmatched": invite_unmatched,
            },
            "queue": [{"k": "start"}],
        },
    )


async def run_step(
    session: AsyncSession,
    ctx: Ctx,
    source: Source,
    job: ImportJob,
    *,
    storage: StorageBackend | None,
    max_upload_bytes: int,
    seconds: float = STEP_SECONDS,
) -> ImportJob:
    """Work through the job's queue until it is empty or ``seconds`` have passed."""
    if job.status in ("done", "failed"):
        return job
    ctx = ctx.with_(via="import")
    run = _Run(session, ctx, source, job, storage, max_upload_bytes)
    job.status = "running"
    deadline = time.monotonic() + seconds
    first = True
    while run.queue and (first or time.monotonic() < deadline):  # always at least one item
        first = False
        it = run.queue.pop(0)
        await run.item(it)
        run.count("steps_done")
    run.save()
    await session.flush()
    return job


async def run_all(
    session: AsyncSession,
    ctx: Ctx,
    source: Source,
    job: ImportJob,
    *,
    storage: StorageBackend | None,
    max_upload_bytes: int,
) -> ImportJob:
    """Every step in one go (small imports, tests, and the CLI between progress lines)."""
    while job.status not in ("done", "failed"):
        await run_step(
            session,
            ctx,
            source,
            job,
            storage=storage,
            max_upload_bytes=max_upload_bytes,
            seconds=float("inf"),
        )
    return job
