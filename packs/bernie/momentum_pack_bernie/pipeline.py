"""Bernie's job (spec §9.3, steps 1-10 here, plus the record so one assignment already gives a
checked invoice record): gather → ingest → (a batch: one child job per invoice, each on its own
subtask) → per invoice: duplicate file → e-invoice? → read (text → OCR → vision) → vendor →
skills → extract → locate → math checks → record.

Every model call and every effect is a recorded step, so a job that's interrupted resumes where
it was. Document bytes are never stored in a step: a split-out or unpacked document is attached
to the task (source "agent") and every later step reads it by its file id."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from pydantic import BaseModel

from momentum.sdk import Job, StepFailed, step
from momentum_pack_bernie import einvoice, extract, ingest, read, vendors
from momentum_pack_bernie.checks_math import check, math_checks
from momentum_pack_bernie.locate import find_amount, locate


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
        if skipped:
            await job.step("skipped_note", _comment, job, _skipped_text(skipped))
        return {"status": "done", "documents": [out], "skipped": skipped}

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
    await job.step("summary", _comment, job, _summary(rows, skipped))
    return {"status": "done", "documents": rows, "skipped": skipped}


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
    checks: list[dict[str, Any]],
    confidence: float,
    status: str,
) -> str:
    rid = await job.effects.records.create(
        "invoice",
        data,
        task_id=job.task_id,
        provenance=prov,
        checks=checks,
        confidence=confidence,
        status=status,
        source_attachment_id=doc.file_id,
        source_sha256=doc.sha256,
        source_locator=f"pages {doc.page_range[0]}-{doc.page_range[1]} of {doc.parent}"
        if doc.page_range
        else None,
    )
    return str(rid)


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
    confidence = 1.0
    chunk_count = 0
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
        confidence = merged.confidence
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
    if entity_id is None:
        v = data["vendor"]
        m = await job.entities.match(
            "vendor_match", "vendor", v.get("name_as_printed") or v["name"], tax_id=v.get("tax_id")
        )
        if m.entity_id is not None:
            entity_id = str(m.entity_id)
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
    if entity_id is not None:
        entity = next((e for e in known if str(e.id) == entity_id), None)
        if entity is not None:
            data["vendor"]["name"] = entity.name
    if account and entity_id is not None:
        seen = await job.step("bank", _bank, job, entity_id, account)
        data["bank"] = {**(data.get("bank") or {}), "last4": seen.get("last4")}

    # where each value is printed, and the checks
    prov, row_checks = locate(data, reading)
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
    checks = math_checks(data, rounding_tolerance=bool(settings.rounding_tolerance)) + row_checks
    if xml_data is not None and reading.pages and data.get("stated_total") is not None:
        readable = [p for p in reading.pages if p.source != "vision" and p.words]
        if readable and not any(find_amount(p, data["stated_total"]) for p in readable):
            checks.append(
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
    if any("instruction text found" in n.casefold() for n in data.get("notes") or []):
        checks.append(
            check(
                "instruction_text_found",
                False,
                "The document doesn't try to give instructions",
                "The document contains text addressed to an AI; it was ignored.",
                severity="warn",
            )
        )
    if earlier:
        checks.append(
            check(
                "duplicate_file",
                False,
                "This file hasn't been processed before",
                f"The same file already made “{earlier[0].title}” ({earlier[0].status}).",
                severity="warn",
            )
        )
    blocked = any(not c["passed"] and c["severity"] == "block" for c in checks)
    status = "needs_review" if blocked else "ready"
    record_id = await job.step(
        "record", _record, job, doc, data, prov, checks, float(confidence), status
    )
    return {
        "status": status,
        "record_id": record_id,
        "file": doc.name,
        "vendor": data["vendor"]["name"],
        "invoice_number": data.get("invoice_number"),
        "invoice_date": data.get("invoice_date"),
        "total": data.get("stated_total"),
        "currency": data.get("currency"),
        "lines": len(data.get("lines") or []),
        "method": data["extraction"]["method"],
        "failing": [c["id"] for c in checks if not c["passed"]],
    }


# ---------------------------------------------------------------- comments


def _skipped_text(skipped: list[dict[str, str]]) -> str:
    rows = "\n".join(f"- {s['file']}: {s['reason']}" for s in skipped)
    return f"I couldn't use {len(skipped)} file{'s' if len(skipped) != 1 else ''}:\n{rows}"


def _summary(rows: list[dict[str, Any]], skipped: list[dict[str, str]]) -> str:
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
            f"{'needs review' if r.get('status') == 'needs_review' else 'ready'} |"
        )
    for r in failed:
        lines.append(f"\nFailed: {r.get('file')}: {r.get('error') or 'unknown error'}")
    if skipped:
        lines.append("\n" + _skipped_text(skipped))
    return "\n".join(lines)
