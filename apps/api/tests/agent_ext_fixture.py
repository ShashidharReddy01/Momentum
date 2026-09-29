"""A pretend host application's agent extensions (S5.1.5 tests): one extra read tool and a few
handler agents. Loaded both directly and through MOMENTUM_AGENT_EXTENSIONS."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict

from momentum.agents.extensions import Extensions, HandlerResult, HandlerRun
from momentum.ai.tools.base import ToolContext, ToolResult, tool


class LookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer: str


@tool(
    name="lookup_customer",
    description="Look up a customer in the host's CRM.",
    risk="read",
    scopes=("tasks:read",),
)
async def lookup_customer(tc: ToolContext, args: LookupArgs) -> ToolResult:
    return ToolResult.success(f"Found {args.customer}", {"customer": args.customer, "tier": "gold"})


async def uploader(run: HandlerRun) -> HandlerResult:
    """Reads its task, attaches a report, proposes a change, and answers."""
    task = await run.task()
    assert task is not None
    run.step(f"Uploading data for {task.title}")
    looked = await run.read("get_task", {"task": str(task.id)})
    assert looked.ok
    await run.attach("upload-report.txt", b"Uploaded 42 rows to the ERP.", "text/plain")
    run.propose("update_task", {"task": str(task.id), "priority": "low"})
    completion = await run.complete([{"role": "user", "content": "summarise the upload"}])
    return HandlerResult(text=f"Uploaded 42 rows. ({completion.text[:20]})")


async def broken(run: HandlerRun) -> HandlerResult:
    raise RuntimeError("ERP is down")


async def slow(run: HandlerRun) -> HandlerResult:
    await asyncio.sleep(5)
    return HandlerResult()


extensions = Extensions(
    tools=[lookup_customer],
    handlers={"acme.erp:upload": uploader, "acme.erp:broken": broken, "acme.erp:slow": slow},
)


def make_extensions() -> Extensions:
    return extensions


not_extensions = 42
