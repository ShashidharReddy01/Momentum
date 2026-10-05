"""A synthetic Asana workspace (S7.4.2), the test oracle for the importer: the backend tests drive
the engine with ``FakeAsana`` and the browser journey (J6) serves the same data over HTTP
(``tools/e2e/asana_fixture_server.py``). Synthetic only: no real people, companies or data.

What it holds, and what a full import of team ``team1`` must produce:

- people: Ravi (``ravi@acme-demo.test``, matches the seed), a newcomer (invited), and someone
  whose email the token can't see (not matched: their comment keeps their name in its text);
- tag "Urgent"; custom fields of every kind (single- and multi-select, number, date, people,
  text, and a formula imported as a text snapshot);
- 3 projects (one archived) with 4 sections; 6 tasks (a milestone, an approval, one task in two
  projects), a legacy "section" row that is skipped, and 2 levels of subtasks;
- 3 stories on the release task (2 comments, one from the unmatched person, and a system story
  that isn't imported), likes, an Asana-hosted file and a Google Drive link, 2 dependencies (one
  on a task outside the import, skipped), and 2 status updates (the newer one sets the status).
"""

from __future__ import annotations

from typing import Any

RAVI: dict[str, Any] = {"gid": "u1", "name": "Ravi Kumar", "email": "ravi@acme-demo.test"}
NEWCOMER: dict[str, Any] = {
    "gid": "u2",
    "name": "Nia Newcomer",
    "email": "nia.newcomer@example.com",
}
HIDDEN: dict[str, Any] = {"gid": "u3", "name": "Ex Colleague", "email": None}

STAGE: dict[str, Any] = {
    "gid": "cf-stage",
    "name": "Stage",
    "resource_subtype": "enum",
    "enum_options": [
        {"gid": "opt-plan", "name": "Plan", "color": "blue", "enabled": True},
        {"gid": "opt-ship", "name": "Ship", "color": "green", "enabled": True},
        {"gid": "opt-old", "name": "Retired", "color": "cool-gray", "enabled": False},
    ],
}
AREAS: dict[str, Any] = {
    "gid": "cf-areas",
    "name": "Areas",
    "resource_subtype": "multi_enum",
    "enum_options": [
        {"gid": "opt-ui", "name": "UI", "color": "purple", "enabled": True},
        {"gid": "opt-api", "name": "API", "color": "aqua", "enabled": True},
    ],
}
POINTS: dict[str, Any] = {
    "gid": "cf-points",
    "name": "Points",
    "resource_subtype": "number",
    "precision": 0,
}
BUDGET: dict[str, Any] = {
    "gid": "cf-budget",
    "name": "Budget",
    "resource_subtype": "number",
    "format": "currency",
    "currency_code": "EUR",
    "precision": 2,
}
LAUNCH: dict[str, Any] = {"gid": "cf-launch", "name": "Launch", "resource_subtype": "date"}
OWNERS: dict[str, Any] = {"gid": "cf-owners", "name": "Owners", "resource_subtype": "people"}
NOTES: dict[str, Any] = {"gid": "cf-notes", "name": "Notes", "resource_subtype": "text"}
PROGRESS: dict[str, Any] = {"gid": "cf-progress", "name": "Progress", "resource_subtype": "formula"}
FIELDS: list[dict[str, Any]] = [STAGE, AREAS, POINTS, BUDGET, LAUNCH, OWNERS, NOTES, PROGRESS]

