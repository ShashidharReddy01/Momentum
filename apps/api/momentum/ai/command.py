"""⌘K natural-language commands (S3.2.2): "assign all overdue tasks in Website Revamp to Ana".

The model finds the targets with read tools and previews the change with write tools
(``ai/loop.py``); the previews become one ``ai_actions`` row shown as a PreviewCard. Nothing is
applied here unless the user turned on "apply low-risk changes without asking" and the action is
low risk. An ambiguous request ends with a question and the candidates, never a guess (J7 AC).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context import Screen, screen_ctx, system_base, user_ctx
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.loop import Emit, emit_proposals, run_tool_loop
from momentum.ai.memory import memory_for
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.context import Ctx
from momentum.domain.workspace.models import Workspace

MAX_STEPS = 6


async def run_command(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    registry: ToolRegistry,
    text: str,
    *,
    screen: Screen,
    now: datetime,
    emit: Emit,
) -> None:
    prompt = prompts.load("command")
    ws = await session.get(Workspace, ctx.workspace_id)
    memory = await memory_for(session, ctx, project_id=screen.project_id)
    system = "\n\n".join(
        [
            system_base(ctx, workspace_name=ws.name if ws else "", memory=memory, now=now).text,
            prompt.body,
            (await user_ctx(session, ctx, now=now)).text,
            (await screen_ctx(session, ctx, screen)).text,
        ]
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f'<data source="command">{safe(text)}</data>'},
    ]
    result = await run_tool_loop(
        session,
        llm,
        ctx,
        registry,
        messages=messages,
        feature="command",
        alias=prompt.alias,
        emit=emit,
        max_steps=MAX_STEPS,
        prompt_version=prompt.version,
        max_tokens=prompt.max_tokens,
    )
    if result.text:
        await emit("token", {"text": result.text})
    await emit_proposals(session, ctx, registry, result, emit, source="command")
    await emit("done", {"steps": result.steps})
