"""Bernie's job (spec §9.3): gather → ingest → (a batch: one child job per invoice, each on its own
subtask, then a summary and the catalogue) → per invoice: duplicate file → e-invoice? → read
(text → OCR → vision) → vendor → skills → extract → locate → math checks → critic → investigator
→ ask about a gap → risk checks → confidence → policy → record → outputs. Waiting for the
approval (or a hold's answer) is its own small job (`decide.py`), so a batch's summary and
catalogue don't wait for every approval.

Every model call and every effect is a recorded step, so a job that's interrupted resumes where
it was. Document bytes are never stored in a step: a split-out or unpacked document is attached
to the task (source "agent") and every later step reads it by its file id."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from momentum.sdk import Job, StepFailed, step
from momentum_pack_bernie import (
    ask_gap,
    confidence,
    critic,
    einvoice,
    extract,
    ingest,
    investigate,
    outputs,
    policy,
    read,
    vendors,
)
from momentum_pack_bernie.checks_math import check, dec, math_checks
from momentum_pack_bernie.locate import find_amount, locate
from momentum_pack_bernie.risk import instruction_check, risk_checks


class DocRef(BaseModel):
    file_id: uuid.UUID
    name: str
    mime: str
    sha256: str
    page_count: int
    vendor_hint: str | None = None
    parent: str | None = None
    page_range: tuple[int, int] | None = None


class Ingest(BaseModel):
    documents: list[DocRef]
    skipped: list[dict[str, str]]


Checks = list[dict[str, Any]]


def _blocking(checks: Checks) -> Checks:
    return [c for c in checks if not c["passed"] and c["severity"] == "block"]


# ---------------------------------------------------------------- the job


async def run(job: Job) -> dict[str, Any]:
    settings = await job.settings()
    if job.input.get("file_id"):  # a child job: one document of a batch
        doc = DocRef.model_validate(job.input["document"])
        return await process(job, settings, doc)
    if job.task_id is None:
        return {"status": "no_task", "documents": []}
    files = [f for f in await job.files.list("files") if f.source != "agent"]
    if not files:
        await job.step(
            "no_files",
            _comment,
            job,
            "I couldn't find an invoice file on this task. Attach the invoice (PDF, image, zip "
            "or e-invoice XML) and assign it to me again.",
        )
        return {"status": "no_files", "documents": []}

    found = await job.step("ingest", _ingest, job, [f.model_dump(mode="json") for f in files])
    docs = [
        d for d in found.documents if d.page_count <= settings.max_pages or d.mime != ingest.PDF
    ]
    too_big = [d for d in found.documents if d not in docs]
    skipped = found.skipped + [
        {
            "file": d.name,
            "reason": f"{d.page_count} pages is more than {settings.max_pages}; "
            "split it and attach the parts",
        }
        for d in too_big
    ]
    if not docs:
        await job.step("nothing_to_read", _comment, job, _skipped_text(skipped))
        return {"status": "nothing_to_read", "documents": [], "skipped": skipped}
    if len(docs) == 1:
        out = await process(job, settings, docs[0])
        rows = out.get("parts") or [out]
        day = (await job.now("catalogue_day")).date().isoformat()
        files_out = await job.step("catalogue", _catalogue, job, rows, day)
        if skipped:
            await job.step("skipped_note", _comment, job, _skipped_text(skipped))
        return {"status": "done", "documents": rows, "skipped": skipped, "catalogue": files_out}

    children = []
    for i, d in enumerate(docs, start=1):
        children.append(
            await job.spawn(
                "extract_invoice",
                {"file_id": str(d.file_id), "document": d.model_dump(mode="json")},
                title=f"Invoice {i} of {len(docs)}: {d.name}",
                key=f"doc{i}",
            )
        )
    results = await job.gather(children, key="invoices")
    rows = [
        r.output
        if r.ok and isinstance(r.output, dict)
        else {"status": "failed", "error": r.error, "file": d.name}
        for r, d in zip(results, docs, strict=True)
    ]
    rows = [x for r in rows for x in (r.get("parts") or [r])]  # a re-split invoice's parts
    day = (await job.now("catalogue_day")).date().isoformat()
    files_out = await job.step("catalogue", _catalogue, job, rows, day)
    await job.step("summary", _comment, job, _summary(rows, skipped, files_out))
    return {"status": "done", "documents": rows, "skipped": skipped, "catalogue": files_out}


# ---------------------------------------------------------------- steps


@step
async def _comment(job: Job, text: str) -> None:
    if job.task_id is not None:
        await job.effects.comments.create(job.task_id, text)


@step
async def _ingest(job: Job, files: list[dict[str, Any]]) -> Ingest:
    """Unpack and split; any document that isn't exactly an attached file is attached to the
    task (so it can be read, reviewed and downloaded), and referred to by its file id after."""
    originals: dict[str, uuid.UUID] = {}
    raw: list[tuple[str, bytes]] = []
    for f in files:
        data = await job.files.read(uuid.UUID(f["id"]))
        raw.append((f["filename"], data))
        originals[ingest.sha256(data)] = uuid.UUID(f["id"])
    got = ingest.ingest(raw)
    refs: list[DocRef] = []
    for d in got.documents:
        file_id = originals.get(d.sha256)
        if file_id is None:
            assert job.task_id is not None
            file_id = await job.effects.attachments.create(
                job.task_id, d.name.rsplit("/", 1)[-1], d.data, d.mime
            )
        refs.append(
            DocRef(
                file_id=file_id,
                name=d.name,
                mime=d.mime,
                sha256=d.sha256,
                page_count=d.page_count,
                vendor_hint=d.vendor_hint,
                parent=d.parent,
                page_range=d.page_range,
            )
        )
    return Ingest(documents=refs, skipped=got.skipped)


@step
async def _split(job: Job, doc: DocRef, pages: tuple[int, int]) -> list[DocRef]:
    """A person said pages a-b are a separate invoice: both parts attached, as documents."""
    assert job.task_id is not None
    data = await job.files.read(doc.file_id)
    a, b = pages
    ranges = [r for r in ((1, a - 1), (a, b), (b + 1, doc.page_count)) if r[0] <= r[1]]
    out: list[DocRef] = []
    stem = doc.name.rsplit(".", 1)[0]
    for (lo, hi), part in zip(ranges, ingest.split_pdf(data, ranges), strict=True):
        name = f"{stem} (pages {lo}-{hi}).pdf"
        fid = await job.effects.attachments.create(job.task_id, name, part, ingest.PDF)
        out.append(
            DocRef(
                file_id=fid,
                name=name,
                mime=ingest.PDF,
                sha256=ingest.sha256(part),
                page_count=hi - lo + 1,
                vendor_hint=doc.vendor_hint,
                parent=doc.name,
                page_range=(lo, hi),
            )
        )
    return out


@step
async def _einvoice(job: Job, doc: DocRef) -> dict[str, Any] | None:
    data = await job.files.read(doc.file_id)
    xml = (
        data
        if doc.mime == "application/xml"
        else einvoice.embedded_xml(data)
        if doc.mime == ingest.PDF
        else None
    )
    if not xml or (doc.mime == "application/xml" and not einvoice.is_einvoice_xml(xml)):
        return None
    return einvoice.parse(xml)


@step
async def _read(job: Job, doc: DocRef, use_ocr: bool) -> read.Reading:
    data = await job.files.read(doc.file_id)
    if doc.mime == ingest.PDF:
        return read.read_pdf(job, data, use_ocr=use_ocr)
    return read.read_image(job, data, use_ocr=use_ocr)


@step
async def _images(job: Job, doc: DocRef, pages: list[int]) -> list[str]:
    """The given (vision) pages as JPEGs for the model, base64."""
    data = await job.files.read(doc.file_id)
    if doc.mime == ingest.PDF:
        return [base64.b64encode(job.render_page(data, n).jpeg).decode() for n in pages]
    return [base64.b64encode(job.render_image(data).jpeg).decode()]


@step
async def _new_vendor(
    job: Job, name: str, tax_id: str | None, country: str | None, hint: str | None
) -> str:
    attributes: dict[str, Any] = {
        "tax_ids": [tax_id] if tax_id else [],
        "folder_names": [hint] if hint else [],
    }
    if country:
        attributes["country"] = country
    return str(await job.effects.entities.create("vendor", name, attributes=attributes))


@step
async def _bank(job: Job, entity_id: str, account: str) -> dict[str, Any]:
    seen = await job.effects.entities.set_bank(uuid.UUID(entity_id), account)
    return seen.model_dump(mode="json")


@step
async def _record(
    job: Job,
    doc: DocRef,
    data: dict[str, Any],
    prov: dict[str, Any],
    checks: Checks,
    confidence_: float,
    status: str,
    decision: dict[str, Any],
) -> str:
    rid = await job.effects.records.create(
        "invoice",
        data,
        task_id=job.task_id,
        provenance=prov,
        checks=checks,
        decision=decision,
        confidence=confidence_,
        status=status,
        source_attachment_id=doc.file_id,
        source_sha256=doc.sha256,
        source_locator=f"pages {doc.page_range[0]}-{doc.page_range[1]} of {doc.parent}"
        if doc.page_range
        else None,
    )
    return str(rid)


@step
async def _approve_by_policy(job: Job, record_id: str) -> None:
    [rec] = await job.records.load([uuid.UUID(record_id)])
    await job.effects.records.update(
        uuid.UUID(record_id),
        [{"op": "set_status", "status": "approved", "reason": "Allowed by Bernie's policy"}],
        expected_version=rec.version,
        authority="policy",
    )


@step
async def _task_outputs(
    job: Job, data: dict[str, Any], status: str, rename: bool, fields: bool
) -> dict[str, Any]:
    assert job.task_id is not None
    done: dict[str, Any] = {"renamed": False, "fields": [], "moved": False}
    if fields:
        done["fields"] = await job.effects.tasks.set_fields(
            job.task_id, outputs.task_fields(data, status), skip_missing=True
        )
    if rename:
        await job.effects.tasks.rename(job.task_id, outputs.task_title(data))
        done["renamed"] = True
    if status == "needs_review":
        done["moved"] = await job.effects.tasks.move_to_review(job.task_id)
    return done


@step
async def _request_approval(job: Job, data: dict[str, Any], description: str, approver: str) -> str:
    assert job.task_id is not None
    tid = await job.effects.tasks.request_approval(
        job.task_id,
        outputs.approval_title(data),
        approver_id=uuid.UUID(approver),
        description=description,
    )
    return str(tid)


@step
async def _catalogue(job: Job, rows: list[dict[str, Any]], day: str) -> dict[str, Any]:
    """The batch's catalogue, attached to the task: `invoices-<date>.xlsx` (the records_export
    sheets: header and lines) and `.csv` in the notebook's column order."""
    assert job.task_id is not None
    ids = [uuid.UUID(r["record_id"]) for r in rows if r.get("record_id")]
    if not ids:
        return {
            "excluded": [{"document": r.get("file") or "?", "reason": "no record"} for r in rows]
        }
    xlsx = await job.records.export(ids, title=f"Invoices {day}", fmt="xlsx")
    recs = {str(r.id): r for r in await job.records.load(ids)}
    data_rows = [
        {**r, "data": recs[r["record_id"]].data, "status": recs[r["record_id"]].status}
        if r.get("record_id") in recs
        else r
        for r in rows
    ]
    csv_text, excluded = outputs.catalogue_csv(data_rows)
    sheet = await job.effects.attachments.create(
        job.task_id,
        f"invoices-{day}.xlsx",
        xlsx,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    csv_id = await job.effects.attachments.create(
        job.task_id, f"invoices-{day}.csv", csv_text.encode("utf-8"), "text/csv"
    )
    return {"xlsx": str(sheet), "csv": str(csv_id), "excluded": excluded}


# ---------------------------------------------------------------- one invoice


async def process(job: Job, settings: Any, doc: DocRef) -> dict[str, Any]:
    earlier = await job.records.by_source("same_file", doc.sha256)
    xml_data = (
        await job.step("einvoice", _einvoice, job, doc)
        if doc.mime in (ingest.PDF, "application/xml")
        else None
    )
    reading = read.Reading(pages=[])
    if doc.mime != "application/xml":
        reading = await job.step("read", _read, job, doc, bool(settings.ocr))
    page_one = reading.pages[0].text if reading.pages else ""

    # vendor (deterministic signals first; a closed-list model call only when they don't decide)
    known = await job.entities.list("vendors", "vendor")
    rec = vendors.recognise(page_one, doc.vendor_hint, known)
    entity_id = rec.entity_id
    if entity_id is None and page_one.strip():
        pool = [e for e in known if str(e.id) in rec.candidates] or vendors.candidates_for_model(
            page_one, known
        )
        if pool:
            prompt = job.prompts.load("bernie_vendor")
            try:
                choice = await job.llm.json(
                    "vendor",
                    vendors.VendorChoice,
                    messages=[
                        {"role": "system", "content": prompt.body},
                        {"role": "user", "content": vendors.model_prompt(page_one, pool)},
                    ],
                    alias=prompt.alias,
                    max_tokens=prompt.max_tokens,
                    prompt_version=prompt.version,
                )
            except StepFailed:  # as the notebook: a failed guess means "new vendor"
                choice = vendors.VendorChoice(vendor_id="new")
            if any(str(e.id) == choice.vendor_id for e in pool):
                entity_id = choice.vendor_id
    skills = await job.skills.for_("skills", entity_id=uuid.UUID(entity_id) if entity_id else None)

    # the invoice's data
    model_confidence = 1.0
    merged: extract.Extracted | None = None
    method = "einvoice"
    chunk_count = 0
    alias = "default"
    images: list[bytes] = []
    if xml_data is not None:
        account = xml_data.pop("_bank_account", None)
        data = dict(xml_data)
        data.setdefault("tax_lines", [])
        data["extraction"] = {
            "method": "einvoice",
            "pages": len(reading.pages),
            "text_pages": reading.text_pages,
            "ocr_pages": reading.ocr_pages,
            "vision_pages": reading.vision_pages,
            "chunks": 0,
            "attempts": 0,
            "model_alias": None,
            "text_confidence": reading.confidence or None,
        }
        data["notes"] = ["Read from the embedded e-invoice XML (no model call)."]
        data["vendor"]["entity_id"] = entity_id
    else:
        method, groups = extract.plan(reading)
        base = job.prompts.load("bernie_extract")
        alias = base.alias
        system = base.body
        if method == "chunked" or len(groups) > 1:
            system = base.body + "\n\n" + job.prompts.load("bernie_extract_chunk").body
        results: list[extract.Extracted] = []
        for k, pages in enumerate(groups, start=1):
            vision_here = [n for n in pages if n in reading.vision_pages]
            imgs = (
                [
                    base64.b64decode(b)
                    for b in await job.step(f"images_{k}", _images, job, doc, vision_here)
                ]
                if vision_here
                else []
            )
            images += imgs
            results.append(
                await job.llm.json(
                    f"extract_{k}",
                    extract.Extracted,
                    messages=[
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": extract.user_content(
                                reading, pages, skills, imgs, slice_of=len(reading.pages)
                            ),
                        },
                    ],
                    alias=base.alias,
                    max_tokens=base.max_tokens,
                    prompt_version=base.version,
                )
            )
            if len(groups) > 1:
                await job.progress(k, len(groups), "page groups")
        merged = extract.merge(results)
        chunk_count = len(results)
        model_confidence = merged.confidence
        account = merged.bank_account
        data = extract.to_record(
            merged,
            method=method,
            reading=reading,
            chunk_count=chunk_count,
            vendor_entity_id=entity_id,
            vendor_name=None,
            model_alias=base.alias,
        )

    # the vendor entity: matched now by name or tax id, or created
    entity = next((e for e in known if str(e.id) == entity_id), None)
    if entity_id is None:
        v = data["vendor"]
        m = await job.entities.match(
            "vendor_match", "vendor", v.get("name_as_printed") or v["name"], tax_id=v.get("tax_id")
        )
        if m.entity_id is not None:
            entity_id = str(m.entity_id)
            entity = next((e for e in known if e.id == m.entity_id), None)
        elif v.get("name") and v["name"] != "Unknown vendor":
            entity_id = await job.step(
                "new_vendor",
                _new_vendor,
                job,
                v["name"],
                v.get("tax_id"),
                v.get("country"),
                doc.vendor_hint,
            )
        data["vendor"]["entity_id"] = entity_id
    if entity is not None:
        data["vendor"]["name"] = entity.name
    vendor_is_new = entity is None or not int((entity.profile or {}).get("invoices") or 0)
    had_bank = bool(((entity.attributes if entity else None) or {}).get("bank") or None)
    bank_seen: dict[str, Any] | None = None
    if account and entity_id is not None:
        bank_seen = await job.step("bank", _bank, job, entity_id, account)
        data["bank"] = {**(data.get("bank") or {}), "last4": bank_seen.get("last4")}

    # where each value is printed, and the arithmetic
    tolerance = bool(settings.rounding_tolerance)

    def checks_for(d: dict[str, Any]) -> tuple[dict[str, Any], Checks]:
        prov_, rows = locate(d, reading)
        return prov_, math_checks(d, rounding_tolerance=tolerance) + rows

    def rebuild(ex: extract.Extracted) -> dict[str, Any]:
        """A corrected extraction as this invoice's data (its vendor and bank kept)."""
        d = extract.to_record(
            ex,
            method=method,
            reading=reading,
            chunk_count=chunk_count,
            vendor_entity_id=entity_id,
            vendor_name=None,
            model_alias=alias,
        )
        d["vendor"] = data["vendor"]
        if "bank" in data:
            d["bank"] = data["bank"]
        return d

    def recheck(ex: extract.Extracted) -> Checks:
        return checks_for(rebuild(ex))[1]

    prov, checks = checks_for(data)
    tried: list[str] = []
    attempts = steps_used = 0
    if merged is not None and _blocking(checks):
        merged, attempts, notes = await _criticise(
            job, reading, merged, checks, skills, images, recheck
        )
        tried += notes
        data = rebuild(merged)
        prov, checks = checks_for(data)
    readable = any(p.source != "vision" and p.words for p in reading.pages)
    if merged is not None and _blocking(checks) and readable:
        merged, steps_used, notes = await _investigate(
            job, settings, reading, merged, checks, recheck
        )
        tried += notes
        data = rebuild(merged)
        prov, checks = checks_for(data)
    data["extraction"]["attempts"] = attempts
    data["extraction"]["investigator_steps"] = steps_used
    if tried:
        data["notes"] = [*(data.get("notes") or []), *tried][:50]

    # still failing: ask once, then go on with the answer (or to review as extracted)
    if _blocking(checks):
        answer = await _ask_gap(job, settings, doc, data, prov, _blocking(checks), tried)
        if answer.get("split"):
            return await _resplit(job, doc, answer["split"])
        if answer.get("ops"):
            data = ask_gap.apply_ops(data, answer["ops"])
            prov, checks = checks_for(data)
            for op in answer["ops"]:
                prov[op["path"]] = {"method": "human", "by": answer.get("by")}

    # the checks that don't change with the arithmetic
    extra: Checks = []
    if xml_data is not None:
        for field in (
            "invoice_number",
            "invoice_date",
            "stated_total",
            "currency",
            "subtotal",
            "tax_amount",
        ):
            if data.get(field) is not None:
                prov.setdefault(field, {}).update({"method": "einvoice", "confidence": 1.0})
        readable_pages = [p for p in reading.pages if p.source != "vision" and p.words]
        if (
            readable_pages
            and data.get("stated_total") is not None
            and not any(find_amount(p, data["stated_total"]) for p in readable_pages)
        ):
            extra.append(
                check(
                    "einvoice_mismatch",
                    False,
                    "The e-invoice and the page show the same total",
                    f"The embedded e-invoice says {data['stated_total']}, "
                    "but that total isn't printed on the page.",
                    severity="warn",
                    fields=["stated_total"],
                )
            )
    hostile = instruction_check(data.get("notes") or [], reading.text)
    if hostile is not None:
        extra.append(hostile)
    if earlier:
        extra.append(
            check(
                "duplicate_file",
                False,
                "This file hasn't been processed before",
                f"The same file already made “{earlier[0].title}” ({earlier[0].status}).",
                severity="warn",
            )
        )

    # risk (deterministic)
    duplicates = await job.records.find_duplicates("duplicates", "invoice", data)
    total = dec(data.get("stated_total"))
    issued = _iso(data.get("invoice_date"))
    similar = (
        await job.records.find_similar("similar", "invoice", data, amount=total, occurred_on=issued)
        if total is not None
        else []
    )
    dup_ids = {d.id for d in duplicates}
    similar = [s for s in similar if s.record.id not in dup_ids]
    today = (await job.now("today")).date()
    checks = (
        checks
        + extra
        + risk_checks(
            data,
            today=today,
            duplicates=duplicates,
            similar=similar,
            bank=bank_seen,
            had_bank=had_bank,
            profile=entity.profile if entity is not None else None,
        )
    )

    # confidence, policy, record
    skill_fields = {s.field for s in skills if s.field}
    overall, prov = confidence.score(
        data, prov, checks, model_confidence=model_confidence, skill_fields=skill_fields
    )
    pctx = policy.PolicyContext(
        checks=checks,
        settings=settings,
        vendor_is_new=vendor_is_new,
        amount=total,
        currency=data.get("currency"),
        confidence=overall,
        vendor=data["vendor"]["name"],
        invoice_number=data.get("invoice_number") or "",
        bank_last4_old=(bank_seen or {}).get("last4_on_file") or "?",
        bank_last4_new=(bank_seen or {}).get("last4") or "?",
    )
    decision = policy.decide(pctx).as_dict()
    verdict = decision["decision"]
    status = "needs_review" if _blocking(checks) or verdict in ("hold", "deny") else "ready"
    record_id = await job.step(
        "record", _record, job, doc, data, prov, checks, float(overall), status, decision
    )
    link = f"/records/{record_id}"

    # outputs
    shown = "hold" if verdict == "hold" else "approved" if verdict == "allow" else status
    if verdict == "allow":
        await job.step("approve", _approve_by_policy, job, record_id)
    if job.task_id is not None:
        await job.step(
            "task_outputs",
            _task_outputs,
            job,
            data,
            shown,
            bool(settings.rename_tasks) and bool(job.input.get("file_id")),
            bool(settings.set_task_fields),
        )
    approver_name: str | None = None
    if verdict == "require_human" and job.task_id is not None:
        approver = await _approver(job, settings, total, data.get("currency"))
        if approver is not None:
            description = outputs.approval_description(data, checks, decision, link)
            approval = await job.step(
                "approval", _request_approval, job, data, description, str(approver)
            )
            approver_name = "the approver"
            await job.spawn(
                "await_decision",
                {"record_id": record_id, "kind": "approval", "approval_task_id": approval},
                title="Wait for the approval",
                key="decision",
                task="same",
            )
    elif verdict == "hold" and job.task_id is not None:
        await job.spawn(
            "await_decision",
            {
                "record_id": record_id,
                "kind": "hold",
                "decision": decision,
                "entity_id": entity_id,
                "bank_last4": (bank_seen or {}).get("last4"),
            },
            title="Wait for an answer about the hold",
            key="decision",
            task="same",
        )
    await job.step(
        "comment",
        _comment,
        job,
        outputs.comment(data, checks, decision, link, status=status, approver=approver_name),
    )
    return {
        "status": "approved" if verdict == "allow" else status,
        "record_id": record_id,
        "file": doc.name,
        "vendor": data["vendor"]["name"],
        "invoice_number": data.get("invoice_number"),
        "invoice_date": data.get("invoice_date"),
        "total": data.get("stated_total"),
        "currency": data.get("currency"),
        "lines": len(data.get("lines") or []),
        "method": data["extraction"]["method"],
        "confidence": overall,
        "decision": verdict,
        "failing": [c["id"] for c in checks if not c["passed"]],
    }


