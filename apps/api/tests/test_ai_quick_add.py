"""S3.2.1 smart quick-add, the server half: the fast-alias extraction (mock fixtures), name
resolution against what the user can see, the structured-output repair retry, the task service's
new priority/recurrence fields, and the endpoint. The local parser is tested in the web app
(quickAddParse.test.ts); together they cover the AC's 30 fixture phrases."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from momentum.ai import prompts
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM, build_llm
from momentum.ai.mock import MockTransport
from momentum.ai.quick_add import Extraction, parse
from momentum.ai.structured import extract
from momentum.ai.types import ChatRequest, RawCompletion, ToolCall
from momentum.ai.usage import NullUsageLog
from momentum.core.db import UnitOfWork
from momentum.core.errors import ValidationFailed
from momentum.core.settings import Settings
from momentum.core.undo import undo
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import World, task_row, world
from tests.helpers import Clients

_ = world
NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)

# The 6 AI phrases of the AC's 30 (the other 24 are local-parser phrases in the web app).
AI_PHRASES: list[tuple[str, dict[str, Any]]] = [
    (
        "Ana needs to prepare the Q4 budget deck by end of next week",
        {
            "title": "Prepare the Q4 budget deck",
            "assignee": "Ana Souza",
            "due_on": date(2026, 10, 9),
        },
    ),
    (
        "remind me to renew the domain before it expires on the 3rd, it's urgent",
        {
            "title": "Renew the domain",
            "assignee": "Ravi Kumar",
            "due_on": date(2026, 10, 3),
            "priority": "urgent",
        },
    ),
    (
        "Priya should review the vendor contract in Vendor Onboarding asap",
        {
            "title": "Review the vendor contract",
            "assignee": "Priya Nair",
            "project": "Vendor Onboarding",
            "priority": "high",
        },
    ),
    (
        "water the office plants every monday and thursday",
        {
            "title": "Water the office plants",
            "recurrence": {
                "freq": "weekly",
                "interval": 1,
                "by_weekday": [0, 3],
                "workdays_only": False,
            },
        },
    ),
    (
        "ask Tom about the launch press list for the marketing campaign",
        {"title": "Ask Tom about the launch press list", "assignee": "Tom Becker", "unresolved": 1},
    ),
    (
        "someone from Product should look at the flaky login test next sprint",
        {"title": "Look at the flaky login test"},
    ),
]


@pytest.fixture
def llm(settings: Settings) -> LLM:
    return build_llm(settings)


@pytest.mark.parametrize(("text", "want"), AI_PHRASES)
async def test_ai_phrases(
    uow: UnitOfWork, world: World, llm: LLM, text: str, want: dict[str, Any]
) -> None:
    async with uow.transaction() as s:
        out = await parse(s, llm, world.ravi, text, now=NOW)
    assert out.title == want["title"]
    assert (out.assignee.name if out.assignee else None) == want.get("assignee")
    assert (out.project.name if out.project else None) == want.get("project")
    assert out.due_on == want.get("due_on")
    assert out.priority == want.get("priority")
    assert (out.recurrence.model_dump() if out.recurrence else None) == want.get("recurrence")
    assert len(out.unresolved) == want.get("unresolved", 0)


async def test_projects_resolve_only_where_the_user_can_add_tasks(
    uow: UnitOfWork, world: World, llm: LLM
) -> None:
    # tom isn't in Operations: "Vendor Onboarding" is invisible to him → unresolved, not leaked
    async with uow.transaction() as s:
        out = await parse(
            s,
            llm,
            world.tom,
            "Priya should review the vendor contract in Vendor Onboarding asap",
            now=NOW,
        )
    assert out.project is None and "Vendor Onboarding" in out.unresolved[0]


class Scripted(MockTransport):
    """Replies with the scripted tool arguments in order (to test the repair retry)."""

    def __init__(self, settings: Settings, replies: list[dict[str, Any]]) -> None:
        super().__init__(settings)
        self.replies = replies
        self.requests: list[ChatRequest] = []

    async def complete(self, req: ChatRequest) -> RawCompletion:
        self.requests.append(req)
        args = self.replies.pop(0)
        return RawCompletion(
            text="",
            tool_calls=[ToolCall("c1", "submit_result", json.dumps(args))],
            finish_reason="tool_calls",
            tokens_in=1,
            tokens_out=1,
            model="mock",
        )


async def test_structured_output_gets_one_repair_retry(settings: Settings, world: World) -> None:
    t = Scripted(
        settings, [{"title": "X", "priority": "critical"}, {"title": "X", "priority": "high"}]
    )
    llm = LLM(settings, t, NullUsageLog())
    out = await extract(
        llm, world.ravi, prompt=prompts.load("quick_add"), system="s", user="u", schema=Extraction
    )
    assert out.priority == "high"
    repair = t.requests[1].messages
    assert repair[-1]["role"] == "tool" and "Invalid result" in repair[-1]["content"]

    t2 = Scripted(settings, [{"title": "X", "priority": "critical"}] * 2)
    with pytest.raises(AIUnavailable) as e:
        await extract(
            LLM(settings, t2, NullUsageLog()),
            world.ravi,
            prompt=prompts.load("quick_add"),
            system="s",
            user="u",
            schema=Extraction,
        )
    assert e.value.reason == "bad_response" and len(t2.requests) == 2


def test_prompt_loader() -> None:
    p = prompts.load("quick_add")
    assert p.version == "quick_add/v1" and p.alias == "fast" and p.temperature == 0
    assert "{today}" in p.body and "submit_result" in p.body
    assert "2026-09-26" in p.render(today="2026-09-26", weekday="Saturday", tz="UTC")


async def test_task_service_priority_and_recurrence(uow: UnitOfWork, world: World) -> None:
    rule = {"freq": "weekly", "interval": 1, "by_weekday": [3, 0, 0], "text": "every mon & thu"}
    async with uow.transaction() as s:
        m = await tasks.create_task(
            s, world.ravi, world.project.id, "Water plants", priority="high", recurrence=rule
        )
    t = await task_row(uow, m.entity[0].id)
    tid = t.id
    assert t.priority == "high"
    assert t.recurrence == {
        "freq": "weekly",
        "interval": 1,
        "by_weekday": [0, 3],
        "text": "every mon & thu",
    }
    async with uow.transaction() as s:
        u = await tasks.update_task(s, world.ravi, t.id, {"priority": "low"})
    async with uow.transaction() as s:
        await undo(s, world.ravi, activity_id=u.activity_id)
    assert (await task_row(uow, t.id)).priority == "high"
    for bad in (
        {"priority": "critical"},
        {"recurrence": {"freq": "hourly"}},
        {"recurrence": {"freq": "weekly", "by_weekday": [9]}},
    ):
        with pytest.raises(ValidationFailed):
            async with uow.transaction() as s:
                await tasks.update_task(s, world.ravi, tid, bad)


async def test_quick_add_endpoint(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post(
        "/api/v1/ai/quick-add",
        json={"text": "Ana needs to prepare the Q4 budget deck by end of next week"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Prepare the Q4 budget deck" and body["assignee"]["name"] == "Ana Souza"
    r = await ravi.post("/api/v1/ai/quick-add", json={"text": "mo breaks this one"})
    assert r.status_code == 503 and r.json()["code"] == "ai_unavailable"
    assert r.json()["reason"] == "bad_response"
    assert (await ravi.post("/api/v1/ai/quick-add", json={"text": ""})).status_code == 422
    # the create endpoint takes the new fields
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    r = await ravi.post(
        f"/api/v1/projects/{pid}/tasks",
        json={
            "title": "Water plants",
            "priority": "low",
            "recurrence": {"freq": "weekly", "by_weekday": [0]},
        },
    )
    assert r.status_code == 201 and r.json()["data"]["priority"] == "low"
    detail = (await ravi.get(f"/api/v1/tasks/{r.json()['data']['id']}")).json()
    assert detail["recurrence"] == {"freq": "weekly", "interval": 1, "by_weekday": [0]}
