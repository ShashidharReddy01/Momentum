"""Phase 7.6 S76-07 (spec §12.1-12.3): the agents directory (search by what agents can do,
filters, health summary), an agent's profile (effects in plain English, triggers, how to hand it
work) and the job card's "jobs on this task" view."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents import directory
from momentum.app import create_app
from momentum.core.db import UnitOfWork
from tests.ai_fixtures import World, world
from tests.helpers import Clients
from tests.jobs_env import JobsEnv

_ = world
B = "/api/v1"


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


def test_effects_read_as_plain_english(make_env: Callable[..., JobsEnv]) -> None:
    env = make_env()
    manifest = env.packs.packs["echo"].manifest
    said = directory.effect_sentences(manifest, env.packs)
    assert "comment on the task" in said
    assert "create echo bill records" in said
    assert "add new echo vendor entries" in said
    assert "propose new skills (hint, rule) for a steward to review" in said


def test_question_search_drops_the_filler() -> None:
    card = directory.DirectoryCardOut.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "user_id": "00000000-0000-0000-0000-000000000002",
            "key": "bernie",
            "name": "Bernie",
            "avatar": "teammate",
            "description": "",
            "enabled": True,
            "source": "pack",
            "title": "Accounts payable clerk",
            "capabilities": [
                {
                    "key": "process_invoices",
                    "title": "Process invoices",
                    "description": "Reads supplier invoices",
                    "examples": [],
                    "files": ["pdf"],
                    "typical_duration_s": None,
                }
            ],
            "data_class": "financial",
            "health": None,
        }
    )
    assert directory.matches("who can read invoices?", card)
    assert directory.matches("Accounts payable", card)
    assert not directory.matches("who can draw diagrams?", card)
    assert directory.matches("   ", card)


async def test_directory_profile_and_task_jobs(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    asker = make_env()
    await asker.install("asker")
    run_id = await asker.start(task=world.copy, text="choice")
    assert await asker.drain() == ["waiting"]
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        app.state.momentum.packs = env.packs
        clients = Clients(app)
        ana = await clients("ana")

        r = (await ana.get(f"{B}/agents/directory", params={"q": "who can echo the input?"})).json()
        [card] = r["data"]
        assert card["key"] == env.agent.key and card["title"] == "Test pack"
        assert card["data_class"] == "internal"
        assert [c["key"] for c in card["capabilities"]] == ["echo", "tryout"]
        assert card["health"] == {"jobs": 0, "items": 0, "success_rate": None}
        assert not (await ana.get(f"{B}/agents/directory", params={"q": "invoices"})).json()["data"]
        by_cap = await ana.get(f"{B}/agents/directory", params={"capability": "echo"})
        assert [c["key"] for c in by_cap.json()["data"]] == [env.agent.key]
        financial = await ana.get(f"{B}/agents/directory", params={"data_class": "financial"})
        assert financial.json()["data"] == []
        everyone = (await ana.get(f"{B}/agents/directory")).json()["data"]
        assert {c["key"] for c in everyone} >= {env.agent.key, asker.agent.key}

        p = (await ana.get(f"{B}/agents/{env.agent.id}/profile")).json()
        assert p["is_pack"] is True and p["has_settings"] is True
        assert p["charter"].startswith("I repeat what I'm given.")
        assert p["capabilities"][0]["examples"] == ["Echo hello"]
        assert "create echo bill records" in p["effects"]
        assert p["triggers"] == ["When a task is assigned to it", "When someone runs it by hand"]
        assert (p["can_assign"], p["can_mention"], p["can_run"]) == (True, False, True)

        ravi = await clients("ravi")
        [job] = (await ravi.get(f"{B}/tasks/{world.copy.id}/jobs")).json()["data"]
        assert job["id"] == str(run_id) and job["status"] == "waiting"
        assert job["waiting_on"] == "ask" and job["asks_for_me"] == 1
        assert job["current_step"] and job["waiting_reason"].startswith("Waiting for an answer: “")
        [mine] = (await ana.get(f"{B}/tasks/{world.copy.id}/jobs")).json()["data"]
        assert mine["asks_for_me"] == 0  # the question is Ravi's

        # "Change": the person who answered can take it back until the agent uses it
        [ask] = (await ravi.get(f"{B}/asks")).json()["data"]
        assert ask["change_activity_id"] is None
        answered = await ravi.post(f"{B}/asks/{ask['id']}/answer", json={"value": "Globex"})
        assert answered.status_code == 200, answered.text
        change = answered.json()["change_activity_id"]
        assert change is not None
        theirs = (await ana.get(f"{B}/asks/{ask['id']}")).json()
        assert theirs["change_activity_id"] is None  # only for the person who answered
        assert (await ravi.post(f"{B}/undo", json={"activity_id": change})).status_code == 200
        assert (await ravi.get(f"{B}/asks/{ask['id']}")).json()["status"] == "open"

        runs = await ravi.get(
            f"{B}/agents/{asker.agent.id}/runs", params={"project_id": str(world.project.id)}
        )
        assert runs.status_code == 200
        await clients.close()
