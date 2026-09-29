"""Scorers (testing-strategy §6): each ``expect`` key of a case is one check on the
``Observation``. A case passes when every check passes. Checks are structural (tools, targets,
fields), citation validity (every reference exists and the asking user can see it), leak checks
(private content never mentioned), and output shape; the LLM-as-judge check lives in the runner
(live mode only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from momentum.ai.evals.features import Observation

UNCERTAIN = re.compile(
    r"couldn['\u2019]?t find|could not find|can['\u2019]?t find|cannot find|unable to find|"
    r"no (matching|relevant|results?|tasks?|information|record)|nothing (about|matching|found|in)|"
    r"not sure|don['\u2019]?t (know|see|have)|isn['\u2019]?t (anything|mentioned)|no mention",
    re.I,
)
KEY = re.compile(r"\bT-\d+\b")


KNOWN = frozenset(
    {
        "nudged_include",
        "nudged_exclude",
        "sorter_priority_in",
        "sorter_priority_none",
        "sorter_field_in",
        "sorter_duplicate_of",
        "sorter_no_duplicate",
        "digest_empty",
        "digest_covers",
        "agent_trigger_types",
        "agent_cron_any",
        "agent_tools_include",
        "agent_tools_exclude",
        "agent_autonomy",
        "error",
        "tools_include",
        "tools_any",
        "tools_exclude",
        "proposes",
        "proposes_any",
        "proposes_nothing",
        "risk",
        "targets_include",
        "targets_exclude",
        "clarifies",
        "citations_valid",
        "min_citations",
        "cites_include",
        "mentions_exclude",
        "grounded",
        "uncertain",
        "text_include_any",
        "text_include_all",
        "text_exclude",
        "not_empty",
        "max_chars",
        "notes_include",
        "notes_empty",
        "shorter_than",
        "preserves",
        "items_cite_tasks",
        "status_in",
        "today_first_any",
        "today_include",
        "today_exclude",
        "subtasks_between",
        "assignees_on_project",
        "due_before_end",
        "tasks_between",
        "fields",
        "rule_exact",
        "values_in",
        "values_absent",
    }
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


def _low(x: str) -> str:
    return x.lower()


def _labels(obs: Observation) -> str:
    """Everything the proposed operations touch, as one searchable string."""
    parts: list[str] = []
    for op in obs.operations:
        parts.append(json.dumps(op.get("args") or {}, ensure_ascii=False))
        parts += [str(d.get("label", "")) for d in op.get("diff") or []]
    return "\n".join(parts).lower()


def _op_args(obs: Observation, tool: str) -> list[dict[str, Any]]:
    return [op.get("args") or {} for op in obs.operations if op.get("tool") == tool]


def score(obs: Observation, expect: dict[str, Any], *, today: date, asked: str = "") -> list[Check]:
    out: list[Check] = []
    add = out.append
    text = obs.text or ""
    lt = text.lower()

    if "error" in expect:
        add(
            Check(
                "error",
                bool(obs.error) and str(obs.error).startswith(str(expect["error"])),
                f"got {obs.error}",
            )
        )
        return out
    add(Check("no_error", obs.error is None, f"error: {obs.error}" if obs.error else ""))

    for t in expect.get("tools_include", []):
        add(Check(f"tools_include:{t}", t in obs.tools, f"tools: {obs.tools}"))
    if "tools_any" in expect:
        add(
            Check(
                "tools_any", any(t in obs.tools for t in expect["tools_any"]), f"tools: {obs.tools}"
            )
        )
    for t in expect.get("tools_exclude", []):
        add(Check(f"tools_exclude:{t}", t not in obs.tools, f"tools: {obs.tools}"))
    proposed = [op.get("tool") for op in obs.operations]
    for t in expect.get("proposes", []):
        add(Check(f"proposes:{t}", t in proposed, f"proposed: {proposed}"))
    if "proposes_any" in expect:
        ok = any(t in proposed for t in expect["proposes_any"])
        add(Check("proposes_any", ok, f"proposed: {proposed}"))
    if expect.get("proposes_nothing"):
        add(Check("proposes_nothing", not proposed, f"proposed: {proposed}"))
    if "risk" in expect:
        add(Check("risk", obs.risk == expect["risk"], f"risk: {obs.risk}"))
    labels = _labels(obs)
    for t in expect.get("targets_include", []):
        add(Check(f"targets_include:{t}", _low(t) in labels, "not in the proposed change"))
    for t in expect.get("targets_exclude", []):
        add(Check(f"targets_exclude:{t}", _low(t) not in labels, "in the proposed change"))
    if "clarifies" in expect:
        # Asking which one, in words and with nothing proposed, is a clarification too.
        asked_in_words = not obs.operations and "?" in text
        clarified = obs.clarified or asked_in_words
        add(
            Check(
                "clarifies",
                clarified == bool(expect["clarifies"]),
                f"clarified: {obs.clarified}, text: {text[-80:]!r}",
            )
        )

    if expect.get("citations_valid"):
        bad = [c.get("ref") for c in obs.citations if not c.get("valid")]
        add(Check("citations_valid", not bad, f"invalid: {bad}"))
    if "min_citations" in expect:
        n = sum(1 for c in obs.citations if c.get("valid"))
        add(Check("min_citations", n >= int(expect["min_citations"]), f"valid citations: {n}"))
    for t in expect.get("cites_include", []):
        ok = any(
            c.get("valid") and _low(t) in _low(str(c.get("title") or "")) for c in obs.citations
        )
        add(Check(f"cites_include:{t}", ok, "not cited"))
    for t in expect.get("mentions_exclude", []):
        in_cites = any(_low(t) in _low(str(c.get("title") or "")) for c in obs.citations)
        # Echoing what the asker typed ("no task called Zenith found") reveals nothing.
        echoed = _low(t) in _low(asked)
        in_text = _low(t) in lt and not echoed
        add(Check(f"mentions_exclude:{t}", not in_text and not in_cites, "leaked"))
    if "grounded" in expect:
        add(
            Check("grounded", obs.grounded == bool(expect["grounded"]), f"grounded: {obs.grounded}")
        )
    if "uncertain" in expect:
        found = bool(UNCERTAIN.search(text))
        add(Check("uncertain", found == bool(expect["uncertain"]), f"text: {text[:160]!r}"))

    if "text_include_any" in expect:
        add(
            Check(
                "text_include_any",
                any(_low(x) in lt for x in expect["text_include_any"]),
                f"text: {text[:160]!r}",
            )
        )
    for x in expect.get("text_include_all", []):
        add(Check(f"text_include:{x}", _low(x) in lt, f"text: {text[:160]!r}"))
    for x in expect.get("text_exclude", []):
        add(Check(f"text_exclude:{x}", _low(x) not in lt, f"text: {text[:160]!r}"))
    if expect.get("not_empty"):
        add(Check("not_empty", bool(text.strip()), "empty"))
    if "max_chars" in expect:
        add(Check("max_chars", len(text) <= int(expect["max_chars"]), f"{len(text)} chars"))
    for x in expect.get("notes_include", []):
        add(
            Check(
                f"notes_include:{x}",
                any(_low(x) in _low(n) for n in obs.notes),
                f"notes: {obs.notes}",
            )
        )
    if expect.get("notes_empty"):
        add(Check("notes_empty", not obs.notes, f"notes: {obs.notes}"))

    # writing help
    if "shorter_than" in expect:
        src = str(obs.data.get("input", ""))
        ratio = len(text) / max(len(src), 1)
        add(Check("shorter_than", ratio <= float(expect["shorter_than"]), f"ratio {ratio:.2f}"))
    for x in expect.get("preserves", []):
        add(Check(f"preserves:{x}", x in text, "missing in the rewrite"))

    # status draft
    if expect.get("items_cite_tasks"):
        items = obs.data.get("items", [])
        bare = [i for i in items if not KEY.search(i)]
        add(Check("items_cite_tasks", bool(items) and not bare, f"uncited: {bare}"))
    if "status_in" in expect:
        add(
            Check(
                "status_in",
                obs.data.get("status") in expect["status_in"],
                f"status: {obs.data.get('status')}",
            )
        )

    # plan my day
    if "today_first_any" in expect:
        today_keys = obs.data.get("today", [])
        first = today_keys[0] if today_keys else None
        add(Check("today_first_any", first in expect["today_first_any"], f"today: {today_keys}"))
    for k in expect.get("today_include", []):
        add(
            Check(
                f"today_include:{k}",
                k in obs.data.get("today", []),
                f"today: {obs.data.get('today')}",
            )
        )
    for k in expect.get("today_exclude", []):
        add(
            Check(
                f"today_exclude:{k}",
                k not in obs.data.get("today", []),
                f"today: {obs.data.get('today')}",
            )
        )

    # Sorter triage (S5.3.2): what it proposed for the new task
    priorities = [a.get("priority") for a in _op_args(obs, "update_task") if "priority" in a]
    if "sorter_priority_in" in expect:
        ok = bool(priorities) and priorities[-1] in expect["sorter_priority_in"]
        add(Check("sorter_priority_in", ok, f"priority: {priorities}"))
    if expect.get("sorter_priority_none"):
        add(Check("sorter_priority_none", not priorities, f"priority: {priorities}"))
    for name, allowed in (expect.get("sorter_field_in") or {}).items():
        got_values = [
            a.get("value")
            for a in _op_args(obs, "set_field_value")
            if str(a.get("field", "")).lower() == name.lower()
        ]
        ok = bool(got_values) and str(got_values[-1]).lower() in {str(x).lower() for x in allowed}
        add(Check(f"sorter_field_in:{name}", ok, f"{name}: {got_values}"))
    comments = " ".join(str(a.get("text", "")) for a in _op_args(obs, "add_comment")).lower()
    if "sorter_duplicate_of" in expect:
        want = [str(x).lower() for x in expect["sorter_duplicate_of"]]
        ok = "duplicate" in comments and any(w in comments for w in want)
        add(Check("sorter_duplicate_of", ok, f"comments: {comments[:160]!r}"))
    if expect.get("sorter_no_duplicate"):
        add(
            Check(
                "sorter_no_duplicate", "duplicate" not in comments, f"comments: {comments[:160]!r}"
            )
        )

    # Nudge (S5.3.4): which tasks got a reminder
    nudged = [str(t).lower() for t in obs.data.get("nudged", [])]
    for t in expect.get("nudged_include", []):
        add(Check(f"nudged_include:{t}", t.lower() in nudged, f"nudged: {nudged}"))
    for t in expect.get("nudged_exclude", []):
        add(Check(f"nudged_exclude:{t}", t.lower() not in nudged, f"nudged: {nudged}"))

    # Pulse digests (S5.3.1)
    if "digest_empty" in expect:
        got_empty = bool(obs.data.get("empty"))
        add(Check("digest_empty", got_empty == bool(expect["digest_empty"]), f"empty: {got_empty}"))
    if expect.get("digest_covers"):
        missing = obs.data.get("missing") or []
        add(Check("digest_covers", not missing, f"missing: {missing}"))

    # agent drafts (S5.2.3)
    if "agent_trigger_types" in expect:
        kinds = sorted({t["type"] for t in obs.data.get("triggers", [])})
        ok = set(expect["agent_trigger_types"]) <= set(kinds)
        add(Check("agent_trigger_types", ok, f"triggers: {kinds}"))
    if "agent_cron_any" in expect:
        crons = [t.get("cron") for t in obs.data.get("triggers", []) if t.get("cron")]
        ok = any(c in expect["agent_cron_any"] for c in crons)
        add(Check("agent_cron_any", ok, f"crons: {crons}"))
    for t in expect.get("agent_tools_include", []):
        add(Check(f"agent_tools_include:{t}", t in obs.data.get("tools", []), ""))
    for t in expect.get("agent_tools_exclude", []):
        add(Check(f"agent_tools_exclude:{t}", t not in obs.data.get("tools", []), ""))
    if "agent_autonomy" in expect:
        got_autonomy = obs.data.get("autonomy")
        ok = got_autonomy == expect["agent_autonomy"]
        add(Check("agent_autonomy", ok, f"autonomy: {got_autonomy}"))

    # break into subtasks
    if "subtasks_between" in expect:
        lo, hi = expect["subtasks_between"]
        n = sum(len(a.get("subtasks", [])) for a in _op_args(obs, "create_subtasks"))
        add(Check("subtasks_between", lo <= n <= hi, f"{n} subtasks"))
    if expect.get("assignees_on_project"):
        allowed = set(obs.data.get("project_people", []))
        used = {
            s["assignee"]
            for a in _op_args(obs, "create_subtasks")
            for s in a.get("subtasks", [])
            if s.get("assignee")
        }
        add(Check("assignees_on_project", used <= allowed, f"outside: {used - allowed}"))

    # project from a brief
    if expect.get("due_before_end"):
        end = obs.data.get("requested_end")
        dues = [
            t["due_on"]
            for a in _op_args(obs, "create_project_from_plan")
            for sec in a.get("sections", [])
            for t in sec.get("tasks", [])
            if t.get("due_on")
        ]
        late = [d for d in dues if end and d > end]
        add(Check("due_before_end", bool(dues) and not late, f"after {end}: {late}"))
    if "tasks_between" in expect:
        lo, hi = expect["tasks_between"]
        n = int(obs.data.get("tasks", 0))
        add(Check("tasks_between", lo <= n <= hi, f"{n} tasks"))

    # natural language → rule: the compiled rule, with names in place of ids, exactly as expected
    if "rule_exact" in expect:
        got = obs.data.get("rule")
        add(Check("rule_exact", got == expect["rule_exact"], json.dumps(got, default=str)[:300]))

    # AI step (S4.1.5): the value it wrote must be one of the acceptable ones, and a field the
    # task says nothing about must be left alone rather than guessed at.
    for name, allowed in (expect.get("values_in") or {}).items():
        got = obs.data.get(name)
        ok = got is not None and _low(str(got)) in [_low(str(a)) for a in allowed]
        add(Check(f"values_in:{name}", ok, f"{name}: {got!r}"))
    for name in expect.get("values_absent") or []:
        add(
            Check(
                f"values_absent:{name}",
                obs.data.get(name) is None,
                f"{name}: {obs.data.get(name)!r}",
            )
        )

    # quick add
    fields = expect.get("fields") or {}
    for name, want in fields.items():
        if name == "due_in_days":
            got = obs.data.get("due_on")
            ok = (
                got == (today + timedelta(days=int(want))).isoformat()
                if want is not None
                else got is None
            )
            add(Check("fields:due_in_days", ok, f"due_on: {got}"))
        elif name in ("assignee", "project"):
            got = (obs.data.get(name) or {}).get("name")
            add(Check(f"fields:{name}", got == want, f"{name}: {got}"))
        elif name == "title_includes":
            got = str(obs.data.get("title", ""))
            add(Check("fields:title_includes", _low(want) in _low(got), f"title: {got!r}"))
        elif name == "recurrence_freq":
            got = (obs.data.get("recurrence") or {}).get("freq")
            add(Check("fields:recurrence_freq", got == want, f"freq: {got}"))
        else:
            got = obs.data.get(name)
            add(Check(f"fields:{name}", got == want, f"{name}: {got}"))
    return out