def _iso(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


# ---------------------------------------------------------------- critic and investigator


async def _criticise(
    job: Job,
    reading: read.Reading,
    merged: extract.Extracted,
    checks: Checks,
    skills: list[Any],
    images: list[bytes],
    recheck: Callable[[extract.Extracted], Checks],
) -> tuple[extract.Extracted, int, list[str]]:
    """The notebook's critic: the exact failing checks, up to 3 attempts; a correction is kept
    only when it validates, every new figure is printed on the page, and it doesn't make more
    checks fail."""
    prompt = job.prompts.load("bernie_critic")
    document = extract.page_block(reading, [p.n for p in reading.pages])
    hints = extract.skills_block(skills)
    current, failing = merged, _blocking(checks)
    tried: list[str] = []
    attempt = 0
    for attempt in range(1, critic.MAX_ATTEMPTS + 1):
        text = critic.user_content(current, failing, attempt, document, hints)
        content: Any = text
        if images:
            content = [{"type": "text", "text": text}] + [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(i).decode()},
                }
                for i in images[:5]
            ]
        try:
            res = await job.llm.json(
                f"critic_{attempt}",
                critic.CriticResult,
                messages=[
                    {"role": "system", "content": prompt.body},
                    {"role": "user", "content": content},
                ],
                alias=prompt.alias,
                max_tokens=prompt.max_tokens,
                prompt_version=prompt.version,
            )
        except StepFailed:
            tried.append("A second look didn't answer.")
            break
        fixed = critic.apply(current, res)
        if fixed is None:
            tried.append(
                "A second look found nothing to correct"
                + (f" ({res.diagnosis})" if res.diagnosis else "")
                + "."
            )
            break
        ok, missing = critic.grounded(current, fixed, reading)
        if not ok:
            tried.append(
                f"A suggested correction used figures not printed on the invoice "
                f"({', '.join(missing[:5])}); not used."
            )
            continue
        now_failing = _blocking(recheck(fixed))
        if len(now_failing) > len(failing):
            tried.append("A suggested correction made more checks fail; not used.")
            continue
        current, failing = fixed, now_failing
        tried.append(f"Corrected ({res.root_cause.replace('_', ' ')}): {res.diagnosis}".strip())
        if not failing:
            break
    return current, attempt, tried


