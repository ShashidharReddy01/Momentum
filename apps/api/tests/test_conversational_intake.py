"""S4.2.2 Conversational intake: a chat turn maps to the same task fields as a classic
submission, follows up on vague answers, and the transcript ends up as a comment on the created
task. Mock-mode fixtures: ``ai/evals/fixtures/mock_responses/conversational_intake.yaml``."""

from __future__ import annotations

import httpx
from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.domain.tasks.models import Task
from tests.helpers import Clients


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _form(c: httpx.AsyncClient, pid: str, **kwargs: object) -> dict[str, object]:
    questions = [
        {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"},
        {"id": "q_due", "label": "Due date", "required": False, "maps_to": "due_on"},
    ]
    r = await c.post(
        "/api/v1/forms",
        json={
            "project_id": pid,
            "name": "Intake",
            "questions": questions,
            "conversational": True,
            **kwargs,
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json()["data"])


def _public_client(as_user: Clients) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=as_user.app), base_url="http://testserver"
    )


async def test_converse_asks_then_follows_up_then_confirms(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid)
    fid = form["id"]

    first = await ravi.post(f"/api/v1/forms/{fid}/converse", json={"history": []})
    assert first.status_code == 200, first.text
    assert first.json()["done"] is False and "task" in first.json()["message"].lower()

    history = [
        {"role": "assistant", "text": first.json()["message"]},
        {"role": "user", "text": "fix the leaky faucet"},
    ]
    second = await ravi.post(f"/api/v1/forms/{fid}/converse", json={"history": history})
    assert second.status_code == 200, second.text
    assert second.json()["done"] is False
    assert second.json()["answers"]["q_title"] == "Fix the leaky faucet"

    history += [
        {"role": "assistant", "text": second.json()["message"]},
        {"role": "user", "text": "soon-ish"},
    ]
    vague = await ravi.post(f"/api/v1/forms/{fid}/converse", json={"history": history})
    assert vague.status_code == 200
    assert vague.json()["done"] is False  # a vague date doesn't count as an answer

    history += [
        {"role": "assistant", "text": vague.json()["message"]},
        {"role": "user", "text": "2026-10-03"},
    ]
    ready = await ravi.post(f"/api/v1/forms/{fid}/converse", json={"history": history})
    assert ready.status_code == 200
    assert ready.json()["done"] is True
    assert ready.json()["answers"] == {
        "q_title": "Fix the leaky faucet",
        "q_due": "2026-10-03",
    }


async def test_converse_submit_creates_the_task_and_attaches_the_transcript(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid)
    fid = form["id"]
    history = [
        {"role": "assistant", "text": "What's the task called?"},
        {"role": "user", "text": "report a bug"},
    ]
    submitted = await ravi.post(
        f"/api/v1/forms/{fid}/converse/submit",
        json={"history": history, "answers": {"q_title": "Report a bug"}},
    )
    assert submitted.status_code == 200, submitted.text
    async with uow.transaction() as s:
        task = (await s.execute(select(Task).where(Task.title == "Report a bug"))).scalar_one()
        assert task.created_via == "form"
    feed = await ravi.get(f"/api/v1/tasks/{task.id}/feed")
    comments = [i["comment"] for i in feed.json()["data"] if i.get("kind") == "comment"]
    texts = [
        span["text"]
        for c in comments
        for para in c["body"]["content"]
        for span in para.get("content", [])
    ]
    assert any("report a bug" in t.lower() for t in texts)


async def test_a_viewer_can_submit_the_internal_link(as_user: Clients) -> None:
    """The internal link needs only visibility (S4.2.2 also fixed the pre-existing gap where
    ``get_form`` — editor-gated — was used for submission too)."""
    ravi, mei = await as_user("ravi"), await as_user("mei")
    pid = await _project(ravi)
    form = await _form(ravi, pid)
    r = await mei.post(f"/api/v1/forms/{form['id']}/converse", json={"history": []})
    assert r.status_code == 200, r.text


async def test_conversational_endpoints_404_when_the_form_isnt_conversational(
    as_user: Clients,
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, conversational=False)
    r = await ravi.post(f"/api/v1/forms/{form['id']}/converse", json={"history": []})
    assert r.status_code == 404


async def test_public_conversational_link_works_without_login(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, public_enabled=True)
    async with _public_client(as_user) as pub:
        turn = await pub.post(
            f"/api/v1/public/forms/{form['public_token']}/converse", json={"history": []}
        )
        assert turn.status_code == 200, turn.text
        submitted = await pub.post(
            f"/api/v1/public/forms/{form['public_token']}/converse/submit",
            json={
                "history": [{"role": "user", "text": "report a bug"}],
                "answers": {"q_title": "Report a bug"},
            },
        )
        assert submitted.status_code == 200, submitted.text
    async with uow.transaction() as s:
        task = (await s.execute(select(Task).where(Task.title == "Report a bug"))).scalar_one()
        assert task.created_via == "form"


async def test_public_conversational_link_needs_the_form_to_be_public(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, public_enabled=False)
    async with _public_client(as_user) as pub:
        r = await pub.post(
            f"/api/v1/public/forms/{form['public_token']}/converse", json={"history": []}
        )
        assert r.status_code == 404
