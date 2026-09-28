"""S4.2.1 Form builder + public forms: validation, permissions, submission (internal and
public), spam limits, the honeypot, and the ``form.submitted`` rule trigger."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.forms.models import FormSubmission
from momentum.domain.rules.engine import run_rules
from momentum.domain.tasks.models import Task
from tests.helpers import Clients


async def _project(c: httpx.AsyncClient, name: str = "Website Revamp") -> str:
    return next(
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _sections(c: httpx.AsyncClient, pid: str) -> dict[str, str]:
    rows = (await c.get(f"/api/v1/projects/{pid}/sections")).json()["data"]
    return {s["name"]: s["id"] for s in rows}


async def _member(c: httpx.AsyncClient, pid: str) -> str:
    detail = (await c.get(f"/api/v1/projects/{pid}")).json()
    return str(detail["members"][0]["user"]["id"])


async def _field(c: httpx.AsyncClient, pid: str, **kwargs: Any) -> str:
    r = await c.post(f"/api/v1/projects/{pid}/fields", json={"name": "Notes", **kwargs})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


def _questions(title_id: str = "q_title", **extra: dict[str, Any]) -> list[dict[str, Any]]:
    base = [{"id": title_id, "label": "Title", "required": True, "maps_to": "title"}]
    base.extend(extra.values())
    return base


async def _form(
    c: httpx.AsyncClient, pid: str, questions: list[dict[str, Any]], **kwargs: Any
) -> dict[str, Any]:
    r = await c.post(
        "/api/v1/forms",
        json={"project_id": pid, "name": "Intake", "questions": questions, **kwargs},
    )
    assert r.status_code == 201, r.text
    return dict(r.json()["data"])


def _public_client(as_user: Clients) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=as_user.app), base_url="http://testserver"
    )


# ---------------- validation ----------------


async def test_form_validation(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    people_field = await _field(ravi, pid, type="people")
    bad = [
        [],  # empty
        [{"id": "q1", "label": "X", "required": False, "maps_to": "title"}],  # title not required
        [{"id": "q1", "label": "X", "required": True, "maps_to": "nope"}],  # bad target
        [  # two title questions
            {"id": "q1", "label": "A", "required": True, "maps_to": "title"},
            {"id": "q2", "label": "B", "required": True, "maps_to": "title"},
        ],
        [  # same target twice
            {"id": "q1", "label": "A", "required": True, "maps_to": "title"},
            {"id": "q2", "label": "B", "required": False, "maps_to": "description"},
            {"id": "q3", "label": "C", "required": False, "maps_to": "description"},
        ],
        [  # show_if references an unknown question
            {"id": "q1", "label": "A", "required": True, "maps_to": "title"},
            {
                "id": "q2",
                "label": "B",
                "required": False,
                "maps_to": "description",
                "show_if": {"question_id": "nope", "equals": "x"},
            },
        ],
        [  # show_if depends on a later question
            {
                "id": "q1",
                "label": "A",
                "required": True,
                "maps_to": "title",
            },
            {
                "id": "q2",
                "label": "B",
                "required": False,
                "maps_to": "description",
                "show_if": {"question_id": "q3", "equals": "x"},
            },
            {"id": "q3", "label": "C", "required": False, "maps_to": "due_on"},
        ],
        [  # a people-type field can't be asked directly
            {"id": "q1", "label": "A", "required": True, "maps_to": "title"},
            {"id": "q2", "label": "B", "required": False, "maps_to": people_field},
        ],
    ]
    for questions in bad:
        r = await ravi.post(
            "/api/v1/forms", json={"project_id": pid, "name": "Intake", "questions": questions}
        )
        assert r.status_code == 422, (questions, r.text)


async def test_managing_forms_needs_project_admin(as_user: Clients) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    pid = await _project(ravi)
    form = await _form(ravi, pid, _questions())
    assert (await mei.get(f"/api/v1/forms/{form['id']}")).status_code == 200
    patch = await mei.patch(f"/api/v1/forms/{form['id']}", json={"enabled": False})
    assert patch.status_code == 403
    assert (await mei.delete(f"/api/v1/forms/{form['id']}")).status_code == 403
    body = {"project_id": pid, "name": "X", "questions": _questions()}
    assert (await mei.post("/api/v1/forms", json=body)).status_code == 403
    ana = await as_user("ana")
    theirs = await _project(ana, "Q4 Launch Campaign")
    hidden = await _form(ana, theirs, _questions())
    assert (await ravi.get(f"/api/v1/forms/{hidden['id']}")).status_code == 404
    assert (await ravi.get(f"/api/v1/forms?project_id={theirs}")).status_code == 404


async def test_crud_and_optimistic_concurrency(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, _questions())
    assert form["version"] == 1
    patched = await ravi.patch(f"/api/v1/forms/{form['id']}", json={"name": "Renamed"})
    assert patched.status_code == 200 and patched.json()["data"]["version"] == 2
    stale = await ravi.patch(
        f"/api/v1/forms/{form['id']}", json={"name": "X", "expected_version": 1}
    )
    assert stale.status_code == 409
    assert (await ravi.delete(f"/api/v1/forms/{form['id']}")).status_code == 200
    assert (await ravi.get(f"/api/v1/forms/{form['id']}")).status_code == 404


# ---------------- submission ----------------


async def test_internal_submission_maps_every_target(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    sections = await _sections(ravi, pid)
    member = await _member(ravi, pid)
    field_id = await _field(ravi, pid, type="text")
    questions = [
        {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"},
        {"id": "q_desc", "label": "Description", "required": False, "maps_to": "description"},
        {"id": "q_assignee", "label": "Assignee", "required": False, "maps_to": "assignee"},
        {"id": "q_due", "label": "Due", "required": False, "maps_to": "due_on"},
        {"id": "q_priority", "label": "Priority", "required": False, "maps_to": "priority"},
        {"id": "q_field", "label": "Notes", "required": False, "maps_to": field_id},
    ]
    form = await _form(ravi, pid, questions, section_id=sections.get("To do"))
    r = await ravi.post(
        f"/api/v1/forms/{form['id']}/submit",
        json={
            "answers": {
                "q_title": "  From the intake form  ",
                "q_desc": "Some details",
                "q_assignee": member,
                "q_due": "2026-12-01",
                "q_priority": "high",
                "q_field": "hello",
            }
        },
    )
    assert r.status_code == 200, r.text
    async with uow.transaction() as s:
        task = (
            await s.execute(select(Task).where(Task.title == "From the intake form"))
        ).scalar_one()
        assert task.assignee_id is not None and str(task.assignee_id) == member
        assert task.priority == "high"
        assert task.due_on is not None and task.due_on.isoformat() == "2026-12-01"
        sub = (
            await s.execute(select(FormSubmission).where(FormSubmission.task_id == task.id))
        ).scalar_one()
        assert sub.submitted_by is not None


async def test_branching_hides_a_question_from_the_required_check(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field_id = await _field(ravi, pid, type="text")
    questions = [
        {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"},
        {"id": "q_gate", "label": "Need details?", "required": False, "maps_to": "priority"},
        {
            "id": "q_detail",
            "label": "Details",
            "required": True,
            "maps_to": field_id,
            "show_if": {"question_id": "q_gate", "equals": "urgent"},
        },
    ]
    form = await _form(ravi, pid, questions)
    # q_gate isn't "urgent", so q_detail is hidden and its required flag doesn't apply
    ok = await ravi.post(
        f"/api/v1/forms/{form['id']}/submit",
        json={"answers": {"q_title": "No details needed", "q_gate": "low"}},
    )
    assert ok.status_code == 200, ok.text
    # q_gate is "urgent", so q_detail is shown and required
    missing = await ravi.post(
        f"/api/v1/forms/{form['id']}/submit",
        json={"answers": {"q_title": "Needs details", "q_gate": "urgent"}},
    )
    assert missing.status_code == 422, missing.text


async def test_description_answer_is_capped(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    questions = [
        {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"},
        {"id": "q_desc", "label": "Description", "required": False, "maps_to": "description"},
    ]
    form = await _form(ravi, pid, questions)
    huge = "x" * 20000
    r = await ravi.post(
        f"/api/v1/forms/{form['id']}/submit",
        json={"answers": {"q_title": "Capped description", "q_desc": huge}},
    )
    assert r.status_code == 200, r.text
    async with uow.transaction() as s:
        task = (
            await s.execute(select(Task).where(Task.title == "Capped description"))
        ).scalar_one()
        assert task.description_text is not None
        assert len(task.description_text) <= 5000


async def test_disabled_form_refuses_submission(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, _questions(), enabled=False)
    r = await ravi.post(f"/api/v1/forms/{form['id']}/submit", json={"answers": {"q_title": "Nope"}})
    assert r.status_code == 404


# ---------------- public link ----------------


async def test_public_form_view_and_submit(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    field_id = await _field(
        ravi,
        pid,
        type="single_select",
        options=[{"label": "Bug"}, {"label": "Feature"}],
    )
    questions = [
        {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"},
        {"id": "q_kind", "label": "Kind", "required": False, "maps_to": field_id},
        {"id": "q_who", "label": "Who should own this?", "required": False, "maps_to": "assignee"},
    ]
    form = await _form(ravi, pid, questions, public_enabled=True)
    token = form["public_token"]
    # not yet public: another form defaults public_enabled=False
    private = await _form(ravi, pid, _questions())
    async with _public_client(as_user) as pub:
        hidden = await pub.get(f"/api/v1/public/forms/{private['public_token']}")
        assert hidden.status_code == 404
        view = await pub.get(f"/api/v1/public/forms/{token}")
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["name"] == "Intake"
        by_id = {q["id"]: q for q in body["questions"]}
        assert by_id["q_kind"]["kind"] == "select"
        assert {o["label"] for o in by_id["q_kind"]["options"]} == {"Bug", "Feature"}
        assert by_id["q_who"]["kind"] == "person" and by_id["q_who"]["people"]
        kind_option = by_id["q_kind"]["options"][0]["id"]
        submitted = await pub.post(
            f"/api/v1/public/forms/{token}/submit",
            json={"answers": {"q_title": "Reported anonymously", "q_kind": kind_option}},
        )
        assert submitted.status_code == 201, submitted.text
    async with uow.transaction() as s:
        task = (
            await s.execute(select(Task).where(Task.title == "Reported anonymously"))
        ).scalar_one()
        assert task.created_via == "form"
        sub = (
            await s.execute(select(FormSubmission).where(FormSubmission.task_id == task.id))
        ).scalar_one()
        assert sub.submitted_by is None and sub.ip_hash is not None


async def test_honeypot_silently_drops_the_submission(as_user: Clients, uow: UnitOfWork) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, _questions(), public_enabled=True)
    async with uow.transaction() as s:
        before = (await s.execute(select(FormSubmission))).scalars().all()
    async with _public_client(as_user) as pub:
        r = await pub.post(
            f"/api/v1/public/forms/{form['public_token']}/submit",
            json={"answers": {"q_title": "Spam"}, "website": "http://spam.example"},
        )
    assert r.status_code == 201, r.text  # looks like success; nothing was created
    async with uow.transaction() as s:
        after = (await s.execute(select(FormSubmission))).scalars().all()
        titled = (await s.execute(select(Task).where(Task.title == "Spam"))).scalars().all()
    assert len(after) == len(before)
    assert titled == []


async def test_public_form_is_rate_limited_per_ip(app_factory: Any, seeded: None) -> None:
    app = app_factory(forms_rate_limit_per_ip=2, forms_rate_limit_per_form=100)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        try:
            ravi = await clients("ravi")
            pid = await _project(ravi)
            form = await _form(ravi, pid, _questions(), public_enabled=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as pub:
                for _ in range(2):
                    ok = await pub.post(
                        f"/api/v1/public/forms/{form['public_token']}/submit",
                        json={"answers": {"q_title": "One more"}},
                    )
                    assert ok.status_code == 201, ok.text
                limited = await pub.post(
                    f"/api/v1/public/forms/{form['public_token']}/submit",
                    json={"answers": {"q_title": "Once too many"}},
                )
                assert limited.status_code == 429, limited.text
        finally:
            await clients.close()


# ---------------- rules integration ----------------


async def test_form_submitted_trigger_fires_a_rule(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, _questions())
    rule = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "On intake",
            "project_id": pid,
            "trigger": {"type": "form.submitted", "form_id": form["id"]},
            "actions": [{"type": "add_comment", "text": "Thanks for the submission!"}],
        },
    )
    assert rule.status_code == 201, rule.text
    submitted = await ravi.post(
        f"/api/v1/forms/{form['id']}/submit", json={"answers": {"q_title": "Please triage"}}
    )
    assert submitted.status_code == 200, submitted.text
    async with uow.transaction() as s:
        await run_rules(s, settings)
    listing = await ravi.get(f"/api/v1/projects/{pid}/tasks")
    task = next(t for t in listing.json()["data"] if t["title"] == "Please triage")
    feed = await ravi.get(f"/api/v1/tasks/{task['id']}/feed")
    comments = [i["comment"] for i in feed.json()["data"] if i.get("kind") == "comment"]
    texts = [
        span["text"]
        for c in comments
        for para in c["body"]["content"]
        for span in para.get("content", [])
    ]
    assert any("Thanks for the submission" in t for t in texts), feed.json()


async def test_form_to_triage_to_assignment_end_to_end(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    """Phase 4 exit: "a form → triage → assignment flow works end to end" — a public submission
    creates the task (intake), a form.submitted rule leaves a triage note and assigns it to a
    team member (triage + assignment), all through the ordinary write paths."""
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    member = await _member(ravi, pid)
    form = await _form(ravi, pid, _questions(), public_enabled=True)
    rule = await ravi.post(
        "/api/v1/rules",
        json={
            "name": "Triage intake",
            "project_id": pid,
            "trigger": {"type": "form.submitted", "form_id": form["id"]},
            "actions": [
                {"type": "add_comment", "text": "Triaged from intake form."},
                {"type": "assign", "user_id": member},
            ],
        },
    )
    assert rule.status_code == 201, rule.text

    public = _public_client(as_user)
    submitted = await public.post(
        f"/api/v1/public/forms/{form['public_token']}/submit",
        json={"answers": {"q_title": "Customer reported a bug"}},
    )
    assert submitted.status_code == 201, submitted.text

    async with uow.transaction() as s:
        await run_rules(s, settings)

    listing = await ravi.get(f"/api/v1/projects/{pid}/tasks")
    task = next(t for t in listing.json()["data"] if t["title"] == "Customer reported a bug")
    assert task["assignee_id"] == member

    feed = await ravi.get(f"/api/v1/tasks/{task['id']}/feed")
    comments = [i["comment"] for i in feed.json()["data"] if i.get("kind") == "comment"]
    texts = [
        span["text"]
        for c in comments
        for para in c["body"]["content"]
        for span in para.get("content", [])
    ]
    assert any("Triaged from intake form." in t for t in texts), feed.json()


@pytest.mark.parametrize("field", ["due_on"])
async def test_invalid_due_date_answer_is_rejected(as_user: Clients, field: str) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    questions = [
        {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"},
        {"id": "q_due", "label": "Due", "required": False, "maps_to": field},
    ]
    form = await _form(ravi, pid, questions)
    r = await ravi.post(
        f"/api/v1/forms/{form['id']}/submit",
        json={"answers": {"q_title": "Bad date", "q_due": "not-a-date"}},
    )
    assert r.status_code == 422, r.text
