"""S3.1.4 Embeddings + hybrid retrieval: chunking, hash-skipping indexing, the outbox consumer,
RRF, optional rerank, the semantic_search tool, and the two ACs: a paraphrase finds the right
task, and private content never reaches a non-member."""

from __future__ import annotations

import itertools
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai import retrieval
from momentum.ai.embeddings import chunk, index_changes, index_entity, reindex
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.mock import MockTransport
from momentum.ai.models import Embedding, LlmCall
from momentum.ai.transport import GatewayTransport
from momentum.ai.types import EmbedRequest, RawEmbedding, RerankRequest
from momentum.ai.usage import DbUsageLog, NullUsageLog
from momentum.core.db import UnitOfWork
from momentum.core.events import ConsumerOffset
from momentum.core.settings import Settings
from momentum.domain.comments.service import create_comment, delete_comment
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import REG, World, world
from tests.conftest import make_settings

_ = world


class CountingMock(MockTransport):
    """The mock gateway, counting embed calls; can be told to fail."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.embedded: list[str] = []
        self.fail = False

    async def embed(self, req: EmbedRequest) -> RawEmbedding:
        if self.fail:
            from momentum.ai.errors import TransportError

            raise TransportError("server_error", "gateway down")
        self.embedded += req.texts
        return await super().embed(req)


@pytest.fixture
async def llm(settings: Settings) -> AsyncIterator[LLM]:
    s = settings.model_copy(update={"llm_max_retries": 0})
    gateway = LLM(s, CountingMock(s), NullUsageLog())
    yield gateway
    await gateway.aclose()


def counting(llm: LLM) -> CountingMock:
    assert isinstance(llm.transport, CountingMock)
    return llm.transport


def doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def rows(uow: UnitOfWork, entity_id: uuid.UUID) -> list[Embedding]:
    async with uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(Embedding)
                    .where(Embedding.entity_id == entity_id)
                    .order_by(Embedding.chunk_no)
                )
            ).scalars()
        )


# ---------------- chunking ----------------


def test_chunks_overlap_and_never_cut_words() -> None:
    assert chunk("") == [] and chunk("   ") == []
    assert chunk("short text") == ["short text"]
    words = [f"word{i:04d}" for i in range(600)]  # ~5,400 characters
    parts = chunk(" ".join(words), size=1400, overlap=200)
    assert len(parts) > 3
    assert all(len(p) <= 1400 for p in parts)
    assert all(set(p.split()) <= set(words) for p in parts)  # whole words only
    for a, b in itertools.pairwise(parts):
        aw, bw = a.split(), b.split()
        start = aw.index(bw[0])  # the next chunk starts inside this one...
        assert aw[start:] == bw[: len(aw) - start]  # ...and repeats its tail
        assert 0 < len(" ".join(aw[start:])) <= 200  # by about the overlap
    joined = set(" ".join(parts).split())
    assert joined == set(words)  # nothing lost
    assert chunk("x" * 3000, size=1400) == ["x" * 1400]  # an over-long word is cut, once


# ---------------- indexing ----------------


async def test_index_entity_skips_unchanged_content(
    uow: UnitOfWork, world: World, llm: LLM
) -> None:
    async with uow.transaction() as s:
        n = await index_entity(s, llm, "task", world.copy.id)
    assert n == 1
    (row,) = await rows(uow, world.copy.id)
    assert row.text == "Draft pricing copy" and row.dim == 1024 and len(row.embedding) == 1024
    assert counting(llm).embedded == ["Draft pricing copy"]

    async with uow.transaction() as s:
        assert await index_entity(s, llm, "task", world.copy.id) == 0  # same hash: no call
    assert counting(llm).embedded == ["Draft pricing copy"]

    async with uow.transaction() as s:
        await tasks.update_task(
            s, world.ravi, world.copy.id, {"description": doc("Ana writes the words.")}
        )
        assert await index_entity(s, llm, "task", world.copy.id) == 1
    (row,) = await rows(uow, world.copy.id)
    assert row.text == "Draft pricing copy Ana writes the words."  # whitespace normalized

    async with uow.transaction() as s:
        await tasks.delete_task(s, world.ravi, world.copy.id)
        assert await index_entity(s, llm, "task", world.copy.id) == 0
    assert await rows(uow, world.copy.id) == []  # gone content leaves the index


async def test_outbox_consumer_indexes_changes_and_resumes_after_failure(
    uow: UnitOfWork, world: World, llm: LLM
) -> None:
    async with uow.transaction() as s:
        first = await index_changes(s, llm)
    assert first.entities >= 3  # the fixture's tasks/projects (everything since the start)
    async with uow.transaction() as s:
        assert (await index_changes(s, llm)).events == 0  # cursor advanced

    async with uow.transaction() as s:
        new = (await tasks.create_task(s, world.ana, world.project.id, "Book the venue")).entity[0]
        c = await create_comment(s, world.ana, world.faq.id, doc("Venue shortlist attached"))
    counting(llm).fail = True
    async with uow.transaction() as s:
        run = await index_changes(s, llm)
    assert run.stopped == "server_error" and run.entities == 0
    assert await rows(uow, new.id) == []
    counting(llm).fail = False
    async with uow.transaction() as s:
        run = await index_changes(s, llm)  # retried, nothing skipped
    assert run.stopped is None
    assert [r.text for r in await rows(uow, new.id)] == ["Book the venue"]
    assert [r.text for r in await rows(uow, c.entity.id)] == [
        "Comment on Draft pricing FAQ: Venue shortlist attached"
    ]
    async with uow.transaction() as s:
        cursor = await s.get(ConsumerOffset, "embeddings")
        assert cursor is not None and cursor.last_event_id > 0

    async with uow.transaction() as s:
        await delete_comment(s, world.ana, c.entity.id)
        await index_changes(s, llm)
    assert await rows(uow, c.entity.id) == []


async def test_reindex_command_rebuilds_by_type(uow: UnitOfWork, world: World, llm: LLM) -> None:
    async with uow.transaction() as s:
        run = await reindex(s, llm, entity_types=["project"])
    assert run.entities >= 3 and run.chunks >= 3
    async with uow.transaction() as s:
        again = await reindex(s, llm, entity_types=["project"])
    assert again.chunks == 0  # unchanged: nothing re-embedded


# ---------------- search ----------------


async def _index(uow: UnitOfWork, llm: LLM, items: list[tuple[str, uuid.UUID]]) -> None:
    async with uow.transaction() as s:
        for kind, eid in items:
            await index_entity(s, llm, kind, eid)


async def test_paraphrase_finds_the_right_task(uow: UnitOfWork, world: World, llm: LLM) -> None:
    """AC: a question that shares no exact phrase with the task still finds it (the vector half),
    ranked above lexically closer distractors."""
    async with uow.transaction() as s:
        await tasks.update_task(
            s,
            world.ravi,
            world.copy.id,
            {"description": doc("Ana is writing the words for the new pricing page.")},
        )
        venue = (
            await tasks.create_task(s, world.ravi, world.project.id, "Book the offsite venue")
        ).entity[0]
        login = (
            await tasks.create_task(s, world.ravi, world.project.id, "Fix the login bug on mobile")
        ).entity[0]
    await _index(
        uow,
        llm,
        [("task", world.copy.id), ("task", world.faq.id), ("task", venue.id), ("task", login.id)],
    )
    async with uow.transaction() as s:
        hits = await retrieval.search(s, llm, world.ana, "who writes text for pricing")
    assert hits[0].entity_id == world.copy.id
    assert hits[0].sources == ["vector"]  # no keyword match: this was the meaning half
    assert hits[0].citation() == f"[T-{world.copy.number}]"
    assert hits[0].project == "AI Tools Lab" and "pricing page" in hits[0].snippet
    ids = [h.entity_id for h in hits]
    assert login.id not in ids[:2]


async def test_private_content_never_reaches_non_members(
    uow: UnitOfWork, world: World, llm: LLM
) -> None:
    """AC: private project content (tasks, comments on them, subtasks) is filtered in SQL."""
    async with uow.transaction() as s:
        await tasks.update_task(
            s, world.priya, world.hidden.id, {"description": doc("Secret pricing strategy for Q4")}
        )
        note = await create_comment(s, world.priya, world.hidden.id, doc("Pricing strategy notes"))
        deep = (
            await tasks.create_subtask(s, world.ravi, world.copy.id, "Pricing strategy research")
        ).entity
        deeper = (
            await tasks.create_subtask(s, world.ravi, deep.id, "Strategy interview notes")
        ).entity
    await _index(
        uow,
        llm,
        [
            ("task", world.hidden.id),
            ("comment", note.entity.id),
            ("task", deep.id),
            ("task", deeper.id),
            ("project", world.secret.id),
        ],
    )
    async with uow.transaction() as s:
        ravi_hits = await retrieval.search(s, llm, world.ravi, "pricing strategy notes", k=15)
        priya_hits = await retrieval.search(s, llm, world.priya, "pricing strategy notes", k=15)
        tom_hits = await retrieval.search(s, llm, world.tom, "pricing strategy notes", k=15)
    private = {world.hidden.id, note.entity.id, world.secret.id}
    assert not private & {h.entity_id for h in ravi_hits}
    assert {deep.id, deeper.id} <= {h.entity_id for h in ravi_hits}  # subtasks at any depth
    assert private - {world.secret.id} <= {h.entity_id for h in priya_hits}
    assert tom_hits == []  # can't see AI Tools Lab or Secret Plans

    # the private task's exact words: a keyword match exists, and must be filtered too
    async with uow.transaction() as s:
        kw_ravi = await retrieval.search(s, llm, world.ravi, "secret pricing strategy", k=15)
        kw_priya = await retrieval.search(s, llm, world.priya, "secret pricing strategy", k=15)
    assert world.hidden.id not in {h.entity_id for h in kw_ravi}
    hit = next(h for h in kw_priya if h.entity_id == world.hidden.id)
    assert "keyword" in hit.sources

    async with uow.transaction() as s:
        await tasks.delete_task(s, world.ravi, deep.id)  # the index isn't updated yet
        hits = await retrieval.search(s, llm, world.ravi, "pricing strategy notes", k=15)
    assert not {deep.id, deeper.id} & {h.entity_id for h in hits}  # deleted: filtered anyway


def test_reciprocal_rank_fusion() -> None:
    a, b, c = (("task", uuid.UUID(int=i)) for i in (1, 2, 3))
    fused = retrieval.fuse([a, b], [b, c])
    assert [k for k, _ in fused] == [b, a, c]  # in both lists beats first in one
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


async def test_optional_rerank_orders_candidates_and_is_logged(
    uow: UnitOfWork,
    world: World,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    s_on = settings.model_copy(update={"ai_rerank": True})
    llm = LLM(s_on, MockTransport(s_on), DbUsageLog(session_factory, 0))
    async with uow.transaction() as s:
        venue = (
            await tasks.create_task(s, world.ravi, world.project.id, "Book the offsite venue")
        ).entity[0]
    await _index(uow, llm, [("task", world.copy.id), ("task", world.faq.id), ("task", venue.id)])
    async with uow.transaction() as s:
        hits = await retrieval.search(s, llm, world.ravi, "offsite venue booking", k=2)
    assert len(hits) == 2 and hits[0].entity_id == venue.id
    async with uow.transaction() as s:
        aliases = set((await s.execute(select(LlmCall.alias, LlmCall.feature))).all())
    assert ("rerank", "retrieval:rerank") in aliases and ("embed", "retrieval") in aliases
    await llm.aclose()


async def test_semantic_search_tool(uow: UnitOfWork, world: World, llm: LLM) -> None:
    await _index(uow, llm, [("task", world.copy.id), ("task", world.faq.id)])
    async with uow.transaction() as s:
        out = await REG.invoke(s, world.ana, "semantic_search", {"query": "pricing copy"}, llm=llm)
    assert out.ok
    first = out.result.data["results"][0]
    assert first["cite"] == f"[T-{world.copy.number}]" and first["type"] == "task"
    async with uow.transaction() as s:
        out = await REG.invoke(s, world.ana, "semantic_search", {"query": "pricing"})
    assert out.result.error["code"] == "unavailable"  # type: ignore[index]


# ---------------- gateway rerank ----------------


async def test_gateway_rerank_request_and_bad_responses() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        import json

        body = json.loads(request.content)
        seen.append({"path": request.url.path, **body})
        if body["query"] == "bad":
            return httpx2.Response(200, json={"results": [{"index": 9, "relevance_score": 1}]})
        return httpx2.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            },
        )

    s = make_settings(
        llm_mode="gateway",
        llm_base_url="http://gateway.test/v1",
        llm_api_key="k",
        llm_rerank_model="provider/rerank",
        llm_max_retries=0,
    )
    t = GatewayTransport(s, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    raw = await t.rerank(RerankRequest("f", "provider/rerank", "q", ["a", "b"], 2))
    assert raw.ranking == [(1, 0.9), (0, 0.2)]
    assert seen[0] == {
        "path": "/v1/rerank",
        "model": "provider/rerank",
        "query": "q",
        "documents": ["a", "b"],
        "top_n": 2,
    }
    from momentum.ai.errors import TransportError

    with pytest.raises(TransportError) as err:
        await t.rerank(RerankRequest("f", "provider/rerank", "bad", ["a", "b"], 2))
    assert err.value.kind == "bad_response"
    llm = LLM(s, t, NullUsageLog())
    from momentum.core.context import Actor, Ctx

    ctx = Ctx(actor=Actor(id=None, workspace_id=uuid.UUID(int=0)), settings=s)
    with pytest.raises(AIUnavailable):
        await llm.rerank("bad", ["a", "b"], top_n=2, feature="f", ctx=ctx)
    await t.aclose()


def test_rerank_settings_default_off_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make_settings()
    assert s.ai_rerank is False and s.llm_rerank_model == "cohere-rerank-v3.5"
    monkeypatch.setenv("MOMENTUM_AI_RERANK", "true")
    monkeypatch.setenv("MOMENTUM_LLM_RERANK_MODEL", "@cfg/rerank-v3.5")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.ai_rerank is True and s.llm_rerank_model == "@cfg/rerank-v3.5"
