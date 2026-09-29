"""S5.0.2: the public forms security review. Anonymous visitors never see the project's members
or pick an assignee; a signed-in submitter can only pick someone the form offers; the per-IP
rate limit uses an address a visitor can't forge (``MOMENTUM_TRUSTED_PROXY_HOPS``)."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from starlette.requests import Request

from momentum.api.deps import client_ip
from momentum.core.db import UnitOfWork
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User
from tests.helpers import Clients
from tests.test_forms import _form, _project, _public_client

WHO = {"id": "q_who", "label": "Owner", "required": True, "maps_to": "assignee"}
TITLE = {"id": "q_title", "label": "Title", "required": True, "maps_to": "title"}


async def _task(uow: UnitOfWork, title: str) -> Task:
    async with uow.transaction() as s:
        return (await s.execute(select(Task).where(Task.title == title))).scalar_one()


async def test_anonymous_visitors_never_see_or_pick_an_assignee(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, [TITLE, WHO], public_enabled=True)
    async with uow.transaction() as s:
        tom = (await s.execute(select(User).where(User.email.like("tom@%")))).scalar_one()
    async with _public_client(as_user) as pub:
        view = (await pub.get(f"/api/v1/public/forms/{form['public_token']}")).json()
        assert [q["id"] for q in view["questions"]] == ["q_title"]
        # a required assignee question doesn't block them, and an answer to it is ignored
        r = await pub.post(
            f"/api/v1/public/forms/{form['public_token']}/submit",
            json={"answers": {"q_title": "Anonymous report", "q_who": str(tom.id)}},
        )
        assert r.status_code == 201, r.text
    assert (await _task(uow, "Anonymous report")).assignee_id is None


async def test_a_signed_in_submitter_picks_only_someone_the_form_offers(
    as_user: Clients, uow: UnitOfWork
) -> None:
    ravi = await as_user("ravi")
    pid = await _project(ravi)
    form = await _form(ravi, pid, [TITLE, WHO])
    async with uow.transaction() as s:
        users = {u.email.split("@")[0]: u for u in (await s.execute(select(User))).scalars()}
    members = (await ravi.get(f"/api/v1/projects/{pid}")).json()["members"]
    member_ids = {m["user"]["id"] for m in members}
    outsider = next(u for u in users.values() if str(u.id) not in member_ids and not u.is_agent)
    url = f"/api/v1/forms/{form['id']}/submit"

    async def submit(title: str, who: Any) -> httpx.Response:
        return await ravi.post(url, json={"answers": {"q_title": title, "q_who": str(who)}})

    assert (await submit("To an outsider", outsider.id)).status_code == 422
    r = await submit("To a member", users["ravi"].id)
    assert r.is_success, r.text
    assert (await _task(uow, "To a member")).assignee_id == users["ravi"].id


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_client_ip_ignores_what_a_visitor_can_forge() -> None:
    # no proxy: the connection's address, whatever the header says
    assert client_ip(_request("203.0.113.9", "1.2.3.4"), 0) == "203.0.113.9"
    # one proxy (Azure App Service): the address it appended, the rightmost entry
    assert client_ip(_request("10.0.0.2", "198.51.100.7"), 1) == "198.51.100.7"
    assert client_ip(_request("10.0.0.2", "6.6.6.6, 198.51.100.7"), 1) == "198.51.100.7"
    # two proxies: the second from the right
    assert client_ip(_request("10.0.0.2", "6.6.6.6, 198.51.100.7, 10.0.0.9"), 2) == "198.51.100.7"
    # a proxy configured but no header (a direct health check): the connection's address
    assert client_ip(_request("10.0.0.2"), 1) == "10.0.0.2"


async def test_behind_a_proxy_the_rate_limit_follows_the_real_address(
    app_factory: Any, seeded: None
) -> None:
    app = app_factory(
        forms_rate_limit_per_ip=2, forms_rate_limit_per_form=100, trusted_proxy_hops=1
    )
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        try:
            ravi = await clients("ravi")
            pid = await _project(ravi)
            form = await _form(ravi, pid, [TITLE], public_enabled=True)
            url = f"/api/v1/public/forms/{form['public_token']}/submit"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as pub:

                async def post(forwarded: str) -> int:
                    r = await pub.post(
                        url,
                        json={"answers": {"q_title": "Hi"}},
                        headers={"X-Forwarded-For": forwarded},
                    )
                    return r.status_code

                assert await post("198.51.100.7") == 201
                assert await post("198.51.100.7") == 201
                # forging a different address on the left doesn't get past the limit
                assert await post("1.1.1.1, 198.51.100.7") == 429
                # and a different visitor behind the same proxy isn't blocked by the first
                assert await post("198.51.100.8") == 201
        finally:
            await clients.close()
