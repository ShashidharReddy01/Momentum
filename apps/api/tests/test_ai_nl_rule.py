"""S4.1.4 NL → rule: the compiler resolves names to ids inside the rule's own project, asks
back instead of guessing, refuses actions the engine can't run yet, and produces a draft that
``POST /rules`` accepts unchanged (with ``created_from_prompt``). The AC's 20 fixture phrases
live in ``momentum/ai/evals/cases/nl_rule.yaml``; these are the resolution and refusal branches
and the endpoint's permissions."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from momentum.ai import nl_rule, prompts
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM, build_llm
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, ValidationFailed
from momentum.core.settings import Settings
from momentum.domain.projects.models import Project
from momentum.domain.rules.schemas import (
    ACTION_PARAMS,
    NOT_YET_ACTIONS,
    NOT_YET_TRIGGERS,
    OPS,
    TRIGGER_PARAMS,
)
from momentum.domain.sections.models import Section
from momentum.domain.tags.schemas import TagCreateIn
from momentum.domain.tags.service import create_tag
from tests.ai_fixtures import World, world
from tests.helpers import Clients

_ = world


@pytest.fixture
def llm(settings: Settings) -> LLM:
    return build_llm(settings)


async def ids(uow: UnitOfWork) -> dict[str, uuid.UUID]:
    """The world's ids, read in their own transaction (its ORM objects expire between tests'
    transactions, so ids are looked up rather than read off them)."""
    async with uow.transaction() as s:
        projects = (await s.execute(select(Project.id, Project.name))).tuples()
        sections = (await s.execute(select(Section.id, Section.name))).tuples()
        return {n: i for i, n in [*projects, *sections]}


async def compile_as(
    uow: UnitOfWork, llm: LLM, world: World, text: str, who: str = "ravi"
) -> nl_rule.CompiledRule:
    ctx = {"ravi": world.ravi, "ana": world.ana, "lena": world.lena}[who]
    project_id = (await ids(uow))["AI Tools Lab"]
    async with uow.transaction() as s:
        return await nl_rule.compile_rule(s, llm, ctx, project_id, text)


async def test_the_model_vocabulary_matches_the_rule_schemas_and_the_prompt() -> None:
    """The draft literals and the prompt are a second and third copy of the rule vocabulary:
    this test is what keeps them honest (S4.1.2 changed the action list once already)."""
    triggers = set(nl_rule.TriggerType.__args__)  # type: ignore[attr-defined]
    actions = set(nl_rule.ActionType.__args__)  # type: ignore[attr-defined]
    assert triggers == set(TRIGGER_PARAMS) and not triggers & NOT_YET_TRIGGERS
    assert actions == set(ACTION_PARAMS) and not actions & NOT_YET_ACTIONS
    assert set(nl_rule.Op.__args__) == set(OPS)  # type: ignore[attr-defined]
    body = prompts.load("nl_rule").body
    for name in triggers | actions:
        assert name in body, f"{name} is missing from the nl_rule prompt"
    for name in NOT_YET_ACTIONS | NOT_YET_TRIGGERS:
        assert name not in body, f"{name} must not be offered by the nl_rule prompt"


async def test_names_resolve_to_ids_in_this_project(
    uow: UnitOfWork, llm: LLM, world: World
) -> None:
    async with uow.transaction() as s:
        tag = (await create_tag(s, world.ravi, TagCreateIn(name="Beta"))).entity
        tag_id = tag.id
    r = await compile_as(
        uow, llm, world, "When it moves to Doing, assign it to Ana and add the Beta tag, please"
    )
    doing_id = (await ids(uow))["Doing"]
    assert r.question is None and r.rule is not None
    assert r.rule.trigger.model_dump(exclude_unset=True) == {
        "type": "task.moved",
        "to_section": doing_id,
    }
    # "High" arrives capitalized from the model; priority values are stored lowercase
    assert [c.model_dump(exclude_unset=True) for c in r.rule.conditions] == [
        {"field": "priority", "op": "eq", "value": "high"}
    ]
    assert [a.model_dump(exclude_unset=True) for a in r.rule.actions] == [
        {"type": "assign", "user_id": world.ana.actor.id},
        {"type": "add_tag", "tag_id": tag_id},
    ]
    assert r.rule.created_from_prompt is not None and "Beta tag" in r.rule.created_from_prompt
    assert r.sentence == (
        "When a task moves to Doing, if priority is high, "
        "then assign to Ana Souza and add tag Beta."
    )
    assert r.named == {
        "trigger": {"type": "task.moved", "to_section": "Doing"},
        "conditions": [{"field": "priority", "op": "eq", "value": "high"}],
        "actions": [
            {"type": "assign", "user_id": "Ana Souza"},
            {"type": "add_tag", "tag_id": "Beta"},
        ],
    }


@pytest.mark.parametrize(
    ("text", "in_question"),
    [
        ("post a message in our Slack channel when done", "Slack"),
        ("move it to Review, unknown section please", "no section called “Review”"),
        ("assign it to the right person, ambiguous person please", "more than one person"),
        ("only when priority is over high, invalid comparison please", "valid rule"),
        ("tidy up the board, nothing but a question", "?"),
        ("do the thing, empty draft please", "when"),
        ("add it to this project, into this very project", "this project"),
    ],
)
async def test_asks_back_instead_of_guessing(
    uow: UnitOfWork, llm: LLM, world: World, text: str, in_question: str
) -> None:
    r = await compile_as(uow, llm, world, text)
    assert r.rule is None and r.question is not None, r
    assert in_question.lower() in r.question.lower()


async def test_a_complete_rule_wins_over_a_stray_question(
    uow: UnitOfWork, llm: LLM, world: World
) -> None:
    r = await compile_as(uow, llm, world, "complete new tasks, both a rule and a question")
    assert r.question is None and r.rule is not None
    assert [a.type for a in r.rule.actions] == ["mark_complete"]


async def test_unassign_and_me_resolve(uow: UnitOfWork, llm: LLM, world: World) -> None:
    r = await compile_as(uow, llm, world, "back to To do: unassign whoever has it")
    assert r.rule is not None
    assert r.rule.actions[0].model_dump(exclude_unset=True) == {"type": "assign", "user_id": None}
    assert r.sentence is not None and "unassign it" in r.sentence

    mine = await compile_as(uow, llm, world, "when a task is completed, assign it to me")
    assert mine.rule is not None
    assert mine.rule.actions[0].user_id == world.ravi.actor.id


async def test_other_projects_resolve_only_where_visible(
    uow: UnitOfWork, llm: LLM, world: World
) -> None:
    ok = await compile_as(uow, llm, world, "on completion, cross-project move it")
    assert ok.rule is not None
    assert ok.rule.actions[0].project_id == world.other.id
    # ana is an editor on the project, not an admin: she can't compile rules for it at all
    with pytest.raises(Forbidden):
        await compile_as(uow, llm, world, "on completion, cross-project move it", who="ana")


async def test_a_reply_the_schema_refuses_degrades_gracefully(
    uow: UnitOfWork, llm: LLM, world: World
) -> None:
    with pytest.raises(AIUnavailable) as e:
        await compile_as(uow, llm, world, "when completed, bad action type")
    assert e.value.reason == "bad_response"


async def test_empty_and_overlong_text_are_refused(uow: UnitOfWork, llm: LLM, world: World) -> None:
    for text in ("   ", "x" * (nl_rule.MAX_TEXT + 1)):
        with pytest.raises(ValidationFailed):
            await compile_as(uow, llm, world, text)


async def test_the_reference_block_never_carries_instructions(
    uow: UnitOfWork, llm: LLM, world: World
) -> None:
    project_id = (await ids(uow))["AI Tools Lab"]
    async with uow.transaction() as s:
        project = await s.get(Project, project_id)
        assert project is not None
        refs = await nl_rule.load_refs(s, world.ravi, project)
    block = nl_rule.reference_block(refs)
    assert block.startswith('<data source="project">') and "Sections: To do, Doing" in block
    assert "Ana Souza" in block and "Draft pricing secret" not in block
    # other projects are listed by name for add_to_project — never ones ravi can't see
    assert "Other projects: " in block and "Side Quest" in block
    assert "Secret Plans" not in block


async def test_endpoint_compiles_and_the_draft_saves_unchanged(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    text = "When a task moves to Review and assign Mei, please."  # matches a mock fixture
    r = await ravi.post("/api/v1/ai/rules/compile", json={"project_id": pid, "text": text})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["question"] is None and body["sentence"].startswith("When a task moves to")
    draft = body["rule"]
    assert draft["created_from_prompt"] == text and draft["enabled"] is True
    assert draft["trigger"]["type"] == "task.moved"

    created = await ravi.post("/api/v1/rules", json={**draft, "project_id": pid})
    assert created.status_code == 201, created.text
    saved = created.json()["data"]
    assert saved["created_from_prompt"] == text and saved["trigger"] == draft["trigger"]

    # a question comes back as a question, not an error
    slack = await ravi.post(
        "/api/v1/ai/rules/compile",
        json={"project_id": pid, "text": "post a message in our Slack channel when done"},
    )
    assert slack.status_code == 200 and slack.json()["rule"] is None
    assert "Slack" in slack.json()["question"]


async def test_endpoint_permissions(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    tom = await as_user("tom")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    text = "When a task moves to Review and assign Mei, please."
    # ana (team editor) may not manage rules; tom can't see the project at all
    assert (
        await ana.post("/api/v1/ai/rules/compile", json={"project_id": pid, "text": text})
    ).status_code == 403
    assert (
        await tom.post("/api/v1/ai/rules/compile", json={"project_id": pid, "text": text})
    ).status_code == 404
    missing = await ravi.post(
        "/api/v1/ai/rules/compile", json={"project_id": str(uuid.uuid4()), "text": text}
    )
    assert missing.status_code == 404
    assert (
        await ravi.post("/api/v1/ai/rules/compile", json={"project_id": pid, "text": ""})
    ).status_code == 422
