"""S7.5.2 security review (OWASP ASVS L1): every API route refuses an anonymous caller (except the
few that are public on purpose, listed here); security headers on pages and API responses; a file
that could carry script (SVG, HTML) always downloads in a sandbox instead of rendering from our
origin; a hostile file name can't break the header."""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from typing import Any

import httpx

from momentum.core.http import SecurityHeadersMiddleware
from tests.helpers import Clients

# reachable without a session, by design (each one checked: what it exposes is public)
PUBLIC = {
    ("GET", "/api/v1/config"),  # runtime config the sign-in page needs (no secrets)
    ("GET", "/api/v1/dev/users"),  # dev sign-in only (auth_mode=dev; absent in production)
    ("POST", "/api/v1/dev/login"),
    ("POST", "/api/v1/dev/logout"),
    ("POST", "/api/v1/auth/logout"),
    # a published form and its conversational intake (S4.2.1, S4.2.2; rate-limited per IP)
    ("GET", "/api/v1/public/forms/{token}"),
    ("POST", "/api/v1/public/forms/{token}/submit"),
    ("POST", "/api/v1/public/forms/{token}/converse"),
    ("POST", "/api/v1/public/forms/{token}/converse/submit"),
}
H = {"X-Requested-With": "momentum"}


def _fill(path: str) -> str:
    return re.sub(r"{[^}]+}", lambda m: str(uuid.uuid4()) if "id" in m.group(0) else "x", path)


async def test_every_api_route_refuses_an_anonymous_caller(as_user: Clients) -> None:
    await as_user("ravi")  # starts the app; this client is not used below
    app = as_user.app
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    paths = app.openapi()["paths"]
    operations = [
        (method.upper(), path)
        for path, item in paths.items()
        for method in item
        if path.startswith("/api/v1/") and method in ("get", "post", "put", "patch", "delete")
    ]
    assert len(operations) > 150
    open_ = []
    for method, path in operations:
        if (method, path) in PUBLIC:
            continue
        r = await anon.request(method, _fill(path), headers=H, json={})
        if r.status_code not in (401, 403):
            open_.append(f"{method} {path} → {r.status_code}")
    await anon.aclose()
    assert open_ == [], "answered without a session:\n" + "\n".join(open_)


async def test_security_headers(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    api = await ravi.get("/api/v1/me")
    assert api.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert api.headers["x-frame-options"] == "SAMEORIGIN"
    assert "strict-transport-security" not in api.headers  # only behind TLS in production
    page = await ravi.get("/healthz")
    csp = page.headers["content-security-policy"]
    assert "script-src 'self';" in csp and "unsafe-eval" not in csp
    assert "connect-src 'self' ws://testserver wss://testserver" in csp
    assert "frame-ancestors 'self'" in csp


async def test_hsts_in_production_and_a_host_can_frame_momentum() -> None:
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    settings = SimpleNamespace(
        env="production", frame_ancestors="https://host.example", content_security_policy=""
    )
    mw = SecurityHeadersMiddleware(app, api_prefix="/api/v1", settings=settings)
    await mw({"type": "http", "path": "/", "headers": [(b"host", b"m.example")]}, None, send)
    headers = dict(sent[0]["headers"])
    assert headers[b"strict-transport-security"].startswith(b"max-age=31536000")
    assert b"frame-ancestors https://host.example" in headers[b"content-security-policy"]
    assert b"x-frame-options" not in headers  # a named host: CSP alone says it


SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


async def _upload(c: httpx.AsyncClient, name: str, data: bytes, mime: str) -> httpx.Response:
    pid = next(
        p["id"]
        for p in (await c.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    t = (await c.post(f"/api/v1/projects/{pid}/tasks", json={"title": "Files"})).json()["data"]
    r = await c.post(f"/api/v1/tasks/{t['id']}/attachments", files={"file": (name, data, mime)})
    assert r.status_code == 201, r.text
    return await c.get(f"/api/v1/attachments/{r.json()['data']['id']}/download")


async def test_a_file_that_could_carry_script_never_renders(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    svg = await _upload(ravi, 'evil".svg', SVG, "image/svg+xml")
    assert re.fullmatch(
        r"attachment; filename=\"[^\"\\]*\"; filename\*=UTF-8''[A-Za-z0-9%._~-]+",
        svg.headers["content-disposition"],
    )
    assert "sandbox" in svg.headers["content-security-policy"]
    assert svg.headers["x-content-type-options"] == "nosniff"
    html = await _upload(ravi, "page.png", b"<html><script>x</script></html>", "image/png")
    assert html.headers["content-disposition"].startswith("attachment")  # the bytes aren't a PNG
    png = await _upload(ravi, "dot.png", PNG, "image/png")
    assert png.headers["content-type"] == "image/png"
    assert png.headers["content-disposition"].startswith("inline")


async def test_a_cookie_session_needs_the_csrf_header_to_change_anything(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    pid = next(
        p["id"]
        for p in (await ravi.get("/api/v1/projects")).json()["data"]
        if p["name"] == "Website Revamp"
    )
    r = await ravi.post(
        f"/api/v1/projects/{pid}/tasks",
        json={"title": "Forged"},
        headers={"X-Requested-With": ""},  # what a cross-site form post would send
    )
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
    assert (await ravi.get("/api/v1/projects", headers={"X-Requested-With": ""})).status_code == 200