RELEASE: dict[str, Any] = {
    "gid": "t1",
    "name": "Ship the release",
    "html_notes": "<body>Careful with <strong>prod</strong>.\n"
    "<ul><li>Backup first</li></ul></body>",
    "resource_subtype": "default_task",
    "assignee": {"email": RAVI["email"]},
    "created_by": {"email": RAVI["email"]},
    "created_at": "2025-11-02T09:00:00.000Z",
    "due_on": "2026-02-01",
    "completed": False,
    "tags": [{"gid": "tag1"}],
    "num_subtasks": 1,
    "followers": [{"email": RAVI["email"]}, {"email": NEWCOMER["email"]}],
    "likes": [{"user": {"email": NEWCOMER["email"]}}],
    "dependencies": [{"gid": "t2"}],
    "permalink_url": "https://app.asana.com/0/p1/t1",
    "custom_fields": [
        {"gid": "cf-stage", "resource_subtype": "enum", "enum_value": {"gid": "opt-ship"}},
        {
            "gid": "cf-areas",
            "resource_subtype": "multi_enum",
            "multi_enum_values": [{"gid": "opt-ui"}, {"gid": "opt-api"}],
        },
        {"gid": "cf-points", "resource_subtype": "number", "number_value": 5},
        {"gid": "cf-budget", "resource_subtype": "number", "number_value": 1200.5},
        {"gid": "cf-launch", "resource_subtype": "date", "date_value": {"date": "2026-03-01"}},
        {
            "gid": "cf-owners",
            "resource_subtype": "people",
            "people_value": [{"email": RAVI["email"]}],
        },
        {"gid": "cf-notes", "resource_subtype": "text", "text_value": "Go/no-go on Monday"},
        {"gid": "cf-progress", "resource_subtype": "formula", "display_value": "42%"},
    ],
}

PROJECTS: list[dict[str, Any]] = [
    {
        "gid": "p1",
        "name": "Imported Project",
        "archived": False,
        "color": "dark-green",
        "privacy_setting": "private_to_team",
        "html_notes": "<body>The <em>launch</em> plan.</body>",
        "owner": {"email": RAVI["email"]},
        "start_on": "2026-01-01",
        "due_on": None,
        "default_view": "board",
    },
    {
        "gid": "p2",
        "name": "Second Project",
        "archived": False,
        "privacy_setting": "public_to_workspace",
    },
    {"gid": "p3", "name": "Old Project", "archived": True, "privacy_setting": "private"},
]
SECTIONS: dict[str, list[dict[str, Any]]] = {
    "p1": [{"gid": "s1", "name": "To do"}, {"gid": "s2", "name": "Done"}],
    "p2": [{"gid": "s3", "name": "Backlog"}],
    "p3": [{"gid": "s4", "name": "Only section"}],
}
FIELD_SETTINGS: dict[str, list[dict[str, Any]]] = {"p1": FIELDS, "p2": [STAGE], "p3": []}
TASKS: dict[str, list[dict[str, Any]]] = {
    "s1": [
        RELEASE,
        {
            "gid": "t2",
            "name": "Kickoff milestone",
            "resource_subtype": "milestone",
            "completed": True,
            "completed_at": "2026-01-05T10:00:00.000Z",
        },
        {
            "gid": "t5",
            "name": "Approve the budget",
            "resource_subtype": "approval",
            "approval_status": "approved",
            "assignee": {"email": NEWCOMER["email"]},
        },
    ],
    "s2": [{"gid": "t3", "name": "Legacy separator row", "resource_subtype": "section"}],
    "s3": [
        RELEASE,  # the same task in a second project: one task, two placements
        {
            "gid": "t4",
            "name": "Second project task",
            "resource_subtype": "default_task",
            "dependencies": [{"gid": "t-elsewhere"}],  # not part of this import
            "custom_fields": [
                {"gid": "cf-stage", "resource_subtype": "enum", "enum_value": {"gid": "opt-plan"}}
            ],
        },
    ],
    "s4": [
        {"gid": "t6", "name": "Old task", "resource_subtype": "default_task", "completed": True}
    ],
}
SUBTASKS: dict[str, list[dict[str, Any]]] = {
    "t1": [
        {
            "gid": "t1-sub1",
            "name": "Notify support",
            "resource_subtype": "default_task",
            "num_subtasks": 1,
            "dependencies": [{"gid": "t1"}],
        }
    ],
    "t1-sub1": [
        {"gid": "t1-sub1-sub", "name": "Draft the note", "resource_subtype": "default_task"}
    ],
}
STORIES: dict[str, list[dict[str, Any]]] = {
    "t1": [
        {
            "gid": "st1",
            "resource_subtype": "comment_added",
            "html_text": "<body>Looks <strong>good</strong> to me</body>",
            "created_at": "2025-11-03T10:00:00.000Z",
            "created_by": {"email": RAVI["email"], "name": RAVI["name"]},
            "likes": [{"user": {"email": NEWCOMER["email"]}}],
        },
        {
            "gid": "st2",
            "resource_subtype": "comment_added",
            "text": "Ping me before the deploy",
            "created_at": "2025-11-04T10:00:00.000Z",
            "created_by": {"email": None, "name": HIDDEN["name"]},
        },
        {
            "gid": "st3",
            "resource_subtype": "assigned",
            "text": "Ravi assigned to you",
            "created_at": "2025-11-02T09:01:00.000Z",
        },
    ]
}
ATTACHMENTS: dict[str, list[dict[str, Any]]] = {
    "t1": [
        {
            "gid": "a1",
            "name": "spec.txt",
            "host": "asana",
            "download_url": "https://files.example.test/spec.txt",
            "size": 18,
            "created_at": "2025-11-02T09:05:00.000Z",
        },
        {
            "gid": "a2",
            "name": "Design doc",
            "host": "gdrive",
            "view_url": "https://docs.example.test/design",
        },
    ]
}
FILE_BYTES = b"release checklist\n"
STATUS_UPDATES: dict[str, list[dict[str, Any]]] = {
    "p1": [
        {
            "gid": "su1",
            "status_type": "on_track",
            "title": "Week 1",
            "text": "All good",
            "created_at": "2026-01-02T09:00:00.000Z",
        },
        {
            "gid": "su2",
            "status_type": "at_risk",
            "title": "Week 2",
            "html_text": "<body>Vendor <em>late</em></body>",
            "created_at": "2026-01-09T09:00:00.000Z",
            "created_by": {"email": RAVI["email"]},
        },
    ]
}


