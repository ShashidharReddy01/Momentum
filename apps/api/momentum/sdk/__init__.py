"""The public, versioned facade every pack imports (ADR-0012). A pack (`momentum_pack_*`) may
import only `momentum.sdk`, its own package and allowed third-party libraries — never
`momentum.domain`, `momentum.ai`, `momentum.agents`, `momentum.core` or `momentum.files` directly
(import-linter enforces this per pack). With 50-100+ packs, Momentum's internals must stay free
to change; only this module is a promise.

Each pack declares `sdk: ">=1.0,<2"` in its manifest; the loader refuses a pack whose declared
range this version doesn't satisfy. The surface grows slice by slice (design spec §11.2):
S76-01 adds `Pack`, `Capability`, `PackSettings` and the setup items (`TaskField`, `Section`);
S76-02 adds the durable `Job` (steps, `job.llm`, `job.effects`, children, waiting, progress), the
`@step` marker for step bodies, `ChildRef` / `ChildResult` and `document_block`; S76-03 adds
`job.ask` (`AskAnswer`), `job.propose` (`Proposed`) and conversation runs (`job.classify` →
`Intent`, `job.jobs_on_task` → `TaskJob`, `send_instruction`, `wait_for_instruction`,
`start_job`); S76-04 adds records: `RecordModel`, `RecordType`, `Money`,
`job.effects.records.create/update` and `job.records` (`get`, `find_duplicates`, `find_similar`,
`query`); S76-05 adds `EntityType` / `EntityModel`, `job.entities` (`match`, `get`,
`bank_matches`), `job.effects.entities` (`create`, `update`, `add_alias`, `set_bank`),
`job.skills` (`for_`, `propose`), `job.effects.skills`, `job.settings()` and `scrub`; S76-09 adds
`job.files` (`list`, `read`) and `FileRef`, `job.ocr` and page rendering, and `StepFailed` (a
step that failed, for a pack that can carry on without it).
"""

from __future__ import annotations

from momentum.agents.jobs.effects import BankSeen, SkillProposal
from momentum.agents.jobs.files import FileRef
from momentum.agents.jobs.job import ChildRef, ChildResult, Job, StepFailed, document_block, step
from momentum.agents.jobs.memory import EntityMatch, EntityView, SkillView
from momentum.agents.jobs.records import RecordView, Similar
from momentum.agents.jobs.talk import AskAnswer, Intent, Proposed, TaskJob
from momentum.agents.packs.entities import EntityModel, EntityType
from momentum.agents.packs.loader import SDK_VERSION
from momentum.agents.packs.manifest import Capability, PackManifest
from momentum.agents.packs.pack import Pack, PackError, PackSettings
from momentum.agents.packs.records import Money, RecordModel, RecordType
from momentum.agents.packs.setup import Section, TaskField
from momentum.core.scrub import ScrubResult, scrub

__all__ = [
    "SDK_VERSION",
    "AskAnswer",
    "BankSeen",
    "Capability",
    "ChildRef",
    "ChildResult",
    "EntityMatch",
    "EntityModel",
    "EntityType",
    "EntityView",
    "FileRef",
    "Intent",
    "Job",
    "Money",
    "Pack",
    "PackError",
    "PackManifest",
    "PackSettings",
    "Proposed",
    "RecordModel",
    "RecordType",
    "RecordView",
    "ScrubResult",
    "Section",
    "Similar",
    "SkillProposal",
    "SkillView",
    "StepFailed",
    "TaskField",
    "TaskJob",
    "document_block",
    "scrub",
    "step",
]