async def _investigate(
    job: Job,
    settings: Any,
    reading: read.Reading,
    current: extract.Extracted,
    checks: Checks,
    recheck: Callable[[extract.Extracted], Checks],
) -> tuple[extract.Extracted, int, list[str]]:
    """The bounded tool loop over this document only. Its fix is kept only when it makes the
    checks pass (values the tools never showed are refused in code)."""
    prompt = job.prompts.load("bernie_investigate")
    inv = investigate.Investigation(reading, current, recheck)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.body},
        {
            "role": "user",
            "content": investigate.opening(current, _blocking(checks), len(reading.pages)),
        },
    ]
    spent = Decimal(0)
    budget = Decimal(str(settings.investigate_budget_usd))
    turns = 0
    for turn in range(1, investigate.MAX_TURNS + 1):
        try:
            out = await job.llm.tools(
                f"investigate_{turn}",
                messages=messages,
                tools=investigate.TOOLS,
                alias="smart" if prompt.alias == "smart" else "default",
                max_tokens=prompt.max_tokens,
                prompt_version=prompt.version,
            )
        except StepFailed:
            break
        turns = turn
        spent += Decimal(str(out.get("cost_usd") or "0"))
        calls = out.get("tool_calls") or []
        if not calls:
            break
        messages.append(
            {
                "role": "assistant",
                "content": out.get("text") or "",
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in calls
                ],
            }
        )
        for c in calls:
            try:
                args = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": inv.run(c["name"], args if isinstance(args, dict) else {}),
                }
            )
        if inv.clean or spent >= budget:
            break
    if inv.clean:
        return inv.current, turns, [f"Investigated the page ({turns} step(s)); the fix adds up."]
    note = f"Investigated the page ({turns} step(s)) but couldn't make it add up"
    return current, turns, [note + (" within the budget." if spent >= budget else ".")]


