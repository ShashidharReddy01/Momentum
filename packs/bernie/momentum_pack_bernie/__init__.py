"""Bernie, the invoice agent (ADR-0013, ADR-0014): reads invoices (PDF, scans, images,
e-invoices, zips, emails) into checked invoice records, one per invoice, line by line. A faithful
port of the COAP notebook's pipeline onto Momentum's agent platform; see `pipeline.py` for the
steps and `docs/agents/bernie.md` for the user guide."""

from __future__ import annotations

from pathlib import Path

from momentum.sdk import Pack, Section, TaskField
from momentum_pack_bernie.entities import VENDOR
from momentum_pack_bernie.pipeline import run
from momentum_pack_bernie.records import INVOICE
from momentum_pack_bernie.settings import BernieSettings

pack = Pack(
    manifest_path=Path(__file__).parent / "manifest.yaml",
    run=run,
    capabilities={"extract_invoice": run},
    settings=BernieSettings,
    record_types=(INVOICE,),
    entity_types=(VENDOR,),
    setup=(
        TaskField(name="Vendor", type="text"),
        TaskField(name="Invoice #", type="text"),
        TaskField(name="Invoice date", type="date"),
        TaskField(name="Amount", type="number"),
        TaskField(name="Currency", type="text"),
        TaskField(
            name="Invoice status",
            type="single_select",
            options=("Needs review", "Ready", "Approved", "Rejected", "On hold"),
        ),
        Section(name="Review", unless=("Review", "In review")),
    ),
)
