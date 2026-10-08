"""Phase 7.6 (spec §3.1): discover and load packs.

Installed packs come from the ``momentum.packs`` entry-point group (the app, the worker and the CLI
all load them the same way). ``MOMENTUM_PACKS`` filters by key (``*`` = all). Test-only packs come
from the repository's ``tests/packs/`` folder only when ``MOMENTUM_TEST_PACKS=true`` (tests, e2e and
the UI audit; never production). ``MOMENTUM_PACKS_ENABLED=false`` loads none.

A pack whose ``sdk`` range this Momentum doesn't satisfy, or whose manifest or limits are invalid,
is **refused** with the reason recorded (``Loaded.errors``), never half-loaded. An entry point that
isn't a ``Pack`` (e.g. a pack still being built) is skipped the same way.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path

from momentum.agents.packs.manifest import ManifestError, in_range
from momentum.agents.packs.pack import Pack, PackError
from momentum.core.settings import Settings
from momentum.core.telemetry import get_logger

ENTRY_POINT_GROUP = "momentum.packs"
SDK_VERSION = "1.0"  # momentum.sdk.SDK_VERSION re-exports this one
TEST_PACKS_DIR = Path(__file__).resolve().parents[5] / "tests" / "packs"

log = get_logger("packs")


@dataclass(frozen=True)
class PackLoadError:
    source: str  # the entry point or folder
    reason: str


@dataclass
class Loaded:
    packs: dict[str, Pack] = field(default_factory=dict)
    errors: list[PackLoadError] = field(default_factory=list)
    test_keys: set[str] = field(default_factory=set)


def _wanted(settings: Settings) -> set[str] | None:
    raw = settings.packs.strip()
    if raw in ("", "*"):
        return None
    return {k.strip() for k in raw.split(",") if k.strip()}


def check_pack(pack: Pack, settings: Settings) -> None:
    """Raise ``PackError`` when ``pack`` can't load on this deployment."""
    manifest = pack.manifest  # ManifestError → caller
    if not in_range(SDK_VERSION, manifest.sdk):
        raise PackError(
            f"{manifest.key} needs momentum.sdk {manifest.sdk}; this Momentum has {SDK_VERSION}"
        )
    limits = manifest.limits
    ceilings = {
        "step_timeout_s": (limits.step_timeout_s, settings.agent_step_timeout_s),
        "max_active_s": (limits.max_active_s, settings.agent_job_max_active_s),
        "concurrency": (limits.concurrency, settings.agent_child_concurrency),
        "max_children": (limits.max_children, settings.agent_max_children),
    }
    over = [f"{k} {v} > {c}" for k, (v, c) in ceilings.items() if v > c]
    if over:
        raise PackError(
            f"{manifest.key}: limits above this deployment's ceilings: {'; '.join(over)}"
        )
    pack.validate()


def _add(loaded: Loaded, pack: object, source: str, settings: Settings, *, test: bool) -> None:
    if not isinstance(pack, Pack):
        loaded.errors.append(PackLoadError(source, "not a momentum.sdk.Pack (not built yet?)"))
        return
    try:
        check_pack(pack, settings)
    except (PackError, ManifestError) as e:
        loaded.errors.append(PackLoadError(source, str(e)))
        return
    key = pack.key
    if key in loaded.packs:
        loaded.errors.append(PackLoadError(source, f"pack key {key!r} is already loaded"))
        return
    loaded.packs[key] = pack
    if test:
        loaded.test_keys.add(key)


def _load_test_pack(folder: Path) -> object:
    """Import ``tests/packs/<name>`` under a unique module name (``tests`` is taken by the API's own
    test package, so these are loaded by path)."""
    name = f"momentum_test_pack_{folder.name}"
    if name in sys.modules:
        return getattr(sys.modules[name], "pack", None)
    spec = importlib.util.spec_from_file_location(
        name, folder / "__init__.py", submodule_search_locations=[str(folder)]
    )
    if spec is None or spec.loader is None:
        raise PackError(f"can't import {folder}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return getattr(module, "pack", None)


def load_packs(settings: Settings, *, test_packs_dir: Path | None = None) -> Loaded:
    loaded = Loaded()
    if not settings.packs_enabled:
        return loaded
    wanted = _wanted(settings)
    for ep in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
        if wanted is not None and ep.name not in wanted:
            continue
        try:
            obj = ep.load()
        except Exception as e:  # a broken pack must not take the app down
            loaded.errors.append(PackLoadError(f"entry point {ep.name}", f"import failed: {e}"))
            continue
        _add(loaded, obj, f"entry point {ep.name}", settings, test=False)
    if settings.test_packs:
        folder_root = test_packs_dir or TEST_PACKS_DIR
        if folder_root.is_dir():
            for folder in sorted(p for p in folder_root.iterdir() if (p / "__init__.py").is_file()):
                if wanted is not None and folder.name not in wanted:
                    continue
                try:
                    obj = _load_test_pack(folder)
                except Exception as e:
                    loaded.errors.append(PackLoadError(str(folder), f"import failed: {e}"))
                    continue
                _add(loaded, obj, str(folder), settings, test=True)
    for err in loaded.errors:
        log.warning("pack_not_loaded", source=err.source, reason=err.reason)
    return loaded
