"""Seed synthetic records for the E2E journeys (Phase 7.6 S76-08): installs the agents (starters
and the test packs, all switched off, as "Install starter agents" does), then, as the Echo test
agent, two bills in Website Revamp (one with a rendered source image and located fields), a
vendor, and one proposed skill. Synthetic data only; refuses any database not ending in _e2e.
Run from apps/api with the E2E environment (tools/e2e/serve.sh)."""

from __future__ import annotations

import io
import os
import sys

from PIL import Image, ImageDraw
from sqlalchemy import select

from momentum.agents.extensions import attach_file
from momentum.agents.loader import all_definitions
from momentum.agents.packs.registry import PackRegistry, sync_record_types
from momentum.agents.triggers import agent_ctx
from momentum.ai.tools.catalog import build_registry
from momentum.core.context import Actor, Ctx
from momentum.core.db import UnitOfWork, create_engine, create_session_factory
from momentum.core.settings import Settings
from momentum.domain.agents import service as agents
from momentum.domain.entities import service as entities
from momentum.domain.projects.models import Project
from momentum.domain.records import service as records
from momentum.domain.skills import service as skills
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace


def _page() -> bytes:
    """A 612x792 'invoice' page (an image; PDF points and pixels coincide here)."""
    img = Image.new("RGB", (612, 792), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 40), "ACME LTD", fill="black")
    d.text((450, 44), "INV-0041", fill="black")
    d.text((40, 300), "Widgets", fill="black")
    d.text((480, 302), "60.00", fill="black")
    d.text((40, 320), "Gadgets", fill="black")
    d.text((480, 322), "40.00", fill="black")
    d.text((400, 704), "Total 100.00 USD", fill="black")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


async def main() -> None:
    settings = Settings()
    if not settings.database_url.rsplit("/", 1)[-1].endswith("_e2e"):
        sys.exit("refusing: E2E records only go into a database whose name ends in _e2e")
    if not settings.test_packs:
        sys.exit("refusing: set MOMENTUM_TEST_PACKS=true (the Echo test pack makes the records)")
    engine = create_engine(settings)
    sf = create_session_factory(engine)
    packs = PackRegistry.load(settings)
    async with sf() as session:
        uow = UnitOfWork(session)
        async with uow.transaction() as s:
            ws = await ensure_default_workspace(s, settings)
            admin_user = await s.scalar(select(User).where(User.role == "admin").limit(1))
            assert admin_user is not None
            admin = Ctx(
                actor=Actor(
                    id=admin_user.id,
                    workspace_id=ws.id,
                    role=admin_user.role,
                    email=admin_user.email,
                    name=admin_user.name,
                ),
                settings=settings,
            )
            results = await agents.install_definitions(
                s, admin, all_definitions((), packs), build_registry().names
            )
            await sync_record_types(s, ws.id, packs, settings)
            echo = next(r.agent for r in results if r.agent.key == "echo")
            project = await s.scalar(select(Project).where(Project.name == "Website Revamp"))
            assert project is not None
            await agents.add_to_project(s, admin, echo.id, project.id, "editor")
            task = await s.scalar(
                select(Task)
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(TaskProject.project_id == project.id, Task.parent_id.is_(None))
                .order_by(Task.number)
                .limit(1)
            )
            assert task is not None
            account = await s.get(User, echo.user_id)
            assert account is not None
            project_id, task_id = project.id, task.id
        bot = agent_ctx(echo, account, settings)
        impl = packs.packs["echo"].record_type("echo_bill")
        vendor_type = packs.packs["echo"].entity_type("echo_vendor")
        async with uow.transaction() as s:
            att = await attach_file(
                s, admin, settings, task_id, "acme-inv-0041.png", _page(), "image/png"
            )
            vendor = await entities.create_entity(
                s, bot, vendor_type, pack_key="echo", name="Acme Ltd", aliases=["ACME Limited"]
            )
            await records.create_record(
                s,
                bot,
                impl,
                project_id=project_id,
                task_id=task_id,
                data={
                    "vendor": {"name": "Acme Ltd", "entity_id": str(vendor.id)},
                    "number": "INV-0041",
                    "total": "100.00",
                    "currency": "USD",
                    "dated": "2026-09-15",
                    "lines": [
                        {"description": "Widgets", "amount": "60.00"},
                        {"description": "Gadgets", "amount": "40.00"},
                    ],
                },
                provenance={
                    "number": {
                        "method": "text",
                        "page": 1,
                        "bbox": [448, 40, 520, 56],
                        "confidence": 0.98,
                    },
                    "total": {
                        "method": "text",
                        "page": 1,
                        "bbox": [398, 700, 520, 716],
                        "confidence": 0.95,
                    },
                    "lines[0].amount": {"method": "table", "page": 1, "bbox": [478, 298, 520, 314]},
                    "lines[1].amount": {"method": "table", "page": 1, "bbox": [478, 318, 520, 334]},
                },
                source_attachment_id=att,
                status="needs_review",
            )
            await records.create_record(
                s,
                bot,
                impl,
                project_id=project_id,
                data={
                    "vendor": {"name": "Globex Print"},
                    "number": "G-7",
                    "total": "450.50",
                    "currency": "USD",
                    "dated": "2026-10-04",
                    "lines": [],
                },
                status="ready",
            )
            await skills.propose(
                s,
                bot,
                pack_key="echo",
                scope_type="entity",
                scope_id=vendor.id,
                kind="hint",
                field="number",
                content={
                    "text": "This vendor prints the invoice number at the top right, after Ref."
                },
                provenance={"task_id": str(task_id), "ops_summary": "number corrected"},
            )
    await engine.dispose()
    print("seeded e2e records")


if __name__ == "__main__":
    os.environ.setdefault("MOMENTUM_TEST_PACKS", "true")
    from momentum.cli import run_async  # a selector event loop on Windows (async psycopg)

    run_async(main())