class FakeAsana:
    """The workspace above behind the importer's ``Source`` interface (records every call)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def workspaces(self) -> list[dict[str, Any]]:
        return [{"gid": "ws1", "name": "Acme (synthetic)"}]

    async def teams(self, workspace_gid: str) -> list[dict[str, Any]]:
        return [{"gid": "team1", "name": "Product"}]

    async def workspace_users(self, workspace_gid: str) -> list[dict[str, Any]]:
        self.calls.append("workspace_users")
        return [RAVI, NEWCOMER, HIDDEN]

    async def team_users(self, team_gid: str) -> list[dict[str, Any]]:
        self.calls.append("team_users")
        return [RAVI, NEWCOMER]

    async def projects(self, team_gid: str, include_archived: bool = True) -> list[dict[str, Any]]:
        self.calls.append("projects")
        return [p for p in PROJECTS if include_archived or not p["archived"]]

    async def custom_field_settings(self, project_gid: str) -> list[dict[str, Any]]:
        self.calls.append("custom_field_settings")
        return [{"custom_field": cf} for cf in FIELD_SETTINGS.get(project_gid, [])]

    async def sections(self, project_gid: str) -> list[dict[str, Any]]:
        self.calls.append("sections")
        return SECTIONS.get(project_gid, [])

    async def tasks(self, section_gid: str) -> list[dict[str, Any]]:
        self.calls.append("tasks")
        return TASKS.get(section_gid, [])

    async def subtasks(self, task_gid: str) -> list[dict[str, Any]]:
        self.calls.append("subtasks")
        return SUBTASKS.get(task_gid, [])

    async def tags(self, workspace_gid: str) -> list[dict[str, Any]]:
        self.calls.append("tags")
        return [{"gid": "tag1", "name": "Urgent", "color": "dark-red"}]

    async def stories(self, task_gid: str) -> list[dict[str, Any]]:
        self.calls.append("stories")
        return STORIES.get(task_gid, [])

    async def attachments(self, task_gid: str) -> list[dict[str, Any]]:
        self.calls.append("attachments")
        return ATTACHMENTS.get(task_gid, [])

    async def status_updates(self, project_gid: str) -> list[dict[str, Any]]:
        self.calls.append("status_updates")
        return STATUS_UPDATES.get(project_gid, [])

    async def download(self, url: str, max_bytes: int) -> bytes | None:
        self.calls.append("download")
        return FILE_BYTES if len(FILE_BYTES) <= max_bytes else None
