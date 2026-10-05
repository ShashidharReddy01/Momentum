"""``momentum seed --scale``: the Phase 7 load-test workspace (synthetic only).

~150 people in 8 teams, 60 projects (a tenth of them private), ~50,000 tasks (with subtasks,
comments, dependencies, tags and followers) — the size Momentum is planned for. Rows are written
in batches straight to the tables, like ``seed --perf``: this is synthetic load data, not app
behaviour, and going through the services would take hours. Deterministic (fixed random seed) and
safe to re-run: it does nothing once the scale teams exist.

Every scale person signs in with dev login like the seeded ones (``scale-NNN@acme-demo.test``).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ids import new_id
from momentum.core.ordering import keys_between
from momentum.core.settings import Settings
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Follower, Task, TaskDependency, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace

PEOPLE = 150
TEAMS = ["Engineering", "Design", "Sales", "Support", "Finance", "People", "Ops", "Marketing NA"]
PROJECTS = 60
TASKS = 50_000  # top-level and subtasks together
SECTIONS = ["Backlog", "Up next", "In progress", "Review", "Done"]
FIRST = ["Alex", "Sam", "Jo", "Kai", "Noor", "Lee", "Ari", "Rae", "Max", "Ivy", "Ben", "Zoe"]
LAST = ["Park", "Ruiz", "Khan", "Novak", "Okafor", "Silva", "Ito", "Berg", "Rossi", "Haas"]
VERBS = ["Draft", "Review", "Ship", "Fix", "Plan", "Test", "Update", "Design", "Write", "Audit"]
THINGS = [
    "pricing page",
    "onboarding flow",
    "Q4 report",
    "API docs",
    "release notes",
    "budget",
    "hiring plan",
    "dashboard",
    "contract",
    "landing page",
    "survey",
    "roadmap",
]
TAGS = [
    "Urgent",
    "Customer",
    "Blocked",
    "Quick win",
    "Tech debt",
    "Legal",
    "Q4",
    "Bug",
    "Idea",
    "Research",
    "Design",
    "Data",
    "Security",
    "Docs",
    "Infra",
    "Mobile",
    "Web",
    "Ops",
    "HR",
    "Finance",
]
PALETTE = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899"]
BATCH = 2_000


def _doc(text: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def seed_scale(session: AsyncSession, settings: Settings) -> dict[str, int]:
    from momentum.seed import seed

    await seed(session, settings)
    ws = await ensure_default_workspace(session, settings)
    exists = await session.execute(
        select(Team.id).where(Team.workspace_id == ws.id, Team.name == TEAMS[0])
    )
    if exists.scalar_one_or_none() is not None:
        return {"scale_tasks": 0}
    rng = random.Random(150)  # noqa: S311 (synthetic data)
    now = datetime.now(UTC)
    today = now.date()

    people = [
        User(
            id=new_id(),
            workspace_id=ws.id,
            email=f"scale-{i:03d}@acme-demo.test",
            name=f"{rng.choice(FIRST)} {rng.choice(LAST)} {i:03d}",
            role="admin" if i < 3 else "member",
            status="active",
            timezone=rng.choice(["Europe/London", "America/New_York", "Asia/Kolkata", "UTC"]),
        )
        for i in range(PEOPLE)
    ]
    session.add_all(people)
    await session.flush()  # no ORM relationships: write people before rows that point at them
    teams = [
        Team(
            id=new_id(),
            workspace_id=ws.id,
            name=name,
            color=f"proj-{n % 12 + 1}",
            created_by=people[0].id,
        )
        for n, name in enumerate(TEAMS)
    ]
    session.add_all(teams)
    await session.flush()
    members: dict[object, list[User]] = {t.id: [] for t in teams}
    for i, person in enumerate(people):
        homes = {teams[i % len(teams)]} | ({rng.choice(teams)} if rng.random() < 0.3 else set())
        for t in homes:
            session.add(
                TeamMember(
                    team_id=t.id,
                    user_id=person.id,
                    role="lead" if len(members[t.id]) == 0 else "member",
                )
            )
            members[t.id].append(person)
    tags = [
        Tag(id=new_id(), workspace_id=ws.id, name=n, color=PALETTE[i % len(PALETTE)])
        for i, n in enumerate(TAGS)
    ]
    session.add_all(tags)
    await session.flush()

    per_project = TASKS // PROJECTS
    out = {
        "scale_people": PEOPLE,
        "scale_projects": PROJECTS,
        "scale_tasks": 0,
        "scale_comments": 0,
        "scale_dependencies": 0,
    }
    for p_index in range(PROJECTS):
        team = teams[p_index % len(teams)]
        crew = members[team.id]
        owner = crew[0]
        private = p_index % 10 == 9
        project = Project(
            id=new_id(),
            workspace_id=ws.id,
            team_id=team.id,
            name=f"{rng.choice(THINGS).capitalize()} {p_index + 1:02d}",
            color=f"proj-{p_index % 12 + 1}",
            privacy="private" if private else "team",
            owner_id=owner.id,
            created_by=owner.id,
            created_via="import",
            due_on=today + timedelta(days=rng.randint(20, 160)),
        )
        session.add(project)
        await session.flush()
        session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="admin"))
        if private:
            for person in rng.sample(crew, min(6, len(crew))):
                if person.id != owner.id:
                    session.add(
                        ProjectMember(project_id=project.id, user_id=person.id, role="editor")
                    )
        sections = [
            Section(id=new_id(), workspace_id=ws.id, project_id=project.id, name=n, position=pos)
            for n, pos in zip(SECTIONS, keys_between(None, None, len(SECTIONS)), strict=True)
        ]
        session.add_all(sections)
        await session.flush()

        made: list[Task] = []
        positions = iter(keys_between(None, None, per_project))  # real order keys, in order
        sub_keys = keys_between(None, None, 3)
        pending: list[object] = []  # rows that point at tasks
        new_tasks: list[Task] = []  # written first (no ORM relationships to order the flush)
        count = 0
        while count < per_project:
            ws.task_seq += 1
            section = rng.choice(sections)
            done = section.name == "Done" or rng.random() < 0.15
            assignee = rng.choice(crew) if rng.random() < 0.8 else None
            due = today + timedelta(days=rng.randint(-20, 90)) if rng.random() < 0.7 else None
            task = Task(
                id=new_id(),
                workspace_id=ws.id,
                number=ws.task_seq,
                title=f"{rng.choice(VERBS)} {rng.choice(THINGS)} #{ws.task_seq}",
                assignee_id=assignee.id if assignee else None,
                due_on=due,
                start_on=due - timedelta(days=rng.randint(1, 10))
                if due and rng.random() < 0.3
                else None,
                priority=rng.choice([None, None, "low", "medium", "high", "urgent"]),
                estimate_minutes=rng.choice([None, None, 60, 120, 240, 480]),
                completed_at=now - timedelta(days=rng.randint(0, 60)) if done else None,
                created_by=owner.id,
                created_via="import",
            )
            new_tasks.append(task)
            pending.append(
                TaskProject(
                    task_id=task.id,
                    project_id=project.id,
                    section_id=section.id,
                    position=next(positions),
                )
            )
            pending.append(Follower(task_id=task.id, user_id=owner.id))
            if assignee and assignee.id != owner.id:
                pending.append(Follower(task_id=task.id, user_id=assignee.id))
            if rng.random() < 0.3:
                pending.append(TaskTag(task_id=task.id, tag_id=rng.choice(tags).id))
            if rng.random() < 0.33:
                author = rng.choice(crew)
                state = rng.choice(["on track", "needs review", "blocked on legal", "done soon"])
                text = f"Update on {task.title}: {state}"
                pending.append(
                    Comment(
                        id=new_id(),
                        workspace_id=ws.id,
                        task_id=task.id,
                        author_id=author.id,
                        body=_doc(text),
                        body_text=text,
                        created_via="import",
                    )
                )
                out["scale_comments"] += 1
            if made and rng.random() < 0.2:
                pending.append(
                    TaskDependency(
                        task_id=task.id,
                        depends_on_id=rng.choice(made[-50:]).id,
                        created_by=owner.id,
                    )
                )
                out["scale_dependencies"] += 1
            made.append(task)
            count += 1
            if rng.random() < 0.1:  # a few subtasks
                for k in range(rng.randint(1, 3)):
                    ws.task_seq += 1
                    new_tasks.append(
                        Task(
                            id=new_id(),
                            workspace_id=ws.id,
                            number=ws.task_seq,
                            parent_id=task.id,
                            parent_position=sub_keys[k],
                            title=f"Step {k + 1} of {task.title}",
                            assignee_id=task.assignee_id,
                            created_by=owner.id,
                            created_via="import",
                        )
                    )
                    count += 1
            if len(pending) + len(new_tasks) >= BATCH:
                session.add_all(new_tasks)
                await session.flush()
                session.add_all(pending)
                await session.flush()
                pending, new_tasks = [], []
        session.add_all(new_tasks)
        await session.flush()
        session.add_all(pending)
        await session.flush()
        out["scale_tasks"] += count
    return out