# ---------------------------------------------------------------- asking and re-splitting


async def _ask_gap(
    job: Job,
    settings: Any,
    doc: DocRef,
    data: dict[str, Any],
    prov: dict[str, Any],
    failing: Checks,
    tried: list[str],
) -> dict[str, Any]:
    people = await job.people("requester_people", "requester")
    route = (
        "requester" if job.requested_by is not None and job.requested_by in people else "stewards"
    )
    answer = await job.ask(
        "gap",
        kind="form",
        title=ask_gap.title(data),
        body=ask_gap.body(failing, tried, data.get("currency")),
        form=ask_gap.FORM,
        evidence=ask_gap.evidence(prov, failing, str(doc.file_id)),
        route=route,
        default_on_expiry=ask_gap.DEFAULT,
        expires_in_days=float(settings.ask_expiry_days),
        remind_in_hours=24,
    )
    value = answer.value if isinstance(answer.value, dict) else {"action": ask_gap.REVIEW}
    by = str(answer.answered_by) if answer.answered_by else None
    if value.get("action") == ask_gap.SPLIT and doc.mime == ingest.PDF:
        rng = ask_gap.pages(value.get("pages"), doc.page_count)
        if rng is not None:
            return {"split": rng, "by": by}
    return {"ops": ask_gap.to_ops(value, data), "by": by}


