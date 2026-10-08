"""Phase 7.6 S76-02 (spec §4.2 rule 3): code between steps must be deterministic, because a job is
replayed from the top. Pack modules may read the clock, make random values or new ids only inside
``@step`` functions (which run once and are recorded); everywhere else they use ``job.now()`` and
``job.uuid()``. This scans every pack (shipped and test) and fails on a call outside a step."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PACK_DIRS = [REPO / "packs", REPO / "tests" / "packs"]
FORBIDDEN = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("time", "monotonic"),
    ("uuid", "uuid4"),
    ("uuid", "uuid1"),
}
FORBIDDEN_NAMES = {"uuid4", "uuid1"}


def _is_step(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for d in fn.decorator_list:
        name = d.attr if isinstance(d, ast.Attribute) else getattr(d, "id", None)
        if name == "step":
            return True
    return False


def violations(source: str, filename: str = "<pack>") -> list[str]:
    """Calls to the clock, randomness or new ids outside ``@step`` functions."""
    tree = ast.parse(source, filename)
    found: list[str] = []

    def visit(node: ast.AST, in_step: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, in_step or _is_step(child))
                continue
            if isinstance(child, ast.Call) and not in_step:
                f = child.func
                bad = False
                if isinstance(f, ast.Attribute):
                    base = f.value
                    base_name = (
                        base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                    )
                    bad = (base_name, f.attr) in FORBIDDEN or base_name == "random"
                elif isinstance(f, ast.Name):
                    bad = f.id in FORBIDDEN_NAMES
                if bad:
                    found.append(f"{filename}:{child.lineno}: {ast.unparse(f)}() outside a @step")
            visit(child, in_step)

    visit(tree, False)
    return found


def _pack_files() -> list[Path]:
    files: list[Path] = []
    for root in PACK_DIRS:
        files += [p for p in root.rglob("*.py") if "tests" not in p.relative_to(root).parts[1:]]
    return sorted(files)


def test_every_pack_is_deterministic_between_steps() -> None:
    files = _pack_files()
    assert any("failer" in str(p) for p in files)  # the scan really covers the packs
    problems = [v for p in files for v in violations(p.read_text(encoding="utf-8"), str(p))]
    assert problems == []


@pytest.mark.parametrize(
    ("source", "bad"),
    [
        ("from datetime import datetime\nasync def run(job):\n    datetime.now()\n", True),
        ("import time\nasync def run(job):\n    x = time.time()\n", True),
        ("import random\nasync def run(job):\n    random.choice([1])\n", True),
        ("from uuid import uuid4\nasync def run(job):\n    uuid4()\n", True),
        ("import uuid\nasync def run(job):\n    uuid.uuid4()\n", True),
        (
            "from momentum.sdk import step\nfrom datetime import datetime\n"
            "@step\nasync def stamp():\n    return datetime.now()\n",
            False,
        ),
        (
            "import momentum.sdk as sdk\nimport time\n@sdk.step\nasync def t():\n"
            "    def inner():\n        return time.time()\n    return inner()\n",
            False,
        ),
        ("async def run(job):\n    return await job.now()\n", False),
    ],
)
def test_the_lint_itself(source: str, bad: bool) -> None:
    assert bool(violations(source)) is bad
