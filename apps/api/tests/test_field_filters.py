"""S7.4.1: custom-field filters (``domain/fields/filters.py``): every op on every field type, across
two projects sharing a field, the text form, and the errors a wrong filter gets."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from momentum.core.db import UnitOfWork
from momentum.core.errors import ValidationFailed
from momentum.core.settings import Settings
from momentum.domain.fields.filters import (
    FieldFilter,
    field_conditions,
    parse_field_filter,
    parse_field_filters,
)
from momentum.domain.tasks.models import Task
from tests.helpers import Clients, ctx_for


async def _project(c: httpx.AsyncClient, name: str) -> str:
    return next(  # type: ignore[no-any-return]
        p["id"] for p in (await c.get("/api/v1/projects")).json()["data"] if p["name"] == name
    )


async def _field(c: httpx.AsyncClient, pid: str, **body: Any) -> dict[str, Any]:
    r = await c.post(f"/api/v1/projects/{pid}/fields", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]  # type: ignore[no-any-return]


async def _task(c: httpx.AsyncClient, pid: str, title: str, **values: Any) -> str:
    t = (await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": title})).json()["data"]
    for fid, v in values.items():
        r = await c.put(f"/api/v1/tasks/{t['id']}/fields/{fid}", json={"value": v})
        assert r.status_code == 200, r.text
    return t["id"]  # type: ignore[no-any-return]


async def test_every_op_on_every_type_across_two_projects(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    web, mobile = await _project(ravi, "Website Revamp"), await _project(ravi, "Mobile App v2")
    stage = await _field(
        ravi,
        web,
        name="Stage",
        type="single_select",
        options=[{"label": "Plan"}, {"label": "Ship"}],
    )
    plan, ship = (o["id"] for o in stage["options"])
    areas = await _field(
        ravi, web, name="Areas", type="multi_select", options=[{"label": "UI"}, {"label": "API"}]
    )
    ui, api = (o["id"] for o in areas["options"])
    points = await _field(ravi, web, name="Points", type="number")
    target = await _field(ravi, web, name="Target", type="date")
    note = await _field(ravi, web, name="Note", type="text")
    legal = await _field(ravi, web, name="Legal", type="checkbox")
    owners = await _field(ravi, web, name="Owners", type="people")
    # the same Stage field on a second project: filters span both
    r = await ravi.post(f"/api/v1/projects/{mobile}/fields/attach", json={"field_id": stage["id"]})
    assert r.status_code in (200, 201), r.text
    me = (await ravi.get("/api/v1/me")).json()["user"]["id"]

    a = await _task(
        ravi,
        web,
        "A",
        **{
            stage["id"]: plan,
            areas["id"]: [ui, api],
            points["id"]: 3,
            target["id"]: "2030-01-10",
            note["id"]: "Needs 100% sign-off",
            legal["id"]: True,
            owners["id"]: [me],
        },
    )
    b = await _task(
        ravi,
        web,
        "B",
        **{stage["id"]: ship, areas["id"]: [api], points["id"]: 8.5, note["id"]: "copy"},
    )
    c = await _task(ravi, mobile, "C", **{stage["id"]: ship})
    d = await _task(ravi, web, "D")  # no values at all
    mine = {a, b, c, d}

    async def ids(*texts: str) -> set[str]:
        ctx = await ctx_for(uow, settings, "ravi")
        async with uow.transaction() as s:
            conds = await field_conditions(s, ctx, parse_field_filters(list(texts)))
            rows = (await s.execute(select(Task.id).where(*conds))).scalars()
            return {str(i) for i in rows} & mine

    S, A, P, T, N, L, W = (
        stage["id"],
        areas["id"],
        points["id"],
        target["id"],
        note["id"],
        legal["id"],
        owners["id"],
    )
    assert await ids(f"{S}:any:{ship}") == {b, c}  # across both projects
    assert await ids(f"{S}:any:{plan},none") == {a, d}
    assert await ids(f"{A}:any:{ui}") == {a}
    assert await ids(f"{A}:any:{api}") == {a, b}
    assert await ids(f"{P}:min:3", f"{P}:max:8") == {a}
    assert await ids(f"{P}:min:4") == {b}
    assert await ids(f"{T}:min:2030-01-01", f"{T}:max:2030-01-31") == {a}
    assert await ids(f"{N}:has:100%") == {a}  # % is literal, not a wildcard
    assert await ids(f"{N}:has:COPY") == {b}
    assert await ids(f"{L}:any:true") == {a}
    assert await ids(f"{L}:any:false") == {b, c, d}  # unchecked and never set read the same
    assert await ids(f"{W}:any:{me}") == {a}
    assert await ids(f"{P}:set") == {a, b}
    assert await ids(f"{P}:empty") == {c, d}
    assert await ids(f"{S}:any:{ship}", f"{P}:set") == {b}  # AND-ed


def test_the_text_form_round_trips_and_explains_mistakes() -> None:
    fid = "01a10bbc-85b8-7013-815b-71c5b6893e6a"
    for text in (f"{fid}:any:a,b", f"{fid}:min:3", f"{fid}:has:a:b", f"{fid}:empty"):
        assert parse_field_filter(text).to_text() == text
    assert parse_field_filter(f"{fid}:has:a:b").value == "a:b"  # only the first two colons split
    for bad in ("nope:any:x", f"{fid}:like:x", f"{fid}:any:", f"{fid}:min:", f"{fid}:set:x"):
        with pytest.raises(ValidationFailed):
            parse_field_filter(bad)
    with pytest.raises(ValidationFailed):
        parse_field_filters([f"{fid}:set"] * 11)


async def test_a_filter_must_suit_its_field(
    as_user: Clients, uow: UnitOfWork, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    web = await _project(ravi, "Website Revamp")
    points = await _field(ravi, web, name="Points", type="number")
    note = await _field(ravi, web, name="Note", type="text")
    ctx = await ctx_for(uow, settings, "ravi")
    wrong = [
        FieldFilter(field_id=points["id"], op="any", values=["x"]),
        FieldFilter(field_id=points["id"], op="has", value="x"),
        FieldFilter(field_id=note["id"], op="min", value="3"),
        FieldFilter(field_id=points["id"], op="min", value="lots"),
        FieldFilter(field_id="01a10bbc-85b8-7013-815b-71c5b6893e6a", op="set"),
    ]
    for f in wrong:
        async with uow.transaction() as s:
            with pytest.raises(ValidationFailed):
                await field_conditions(s, ctx, [f])
