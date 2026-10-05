"""Robustness sweep over every API operation (Phase 7 E7.0, kept as a regression test).

For each operation in the OpenAPI schema, the sweep builds a request from the schema (path ids
point at real entities of a small world made through the API, so handlers get past their 404s),
then sends it again with boundary values in every string field and string parameter: a NUL
character (Postgres rejects it in text), an emoji / right-to-left mix, and 10,000 characters.
Whatever the input, the API must answer with a 2xx/3xx/4xx, never a 5xx.

``PROBE_FULL=1`` adds more mutations (wrong types, negative and huge numbers) for exploratory runs.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

from tests.helpers import Clients

B = "/api/v1"
FULL = os.environ.get("PROBE_FULL") == "1"
NUL = "a\u0000b"
WEIRD = "‮RTL 😀 𝄞 ́ <b>x</b> '\" ; DROP TABLE"
LONG = "x" * 10_000
# operations that leave the session or need a body the sweep can't build
SKIP = {
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/dev/login"),
    ("POST", "/api/v1/dev/logout"),
}


def _resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    if "anyOf" in schema:  # Optional[X] → X
        options = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if options:
            return _resolve(spec, options[0])
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return _resolve(spec, schema["allOf"][0])
    return schema


def _value(spec: dict[str, Any], schema: dict[str, Any], name: str, ids: dict[str, str]) -> Any:
    s = _resolve(spec, schema)
    if "enum" in s:
        return s["enum"][0]
    if "const" in s:
        return s["const"]
    t = s.get("type")
    fmt = s.get("format")
    if fmt == "uuid" or (t == "string" and name.endswith("_id")):
        return ids.get(name, str(uuid.uuid4()))
    if t == "string":
        if fmt == "date":
            return "2026-10-15"
        if fmt == "date-time":
            return "2026-10-15T10:00:00Z"
        if fmt == "email":
            return "probe@acme-demo.test"
        return "Probe"[: s.get("maxLength", 5)].ljust(s.get("minLength", 0), "p")
    if t == "integer":
        return max(int(s.get("minimum", 1)), 1) if "maximum" not in s else int(s.get("minimum", 1))
    if t == "number":
        return float(s.get("minimum", 1))
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object" or "properties" in s:
        return {
            k: _value(spec, v, k, ids)
            for k, v in (s.get("properties") or {}).items()
            if k in (s.get("required") or [])
        }
    return None


def _strings(
    spec: dict[str, Any], schema: dict[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    """Paths to every plain string property (not ids, dates or enums) of a body schema."""
    s = _resolve(spec, schema)
    out: list[tuple[str, ...]] = []
    for k, v in (s.get("properties") or {}).items():
        r = _resolve(spec, v)
        if (
            r.get("type") == "string"
            and "enum" not in r
            and r.get("format") not in ("uuid", "date", "date-time")
            and not k.endswith("_id")
        ):
            out.append((*prefix, k))
        elif r.get("type") == "object" or "properties" in r:
            out += _strings(spec, v, (*prefix, k))
    return out


def _set(body: dict[str, Any], path: tuple[str, ...], value: Any) -> dict[str, Any]:
    import copy

    b = copy.deepcopy(body)
    cur = b
    for k in path[:-1]:
        cur = cur.setdefault(k, {})
    cur[path[-1]] = value
    return b


# Creation bodies the schema walk can't make valid on its own (nested required structures).
REAL_BODIES: dict[str, dict[str, Any]] = {
    "/forms": {
        "project_id": "",
        "name": "Probe form",
        "questions": [{"id": "q_title", "label": "Title", "required": True, "maps_to": "title"}],
    },
    "/rules": {
        "project_id": "",
        "name": "Probe rule",
        "trigger": {"type": "task.completed"},
        "actions": [{"type": "add_comment", "text": "done"}],
    },
    "/me/tokens": {"name": "probe", "scopes": ["read"]},
}


async def _world(c: httpx.AsyncClient) -> dict[str, str]:
    """Real ids for the path parameters, made through the API as the admin."""
    ids: dict[str, str] = {}
    team = (await c.get(f"{B}/teams")).json()["data"][0]
    ids["team_id"] = team["id"]
    p = (await c.post(f"{B}/projects", json={"team_id": team["id"], "name": "Probe Lab"})).json()[
        "data"
    ]
    ids["project_id"] = p["id"]
    sections = (await c.get(f"{B}/projects/{p['id']}/sections")).json()["data"]
    ids["section_id"] = sections[0]["id"]
    t = (await c.post(f"{B}/projects/{p['id']}/tasks", json={"title": "Probe task"})).json()["data"]
    t2 = (await c.post(f"{B}/projects/{p['id']}/tasks", json={"title": "Probe blocker"})).json()[
        "data"
    ]
    ids["task_id"] = t["id"]
    ids["depends_on_id"] = t2["id"]
    cm = await c.post(
        f"{B}/tasks/{t['id']}/comments", json={"body": {"type": "doc", "content": []}, "text": "hi"}
    )
    if cm.status_code < 300:
        ids["comment_id"] = cm.json()["data"]["id"]
    tag = await c.post(f"{B}/tags", json={"name": "probe-tag"})
    if tag.status_code < 300:
        ids["tag_id"] = tag.json()["data"]["id"]
    f = await c.post(f"{B}/fields", json={"name": "Probe field", "type": "text"})
    if f.status_code < 300:
        ids["field_id"] = f.json()["data"]["id"]
    # more entities, made from their own schemas, so their handlers get past the 404 too
    spec = (await c.get(f"{B}/openapi.json")).json()
    for path, key in (
        ("/goals", "goal_id"),
        ("/portfolios", "portfolio_id"),
        ("/dashboards", "dashboard_id"),
        ("/dashboards/{dashboard_id}/widgets", "widget_id"),
        ("/agents", "agent_id"),
        ("/forms", "form_id"),
        ("/rules", "rule_id"),
        ("/templates/from-project", "template_id"),
        ("/me/tokens", "token_id"),
        ("/ai/memory", "memory_id"),
    ):
        schema = (
            spec["paths"][B + path]["post"]
            .get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        body = _value(spec, schema, "", ids) if schema else None
        body = {**(body or {}), **REAL_BODIES.get(path, {})} if path in REAL_BODIES else body
        if path in REAL_BODIES and "project_id" in REAL_BODIES[path]:
            body["project_id"] = ids["project_id"]
        url = path
        for name, value in ids.items():
            url = url.replace("{" + name + "}", value)
        r = await c.post(B + url, json=body)
        if r.status_code < 300:
            data = r.json()
            data = data.get("data", data)
            if isinstance(data, dict) and "id" in data:
                ids[key] = str(data["id"])
    me = (await c.get(f"{B}/me")).json()
    ids["user_id"] = (me.get("data") or me).get("id", str(uuid.uuid4()))
    return ids


async def _sweep(c: httpx.AsyncClient, spec: dict[str, Any], ids: dict[str, str]) -> list[str]:
    failures: list[str] = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if (
                method not in ("get", "post", "put", "patch", "delete")
                or (method.upper(), path) in SKIP
            ):
                continue
            if path.startswith("/api/v1/dev") or "/ws" in path:
                continue
            params = op.get("parameters", [])
            url = path
            for prm in params:
                if prm["in"] == "path":
                    url = url.replace(
                        "{" + prm["name"] + "}", str(_value(spec, prm["schema"], prm["name"], ids))
                    )
            query = {
                prm["name"]: _value(spec, prm["schema"], prm["name"], ids)
                for prm in params
                if prm["in"] == "query" and prm.get("required")
            }
            body_schema = (
                op.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if op.get("requestBody") and body_schema is None:
                continue  # multipart uploads etc.
            body = _value(spec, body_schema, "", ids) if body_schema else None
            variants: list[tuple[str, dict[str, Any], Any]] = [("base", query, body)]
            for prm in params:
                r = _resolve(spec, prm["schema"])
                if (
                    prm["in"] == "query"
                    and r.get("type") == "string"
                    and "enum" not in r
                    and r.get("format") is None
                ):
                    for label, v in (("nul", NUL), ("weird", WEIRD), ("long", LONG)):
                        variants.append(
                            (f"query:{prm['name']}={label}", {**query, prm["name"]: v}, body)
                        )
            if body_schema:
                for sp in _strings(spec, body_schema):
                    for label, v in (("nul", NUL), ("weird", WEIRD), ("long", LONG)):
                        variants.append(
                            (f"body:{'.'.join(sp)}={label}", query, _set(body or {}, sp, v))
                        )
            if FULL and isinstance(body, dict):
                for k in list(body):
                    for label, v in (("neg", -1), ("huge", 2**63), ("list", [1]), ("null", None)):
                        variants.append((f"body:{k}={label}", query, {**body, k: v}))
            for label, q, b in variants:
                try:
                    r = await c.request(
                        method.upper(), url, params=q, json=b if body_schema else None
                    )
                except Exception as e:  # an exception escaping the app is a 500 too
                    failures.append(
                        f"{method.upper()} {path} [{label}] raised {type(e).__name__}: {e}"[:300]
                    )
                    continue
                if r.status_code >= 500 and not (
                    r.status_code == 503 and "ai_unavailable" in r.text
                ):
                    # (503 ai_unavailable is the designed answer when the mock model has no reply)
                    failures.append(
                        f"{method.upper()} {path} [{label}] -> {r.status_code} {r.text[:150]}"
                    )
    return failures


async def test_no_input_makes_the_api_fail(as_user: Clients) -> None:
    admin = await as_user("admin")
    spec = (await admin.get(f"{B}/openapi.json")).json()
    ids = await _world(admin)
    made = sorted(ids)
    failures = await _sweep(admin, spec, ids)
    assert len(made) >= 17, made  # the world really has the entities the sweep relies on
    # the same requests as a member who owns none of it (403/404 paths must not crash either)
    failures += [f"as mei: {f}" for f in await _sweep(await as_user("mei"), spec, ids)]
    assert not failures, f"{len(failures)} 5xx responses:\n" + "\n".join(failures[:80])
