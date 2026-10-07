"""Phase 7.5 (spec §6.1): the neutral report document every renderer reads. Builders make it
from domain data (no LLM call); the narrative adds ``Paragraph(ai=True)`` blocks; renderers turn
it into docx, xlsx, pdf, md or csv and mark every AI paragraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Cell = str | int | float | bool | date | datetime | None
AI_LABEL = "AI-drafted, review before sending"


@dataclass
class Heading:
    text: str
    level: int = 1


@dataclass
class Paragraph:
    text: str
    ai: bool = False
    cites: list[str] = field(default_factory=list)


@dataclass
class Kpi:
    label: str
    value: str
    raw: float | None = None  # the number behind ``value`` (xlsx writes it as a number)
    delta: str | None = None


@dataclass
class KPIRow:
    items: list[Kpi]


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[Cell]]
    total_row: list[Cell] | None = None
    sheet: str | None = None  # xlsx: its own data sheet (name), else on the summary


@dataclass
class Chart:
    title: str
    kind: Literal["bar", "line", "donut"]
    labels: list[str]
    values: list[float]


@dataclass
class TaskItem:
    key: str
    title: str
    assignee: str | None = None
    due_on: date | None = None
    done: bool = False


@dataclass
class TaskList:
    title: str
    items: list[TaskItem]
    empty: str = "Nothing here."


@dataclass
class Callout:
    text: str
    tone: Literal["info", "warn", "crit", "ok"] = "info"


@dataclass
class PageBreak:
    pass


Block = Heading | Paragraph | KPIRow | Table | Chart | TaskList | Callout | PageBreak


@dataclass
class ReportDocument:
    title: str
    subtitle: str
    generated_at: datetime
    generated_by: str
    scope_note: str
    blocks: list[Block] = field(default_factory=list)
    # the facts the narrative may use (numbers, names, keys), handed to it as data
    facts: dict[str, object] = field(default_factory=dict)
    # where the narrative goes (after the headline numbers); None: at the end
    narrative_index: int | None = None

    def add(self, *blocks: Block) -> None:
        self.blocks.extend(blocks)

    @property
    def ai_paragraphs(self) -> list[Paragraph]:
        return [b for b in self.blocks if isinstance(b, Paragraph) and b.ai]
