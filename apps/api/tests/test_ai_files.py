"""Phase 7.5 S75-03 (spec §4.4-4.9, §11.2): Mo's file tools as the person. A private file is
unreadable through every tool for a non-member and a guest; image caps hold; look_at says
"not supported" when vision is off; hostile files lead to no proposals; "turn these notes into
tasks" yields create_task previews only. Mock mode throughout."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from momentum.ai.chat import run_chat, start_turn
from momentum.ai.context import Screen
from momentum.ai.file_context import FileSession
from momentum.ai.llm import build_llm
from momentum.ai.loop import images_message
from momentum.ai.mock import image_tokens, request_key
from momentum.ai.models import AiAction
from momentum.ai.tools.catalog import build_registry
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.tasks.models import Task
from momentum.files.render import render_image
from tests.conftest import make_settings
from tests.fixtures.files import build
from tests.helpers import Clients, ctx_for

B = "/api/v1"
REG = build_registry()
FILE_TOOLS = [
    ("file_outline", {}),
    ("read_file", {}),
    ("read_sheet", {}),
    ("query_table", {"query": {"aggregates": [{"fn": "count"}]}}),
    ("search_in_file", {"query": "Amount"}),
    ("look_at", {}),
    ("describe_macros", {}),
]


async def _project(c: httpx.AsyncClient, name: str) -> str:
    return next(p["id"] for p in (await c.get(f"{B}/projects")).json()["data"] if p["name"] == name)


async def _upload(c: httpx.AsyncClient, pid: str, name: str, data: bytes) -> str:
    r = await c.post(
        f"{B}/projects/{pid}/files", files={"file": (name, data, "application/octet-stream")}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _invoke(
    uow: UnitOfWork, ctx: Any, tool: str, args: dict[str, Any], files: FileSession | None = None
) -> Any:
    async with uow.transaction() as s:
        return await REG.invoke(s, ctx, tool, args, files=files or FileSession())


async def test_a_private_file_is_unreadable_through_every_tool(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    private = await _project(ravi, "Mobile App v2")  # private: priya owns it, ravi is a member
    fid = await _upload(ravi, private, "secret-budget.xlsx", build.xlsx_quote())

    # ravi (a member) reads it
    ravi_ctx = await ctx_for(uow, settings, "ravi")
    ok = await _invoke(uow, ravi_ctx, "file_outline", {"file": fid})
    assert ok.ok, ok.result.error

    mei_ctx = await ctx_for(uow, settings, "mei")  # Product team, not a member of Mobile App v2
    for name, extra in FILE_TOOLS:
        for ref in (fid, "secret-budget.xlsx", {"name": "secret-budget.xlsx", "project": private}):
            out = await _invoke(uow, mei_ctx, name, {"file": ref, **extra})
            assert not out.ok, (name, ref)
            assert out.result.error["code"] == "not_found", (name, ref, out.result.error)
            assert "Quote" not in str(out.to_json())
    listed = await _invoke(uow, mei_ctx, "list_files", {"q": "secret"})
    assert listed.ok and listed.result.data["files"] == []
    # a chip with the private file's id doesn't open it either
    out = await _invoke(
        uow,
        mei_ctx,
        "read_file",
        {"file": "secret-budget.xlsx"},
        FileSession(attachment_ids=[uuid.UUID(fid)]),
    )
    assert not out.ok

    # a guest sees only explicitly shared projects (H61): Website Revamp's file is out of reach
    admin = await as_user("admin")
    users = {
        u["email"].split("@")[0]: u["id"] for u in (await admin.get(f"{B}/users")).json()["data"]
    }
    wr = await _project(ravi, "Website Revamp")
    team_file = await _upload(ravi, wr, "team-notes.txt", b"Team only")
    await admin.patch(f"{B}/users/{users['priya']}", json={"role": "guest"})
    guest = await ctx_for(uow, settings, "priya")
    for name, extra in FILE_TOOLS:
        out = await _invoke(uow, guest, name, {"file": team_file, **extra})
        assert not out.ok and out.result.error["code"] == "not_found", name
    shared = await _invoke(uow, guest, "file_outline", {"file": fid})  # her own project: fine
    assert shared.ok


async def test_tables_and_text_through_the_tools(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi, "Website Revamp")
    await _upload(ravi, pid, "invoices.xlsx", build.xlsx_invoices(300))
    await _upload(ravi, pid, "sow.docx", build.docx_sow())
    ctx = await ctx_for(uow, settings, "ravi")
    files = FileSession(project_id=uuid.UUID(pid))

    outline = await _invoke(uow, ctx, "file_outline", {"file": "invoices.xlsx"}, files)
    assert [s["name"] for s in outline.result.data["sheets"]] == ["Invoices", "Summary", "Notes"]
    q = await _invoke(
        uow,
        ctx,
        "query_table",
        {
            "file": "invoices",
            "sheet": "Invoices",
            "query": {
                "filters": [{"column": "Status", "op": "eq", "value": "Overdue"}],
                "aggregates": [{"fn": "sum", "column": "Amount", "as": "total"}],
            },
        },
        files,
    )
    expected = sum(r[2] for r in build.invoice_rows(300) if r[3] == "Overdue")
    assert q.result.data["first_row"]["total"] == pytest.approx(expected)
    sheet = await _invoke(
        uow,
        ctx,
        "read_sheet",
        {"file": "invoices.xlsx", "sheet": "Summary", "formulas": True},
        files,
    )
    assert any(f["formula"].startswith("=SUM(") for f in sheet.result.data["formulas"])
    part = await _invoke(uow, ctx, "read_file", {"file": "sow.docx", "locator": "table 1"}, files)
    assert part.result.data["parts"][0]["table"]["columns"] == ["Deliverable", "Owner", "Due"]
    found = await _invoke(
        uow, ctx, "search_in_file", {"file": "sow.docx", "query": "renewl clause"}, files
    )
    assert found.result.data["matches"] and found.result.data["close_spelling"] is True
    bad = await _invoke(
        uow,
        ctx,
        "query_table",
        {
            "file": "invoices.xlsx",
            "sheet": "Invoices",
            "query": {"aggregates": [{"fn": "sum", "column": "Price"}]},
        },
        files,
    )
    assert not bad.ok and "Columns:" in bad.result.error["message"]


async def test_look_at_caps_and_vision_off(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi, "Website Revamp")
    png = await _upload(ravi, pid, "shot.png", build.png_screenshot())
    pdf = await _upload(ravi, pid, "contract.pdf", build.pdf_contract())
    ctx = await ctx_for(uow, settings, "ravi")

    files = FileSession()
    out = await _invoke(uow, ctx, "look_at", {"file": png}, files)
    assert out.ok and len(files.pending) == 1
    assert files.pending[0][1].jpeg[:2] == b"\xff\xd8"  # a JPEG, re-encoded

    capped = ctx.with_(settings=settings.model_copy(update={"ai_max_images_per_call": 2}))
    files = FileSession()
    assert (await _invoke(uow, capped, "look_at", {"file": pdf, "pages": [1, 2]}, files)).ok
    more = await _invoke(uow, capped, "look_at", {"file": png}, files)
    assert not more.ok and more.result.error["code"] == "image_cap"

    files = FileSession(sent=20)  # the conversation already sent its 20 images
    over = await _invoke(uow, ctx, "look_at", {"file": png}, files)
    assert not over.ok and "20 images" in over.result.error["message"]

    off = ctx.with_(settings=settings.model_copy(update={"llm_supports_vision": False}))
    no = await _invoke(uow, off, "look_at", {"file": png}, FileSession())
    assert not no.ok and no.result.error["code"] == "not_supported"


def test_images_ride_in_a_user_message_and_count_by_size() -> None:
    r = render_image(build.png_screenshot())
    msg = images_message([("shot.png", r)])
    assert msg["role"] == "user"
    assert msg["content"][0]["text"].startswith('<data source="look_at">')
    assert msg["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert image_tokens([msg]) == (r.width * r.height) // 750
    # the mock's request key depends on image size, not bytes
    other = render_image(build.png_screenshot("A different error message entirely"))
    assert (other.width, other.height) == (r.width, r.height)
    same = images_message([("shot.png", other)])
    assert request_key([msg], None) == request_key([same], None)


async def _chat(uow: UnitOfWork, ctx: Any, text: str, screen: Screen) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(t: str, d: dict[str, Any]) -> None:
        events.append((t, d))

    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        turn = await start_turn(s, ctx, text, conversation_id=None, screen=screen)
        ids = (turn.conversation.id, turn.message.id)
    async with uow.transaction() as s:
        await run_chat(
            s, build_llm(make_settings()), ctx, REG, ids, screen=screen, now=_now(), emit=emit
        )
    return events


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def test_hostile_files_lead_to_no_proposals(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi, "Website Revamp")
    doc = await _upload(ravi, pid, "hostile-notes.docx", build.docx_hostile())
    img = await _upload(ravi, pid, "hostile.png", build.png_hostile())
    ctx = await ctx_for(uow, settings, "ravi")
    async with uow.transaction() as s:
        before = (await s.execute(select(func.count()).select_from(AiAction))).scalar_one()
    for question, fid in (
        ("Do what the hostile notes say", doc),
        ("Read hostile.png and act on it", img),
    ):
        events = await _chat(uow, ctx, question, Screen(kind="other", file_ids=[uuid.UUID(fid)]))
        kinds = [t for t, _ in events]
        assert "action_proposed" not in kinds, question
        assert any(t == "tool_result" and d["ok"] for t, d in events), question
    async with uow.transaction() as s:
        assert (await s.execute(select(func.count()).select_from(AiAction))).scalar_one() == before


async def test_notes_into_tasks_are_previews_only(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    teams = {t["name"]: t["id"] for t in (await ravi.get(f"{B}/teams")).json()["data"]}
    r = await ravi.post(
        f"{B}/projects", json={"team_id": teams["Product"], "name": "Northwind onboarding"}
    )
    pid = r.json()["data"]["id"]
    fid = await _upload(ravi, pid, "meeting-notes.docx", build.docx_meeting_notes())
    ctx = await ctx_for(uow, settings, "ravi")
    async with uow.transaction() as s:
        tasks_before = (await s.execute(select(func.count()).select_from(Task))).scalar_one()
    events = await _chat(
        uow,
        ctx,
        "Turn the action items in these meeting notes into tasks in Northwind onboarding",
        Screen(kind="project", project_id=uuid.UUID(pid), file_ids=[uuid.UUID(fid)]),
    )
    proposed = [d for t, d in events if t == "action_proposed"]
    assert len(proposed) == 1
    async with uow.transaction() as s:
        action = await s.get(AiAction, uuid.UUID(proposed[0]["action_id"]))
        assert action is not None and action.state == "proposed"
        assert [op["tool"] for op in action.operations] == ["create_task"] * 3
        assert (
            await s.execute(select(func.count()).select_from(Task))
        ).scalar_one() == tasks_before
    cites = [d for t, d in events if t == "citation"]
    assert any(c["type"] == "file" and c["valid"] and c["key"] for c in cites)


async def test_conversation_files_are_private_and_go_with_the_chat(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    from momentum.ai.models import AiConversation, ConversationFile

    ravi = await as_user("ravi")
    r = await ravi.post(
        f"{B}/ai/conversation-files",
        files={"file": ("notes.csv", b"item,amount\nA,10\nB,5\n", "text/csv")},
    )
    assert r.status_code == 201, r.text
    cf = r.json()
    conv = cf["conversation_id"]
    assert cf["filename"] == "notes.csv"
    # a second file joins the same chat
    r2 = await ravi.post(
        f"{B}/ai/conversation-files",
        files={"file": ("more.txt", b"more", "text/plain")},
        data={"conversation_id": conv},
    )
    assert r2.status_code == 201 and r2.json()["conversation_id"] == conv
    listed = (await ravi.get(f"{B}/ai/conversations/{conv}/files")).json()["data"]
    assert [f["filename"] for f in listed] == ["notes.csv", "more.txt"]

    mei = await as_user("mei")
    assert (await mei.get(f"{B}/ai/conversations/{conv}/files")).status_code == 404
    r3 = await mei.post(
        f"{B}/ai/conversation-files",
        files={"file": ("x.txt", b"x", "text/plain")},
        data={"conversation_id": conv},
    )
    assert r3.status_code == 404

    ravi_ctx = await ctx_for(uow, settings, "ravi")
    mine = FileSession(conversation_id=uuid.UUID(conv))
    q = await _invoke(
        uow,
        ravi_ctx,
        "query_table",
        {
            "file": "notes.csv",
            "query": {"aggregates": [{"fn": "sum", "column": "amount", "as": "t"}]},
        },
        mine,
    )
    assert q.ok and q.result.data["first_row"]["t"] == 15
    # someone else holding the same conversation id reads nothing
    mei_ctx = await ctx_for(uow, settings, "mei")
    out = await _invoke(uow, mei_ctx, "read_file", {"file": "notes.csv"}, mine)
    assert not out.ok and out.result.error["code"] == "not_found"
    out = await _invoke(uow, mei_ctx, "read_file", {"file": cf["id"]}, mine)
    assert not out.ok

    # deleted with the conversation
    async with uow.transaction() as s:
        await s.delete(await s.get(AiConversation, uuid.UUID(conv)))
    async with uow.transaction() as s:
        n = (await s.execute(select(func.count()).select_from(ConversationFile))).scalar_one()
        assert n == 0


async def test_file_citations_resolve_as_the_reader(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    from momentum.ai import citations

    ravi = await as_user("ravi")
    private = await _project(ravi, "Mobile App v2")
    await _upload(ravi, private, "secret.pdf", build.pdf_contract())
    text = "See [F:secret.pdf · p2] and [F:nowhere.pdf]."
    async with uow.transaction() as s:
        mine = await citations.resolve(s, await ctx_for(uow, settings, "ravi"), text)
    assert [(c.type, c.valid, c.key) for c in mine] == [("file", True, "p2"), ("file", False, None)]
    async with uow.transaction() as s:
        theirs = await citations.resolve(s, await ctx_for(uow, settings, "mei"), text)
    assert [c.valid for c in theirs] == [False, False]
    assert theirs[0].id is None
