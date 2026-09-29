"""S5.1.5 (ADR-0009): host tools, host definition directories, code-backed handler agents, and
the get_attachment_text tool."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from momentum.agents.extensions import EMPTY, load_extensions
from momentum.agents.runtime import execute_run
from momentum.agents.triggers import request_run
from momentum.ai.models import AiAction, LlmCall
from momentum.ai.tools.catalog import build_registry
from momentum.core.db import UnitOfWork
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.runs import claim_runs
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from tests import agent_ext_fixture as host
from tests.ai_fixtures import World, call, world
from tests.conftest import make_settings
from tests.helpers import Clients
from tests.test_agent_runtime import Env, _defn, make_env

_ = (world, make_env)
HOST_REG = build_registry(*host.extensions.tools)


def _handler_defn(handler: str, **over: Any) -> Any:
    return _defn(key="uploader", name="ERP Uploader", kind="handler", handler=handler, **over)


async def _drain(env: Env, registry: Any = HOST_REG) -> list[str]:
    async with env.uow.transaction() as s:
        claimed = await claim_runs(s, timeout_s=300)
    out = []
    for run_id in claimed.run_ids:
        async with env.uow.transaction() as s:
            out.append(
                await execute_run(
                    s, env.llm, registry, env.settings, run_id, handlers=host.extensions.handlers
                )
            )
    return out


async def _run_on_copy(env: Env) -> None:
    async with env.uow.transaction() as s:
        await request_run(s, env.world.ravi, env.agent, task_id=env.world.copy.id)


# ---------- loading ----------


def test_extensions_load_from_the_setting() -> None:
    assert load_extensions(make_settings()) is EMPTY
    ext = load_extensions(make_settings(agent_extensions="tests.agent_ext_fixture:extensions"))
    assert [t.spec.name for t in ext.tools] == ["lookup_customer"]
    called = load_extensions(
        make_settings(agent_extensions="tests.agent_ext_fixture:make_extensions")
    )
    assert set(called.handlers) == {"acme.erp:upload", "acme.erp:broken", "acme.erp:slow"}
    with pytest.raises(ValueError, match=r"package\.module:attribute"):
        load_extensions(make_settings(agent_extensions="tests.agent_ext_fixture"))
    with pytest.raises(ValueError, match="not an Extensions"):
        load_extensions(make_settings(agent_extensions="tests.agent_ext_fixture:not_extensions"))


async def test_the_app_gets_host_tools_handlers_and_definitions(
    seeded: None, tmp_path: Path
) -> None:
    from momentum.app import create_app

    (tmp_path / "crm_helper.yaml").write_text(
        "key: crm_helper\nname: CRM Helper\ntools: [lookup_customer, add_comment]\n"
    )
    settings = make_settings(agent_extensions="tests.agent_ext_fixture:extensions")
    app = create_app(settings, agent_definition_dirs=[tmp_path])
    async with app.router.lifespan_context(app):
        runtime = app.state.momentum
        assert runtime.tools.get("lookup_customer") is not None
        assert "acme.erp:upload" in runtime.agent_handlers
        clients = Clients(app)
        admin = await clients("admin")
        r = await admin.post("/api/v1/agents/install", json={"keys": ["crm_helper"]})
        assert r.status_code == 200, r.text  # a host tool is a known tool
        await clients.close()


# ---------- handler agents ----------


async def test_a_handler_agent_does_its_work_like_any_agent(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_handler_defn("acme.erp:upload", tools=["get_task", "update_task"]))
    await _run_on_copy(env)
    assert await _drain(env) == ["succeeded"]
    w = env.world
    async with env.uow.transaction() as s:
        run = (await s.execute(select(AgentRun))).scalar_one()
        comment = (
            await s.execute(select(Comment).where(Comment.task_id == w.copy.id))
        ).scalar_one()
        att = (
            await s.execute(select(Attachment).where(Attachment.task_id == w.copy.id))
        ).scalar_one()
        action = (await s.execute(select(AiAction))).scalar_one()
        billed = await s.scalar(
            select(func.count()).select_from(LlmCall).where(LlmCall.agent_run_id == run.id)
        )
    steps = [(st["kind"], st["summary"]) for st in run.trace]
    assert ("step", "Uploading data for Draft pricing copy") in steps
    assert ("step", "Attached upload-report.txt") in steps
    # its answer in the thread, marked AI; its file readable; its proposal waiting for ravi
    assert (
        comment.author_id == env.account.id
        and comment.is_ai
        and "Uploaded 42 rows" in str(comment.body)
    )
    assert att.uploaded_by == env.account.id and att.text_extract == "Uploaded 42 rows to the ERP."
    assert action.state == "proposed" and action.proposed_for == w.ravi.actor.id
    assert billed == 1  # its model call counts against its budget


async def test_a_failing_or_slow_handler_fails_clearly_and_rolls_back(
    make_env: Callable[..., Env], monkeypatch: pytest.MonkeyPatch
) -> None:
    from momentum.agents import runtime

    env = make_env()
    await env.install(_handler_defn("acme.erp:broken"))
    await _run_on_copy(env)
    assert await _drain(env) == ["failed"]
    [run] = await env.runs()
    assert run.error == "The handler failed: RuntimeError: ERP is down"

    # the host changes which function backs the agent (definitions carry it; no API for it)
    async with env.uow.transaction() as s:
        agent = await s.get(type(env.agent), env.agent.id)
        assert agent is not None
        agent.handler = "acme.erp:slow"
    monkeypatch.setattr(runtime, "_limits", lambda a, s: (5, 0))
    async with env.uow.transaction() as s:
        await request_run(s, env.world.ravi, agent, task_id=env.world.faq.id)
    assert await _drain(env) == ["failed"]
    runs = await env.runs()
    assert "time limit" in (runs[-1].error or "")


# ---------- host tools ----------


async def test_a_model_agent_can_call_a_host_tool(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_defn(tools=["lookup_customer", "get_task"]), tool_names=HOST_REG.names)
    env.script(
        [
            {
                "match": {"contains": "asked you to run", "turn": 1},
                "tool_calls": [{"name": "lookup_customer", "arguments": {"customer": "Acme Ltd"}}],
            },
            {
                "match": {"contains": "asked you to run", "turn": 2},
                "text": "(mock) Acme is gold tier.",
            },
        ]
    )
    await _run_on_copy(env)
    assert await _drain(env) == ["succeeded"]
    [run] = await env.runs()
    [tool_step] = [st for st in run.trace if st["kind"] == "tool"]
    assert tool_step["name"] == "lookup_customer" and tool_step["ok"] is True


# ---------- get_attachment_text ----------


async def _file(
    uow: UnitOfWork, w: World, name: str, text: str | None, status: str = "done"
) -> None:
    async with uow.transaction() as s:
        s.add(
            Attachment(
                workspace_id=w.project.workspace_id,
                task_id=w.copy.id,
                storage_key=f"x/{name}",
                filename=name,
                mime="application/pdf",
                size_bytes=10,
                sha256="0" * 64,
                text_extract=text,
                extract_status=status,
                uploaded_by=w.ravi.actor.id,
            )
        )


async def test_get_attachment_text(uow: UnitOfWork, world: World) -> None:
    w = world
    await _file(uow, w, "invoice-2026-09.pdf", "Invoice total: 1,200 EUR " + "x" * 30_000)
    out = await call(uow, w.ravi, "get_attachment_text", {"task": "Draft pricing copy"})
    assert out.ok and out.result.data["file"] == "invoice-2026-09.pdf"
    assert out.result.data["truncated"] is True and len(out.result.data["text"]) == 20_000
    assert "<data" in out.message_content()  # tool output is data, never instructions

    await _file(uow, w, "contract.pdf", None, status="pending")
    both = await call(uow, w.ravi, "get_attachment_text", {"task": "Draft pricing copy"})
    assert not both.ok and both.result.error["code"] == "ambiguous"  # type: ignore[index]
    pending = await call(
        uow, w.ravi, "get_attachment_text", {"task": "Draft pricing copy", "name": "contract"}
    )
    assert pending.result.error["code"] == "not_ready"  # type: ignore[index]
    # someone who can't see the task can't read its files
    hidden = await call(uow, w.tom, "get_attachment_text", {"task": str(w.copy.id)})
    assert not hidden.ok and hidden.result.error["code"] == "not_found"  # type: ignore[index]
    # get_task names the files
    detail = await call(uow, w.ravi, "get_task", {"task": "Draft pricing copy"})
    assert detail.result.data["task"]["attachments"] == ["invoice-2026-09.pdf", "contract.pdf"]