async def _resplit(job: Job, doc: DocRef, pages: tuple[int, int]) -> dict[str, Any]:
    """The parts become invoices of their own (one child job each); this invoice ends here."""
    parts = await job.step("split", _split, job, doc, pages)
    children = [
        await job.spawn(
            "extract_invoice",
            {"file_id": str(p.file_id), "document": p.model_dump(mode="json")},
            title=f"Invoice: {p.name}",
            key=f"part{i}",
        )
        for i, p in enumerate(parts, start=1)
    ]
    results = await job.gather(children, key="parts")
    rows = [
        r.output
        if r.ok and isinstance(r.output, dict)
        else {"status": "failed", "error": r.error, "file": p.name}
        for r, p in zip(results, parts, strict=True)
    ]
    await job.step(
        "resplit_note",
        _comment,
        job,
        f"Split {doc.name} as asked (pages {pages[0]}-{pages[1]} are a separate invoice); "
        f"each part has its own subtask and record.",
    )
    return {"status": "resplit", "file": doc.name, "parts": rows}


async def _approver(
    job: Job, settings: Any, total: Decimal | None, currency: str | None
) -> uuid.UUID | None:
    """The first approval tier whose limit covers the amount, else the approvers setting (or the
    project owner, then admins)."""
    cur = (currency or "").upper()
    for tier in settings.approval_tiers:
        limit = {k.upper(): v for k, v in tier.up_to.items()}.get(cur)
        if total is not None and limit is not None and abs(total) <= limit:
            try:
                return uuid.UUID(tier.approver)
            except ValueError:
                continue
    people = await job.people("approvers", "approver")
    return people[0] if people else None


