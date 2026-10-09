"""Bernie's settings (spec §9.7): per workspace, overridable per project, edited on the agent
page's Settings tab (rendered from this schema's `ui` hints)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from momentum.sdk import PackSettings


class BernieSettings(PackSettings):
    stewards: list[str] = Field(
        default_factory=list,
        title="Stewards",
        description=(
            "People who look after Bernie: review its learned skills and its holds "
            "(default: workspace admins)"
        ),
        json_schema_extra={"ui": "people"},
    )
    auto_approve: bool = Field(
        default=False,
        title="Approve small, clean invoices on its own",
        description=(
            "Off by default. Never for a new vendor, changed bank details or a failed check"
        ),
        json_schema_extra={"ui": "bool"},
    )
    materiality: dict[str, Decimal] = Field(
        default_factory=lambda: {"USD": Decimal(5000), "GBP": Decimal(4000), "EUR": Decimal(4500)},
        title="Needs a person at or above",
        description="Per currency; any other currency always needs a person",
        json_schema_extra={"ui": "money_by_currency"},
    )
    confidence_floor: float = Field(
        default=0.85,
        ge=0,
        le=1,
        title="Confidence floor",
        description="Below this, an invoice always goes to a person",
        json_schema_extra={"ui": "percent"},
    )
    rounding_tolerance: bool = Field(
        default=True,
        title="Allow per-line rounding",
        description=(
            "Lines may differ from the total by 0.01 per line (some vendors round each line)"
        ),
        json_schema_extra={"ui": "bool"},
    )
    ocr: bool = Field(
        default=True,
        title="Read scans with OCR first",
        description=(
            "OCR scanned pages before looking at them as images (needs Tesseract on the server)"
        ),
        json_schema_extra={"ui": "bool"},
    )
    watch_uploads: bool = Field(
        default=False,
        title="Process every invoice uploaded to the project",
        description="A task per upload, in the inbox section, assigned to Bernie",
        json_schema_extra={"ui": "bool"},
    )
    inbox_section: str = Field(
        default="Invoices in",
        title="Inbox section",
        description="Where watched uploads become tasks",
        json_schema_extra={"ui": "text"},
    )
    rename_tasks: bool = Field(
        default=True,
        title="Rename tasks",
        description='e.g. "Northwind Data · INV-2041 · GBP 1,250.00"',
        json_schema_extra={"ui": "bool"},
    )
    set_task_fields: bool = Field(
        default=True,
        title="Fill in task fields",
        description="Vendor, invoice number, date, amount, currency",
        json_schema_extra={"ui": "bool"},
    )
    max_pages: int = Field(
        default=200,
        ge=1,
        le=2000,
        title="Most pages in one document",
        description="Bigger documents: Bernie asks you to split them",
        json_schema_extra={"ui": "int"},
    )
