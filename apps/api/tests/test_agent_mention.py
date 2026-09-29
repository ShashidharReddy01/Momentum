"""S5.2.2: @mentioning an agent. The mention picker offers the agents that answer mentions; a
mention (in a new comment or added by an edit) runs the agent with the thread as context; the
reply lands in the thread and @mentions the person who asked."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from momentum.ai.tools.write_tools import text_doc
from momentum.core.context import Ctx
from momentum.domain.agents import service
from momentum.domain.comments.service import create_comment, edit_comment
from tests.ai_fixtures import world
from tests.helpers import Clients, ctx_for
from tests.test_agent_runtime import TOOLS, Env, _comments, _defn, make_env

_ = (make_env, world)


def _mention_doc(env: Env, text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "mention",
                        "attrs": {
                            "id": str(env.account.id),
                            "label": env.agent.name,
                            "kind": "user",
                        },
                    },
                    {"type": "text", "text": f" {text}"},
                ],
            }
        ],
    }


async def _comment(env: Env, who: Ctx, doc: dict[str, Any]) -> Any:
    async with env.uow.transaction() as s:
        return (await create_comment(s, who, env.world.copy.id, doc)).entity


async def test_the_mention_picker_offers_agents_that_answer_mentions(
    make_env: Callable[..., Env], as_user: Clients
) -> None:
    env = make_env()
    helper = await env.install(_defn())
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:  # an agent that doesn't answer mentions
        await service.install_definitions(
            s,
            admin,
            [(_defn(key="quiet", name="Quiet Helper", triggers=[{"type": "manual"}]), "host")],
            TOOLS,
        )
    ravi = await as_user("ravi")
    users = (await ravi.get("/api/v1/mentions/search?q=help")).json()["users"]
    assert [(u["name"], u["is_agent"]) for u in users] == [(helper.name, True)]
    people = (await ravi.get("/api/v1/mentions/search?q=ana")).json()["users"]
    assert people and not any(u["is_agent"] for u in people)


async def test_a_mention_gets_a_reply_in_the_thread_with_the_thread_as_context(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(_defn())
    env.script(
        [
            # the earlier comment is in what the agent sees, so it can answer from it
            {
                "match": {"contains": "Launch moved to Friday", "turn": 1},
                "text": "(mock) The thread says launch moved to Friday.",
            },
        ]
    )
    await _comment(env, env.world.ana, text_doc("Launch moved to Friday."))
    await _comment(env, env.world.ravi, _mention_doc(env, "when is launch?"))
    assert await env.events() == 1
    assert await env.drain() == ["succeeded"]
    *_, reply = await _comments(env, env.world.copy.id)
    assert reply.author_id == env.account.id and reply.is_ai
    first = reply.body["content"][0]["content"]
    assert first[0]["type"] == "mention"
    assert first[0]["attrs"]["id"] == str(env.world.ravi.actor.id)  # the person who asked
    assert "moved to Friday" in first[-1]["text"]
    # the task isn't handed anywhere: only an assignment is handed back
    [run] = await env.runs()
    assert run.trigger["type"] == "mentioned" and "handoff" not in (run.output or {})


async def test_a_mention_added_by_an_edit_runs_once(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_defn())
    env.script([{"match": {"contains": "mentioned you", "turn": 1}, "text": "(mock) On it."}])
    comment = await _comment(env, env.world.ravi, text_doc("Can someone check the copy?"))
    assert await env.events() == 0
    async with env.uow.transaction() as s:
        await edit_comment(s, env.world.ravi, comment.id, _mention_doc(env, "can you check it?"))
    assert await env.events() == 1
    assert await env.drain() == ["succeeded"]
    async with env.uow.transaction() as s:  # editing it again doesn't ask again
        await edit_comment(s, env.world.ravi, comment.id, _mention_doc(env, "can you check it??"))
    assert await env.events() == 0
    assert len(await env.runs()) == 1