# ---------------------------------------------------------------- comments


def _skipped_text(skipped: list[dict[str, str]]) -> str:
    rows = "\n".join(f"- {s['file']}: {s['reason']}" for s in skipped)
    return f"I couldn't use {len(skipped)} file{'s' if len(skipped) != 1 else ''}:\n{rows}"


def _summary(
    rows: list[dict[str, Any]], skipped: list[dict[str, str]], files: dict[str, Any] | None = None
) -> str:
    ok = [r for r in rows if r.get("record_id")]
    review = [r for r in ok if r.get("status") == "needs_review"]
    failed = [r for r in rows if not r.get("record_id")]
    lines = [
        f"I read {len(ok)} invoice{'s' if len(ok) != 1 else ''}"
        + (f" ({len(review)} need a look)" if review else "")
        + (f"; {len(failed)} failed" if failed else "")
        + ".",
        "",
        "| Vendor | Number | Date | Total | Currency | Lines | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in ok:
        lines.append(
            f"| {r.get('vendor')} | {r.get('invoice_number') or '—'} | "
            f"{r.get('invoice_date') or '—'} | "
            f"{r.get('total') or '—'} | {r.get('currency') or '—'} | {r.get('lines')} | "
            f"{outputs.STATUS_LABELS.get(str(r.get('status')), str(r.get('status')))} |"
        )
    for r in failed:
        lines.append(f"\nFailed: {r.get('file')}: {r.get('error') or 'unknown error'}")
    if files and files.get("xlsx"):
        lines.append("\nThe catalogue (Excel and CSV, one row per line item) is attached.")
    for e in (files or {}).get("excluded") or []:
        lines.append(f"\nNot in the catalogue: {e['document']}: {e['reason']}")
    if skipped:
        lines.append("\n" + _skipped_text(skipped))
    return "\n".join(lines)
