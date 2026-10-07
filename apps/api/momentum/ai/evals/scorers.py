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

# Narrower than UNCERTAIN: saying the search came up empty (not hedging inside a real answer).
NOT_FOUND = re.compile(
    r"(couldn['\u2019]?t|could not|can['\u2019]?t|cannot|unable to|didn['\u2019]?t|did not) find|"
    r"nothing (about|matching|found|on that|related)|no (matching|relevant) (results?|tasks?|"
    r"information|content)|(found|returned|there(['\u2019]s| is| are)) (nothing|no (results?|"
    r"matches|tasks?))",
    re.I,
)
UNCERTAIN = re.compile(
    r"couldn['\u2019]?t find|could not find|can['\u2019]?t find|cannot find|unable to find|"
    r"no (matching|relevant|results?|tasks?|information|record)|nothing (about|matching|found|in)|"
    r"not sure|don['\u2019]?t (know|see|have)|isn['\u2019]?t (anything|mentioned)|no mention",
    re.I,
)
KEY = re.compile(r"\bT-\d+\b")


KNOWN = frozenset(
    {
        "action_items_recall",
        "risk_level_in",
        "risk_signals_include",
        "nudged_include",
        "nudged_exclude",
        "sorter_priority_in",
        "sorter_priority_none",
        "sorter_priority_not_in",
        "sorter_field_in",
        "sorter_duplicate_of",
        "sorter_no_duplicate",
        "digest_empty",
        "digest_covers",
        "agent_trigger_types",
        "agent_cron_any",
        "agent_tools_include",
        "agent_tools_any",
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
        "ai_draft",
        "today_first_any",
        "today_include",
        "today_exclude",
        "subtasks_between",
        "assignees_on_project",
        "due_before_end",
        "tasks_between",
        "fields",
        "rule_exact",
        "chart_exact",
        "chart_window_between",
        "chart_value",
        "chart_groups",
        "chart_tasks",
        "values_in",
        "values_absent",
        # Phase 7.5 (spec §11.3)
        "cites_locator",
        "numbers_from_tools",
        "query_exact",
        "images_sent",
        "answer_contains_number",
        "no_leak",
        "paragraphs_min",
        "cites_from_facts",
    }
)

_NUM = re.compile(r"(?<![\w.])[-+]?\(?\d[\d,]*(?:\.\d+)?\)?%?(?![\w])")
_BRACKETS = re.compile(r"\[[^\]]*\]")


def _numbers(text: str) -> list[float]:
    """Numbers as a reader sees them: 1,234.50 → 1234.5; (12) → -12; 12% → 12."""
    out: list[float] = []
    for m in _NUM.finditer(text):
        raw = m.group(0)
        neg = raw.startswith("(") and raw.endswith(")")
        clean = raw.strip("()+%").replace(",", "")
        try:
            n = float(clean)
        except ValueError:
            continue
        out.append(-n if neg else n)
    return out


def _flat_numbers(value: Any) -> set[float]:
    found: set[float] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, int | float):
        found.add(float(value))
    elif isinstance(value, str):
        found.update(_numbers(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _flat_numbers(v)
    elif isinstance(value, list):
        for v in value:
            found |= _flat_numbers(v)
    return found


def _close(n: float, known: set[float]) -> bool:
    """Equal, or the same value rounded the way a person writes it (0-2 decimals, or x100 for
    a share shown as a percentage)."""
    for k in known:
        if abs(n - k) < 1e-6 or any(abs(n - round(k, d)) < 1e-6 for d in (0, 1, 2)):
            return True
        if abs(n - round(k * 100, 1)) < 1e-6 or abs(n - round(k * 100)) < 1e-6:
            return True
    return False


def _query_matches(want: dict[str, Any], got: dict[str, Any]) -> bool:
    """Every key the case names must match (names case-insensitive); others are free."""

    def norm(v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        if isinstance(v, list):
            return [norm(x) for x in v]
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items() if x not in (None, [], {})}
        return v

    g = norm(got)
    for key, value in norm(want).items():
        have = g.get(key)
        if isinstance(value, list) and isinstance(have, list):
            if not all(any(_sub(v, h) for h in have) for v in value):
                return False
        elif not _sub(value, have):
            return False
    return True


def _sub(want: Any, have: Any) -> bool:
    if isinstance(want, dict) and isinstance(have, dict):
        return all(_sub(v, have.get(k)) for k, v in want.items())
    if isinstance(want, int | float) and isinstance(have, int | float | str):
        try:
            return abs(float(have) - float(want)) < 1e-9
        except ValueError:
            return False
    return bool(want == have)


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
        # Grounded = the answer rests on workspace sources: a valid citation, and not an answer
        # that says it found nothing (whatever it then cites "for context" doesn't bear on the
        # question: Phase 5 live round 2, chat/empty_retrieval_admits_it).
        found_nothing = bool(NOT_FOUND.search(text))
        grounded = bool(obs.grounded) and not found_nothing
        add(
            Check(
                "grounded",
                grounded == bool(expect["grounded"]),
                f"grounded: {grounded} (cites a source: {obs.grounded}, says it found nothing: "
                f"{found_nothing})",
            )
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
    if "ai_draft" in expect:  # S6.3.2: the model's draft was kept (grounded in the facts)
        add(
            Check("ai_draft", obs.data.get("ai") is expect["ai_draft"], f"ai: {obs.data.get('ai')}")
        )
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
    if "sorter_priority_not_in" in expect:
        ok = not any(p in expect["sorter_priority_not_in"] for p in priorities)
        add(Check("sorter_priority_not_in", ok, f"priority: {priorities}"))
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

    # Scribe (S5.3.6): share of the expected action items among the proposed tasks' titles
    if "action_items_recall" in expect:
        spec = expect["action_items_recall"]
        titles = " | ".join(str(a.get("title", "")).lower() for a in _op_args(obs, "create_task"))
        wanted = [str(x).lower() for x in spec["items"]]
        hit = [w for w in wanted if all(word in titles for word in w.split())]
        recall = len(hit) / len(wanted) if wanted else 1.0
        ok = recall >= float(spec.get("min", 0.85))
        add(Check("action_items_recall", ok, f"{recall:.0%}: missing {set(wanted) - set(hit)}"))

    # Radar (S5.3.7): the note's level and signals
    if "risk_level_in" in expect:
        got_level = obs.data.get("level")
        ok = got_level in expect["risk_level_in"]
        add(Check("risk_level_in", ok, f"level: {got_level}"))
    for kind in expect.get("risk_signals_include", []):
        kinds = obs.data.get("kinds") or []
        add(Check(f"risk_signals_include:{kind}", kind in kinds, f"signals: {kinds}"))

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
    if "agent_tools_any" in expect:  # one of these is enough (e.g. either way of searching)
        got_tools = obs.data.get("tools", [])
        ok = any(t in got_tools for t in expect["agent_tools_any"])
        add(Check("agent_tools_any", ok, f"tools: {got_tools}"))
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

    # ask for a chart (S6.5.2): the chart as names; the window only within a range (the model
    # may read "last 3 months" as 84 or 90 days); the numbers the server counted
    if "chart_exact" in expect:
        chart_got: dict[str, Any] = obs.data.get("chart") or {}
        want_chart: dict[str, Any] = expect["chart_exact"]
        seen = {k: v for k, v in chart_got.items() if k != "window_days"}
        want_full = {"group_by": None, "measure": "count", **want_chart}
        want_full["filters"] = {"status": "open", **want_chart.get("filters", {})}
        add(Check("chart_exact", seen == want_full, json.dumps(chart_got, default=str)[:300]))
    if "chart_window_between" in expect:
        w_lo, w_hi = expect["chart_window_between"]
        window = (obs.data.get("chart") or {}).get("window_days")
        ok_window = window is not None and w_lo <= window <= w_hi
        add(Check("chart_window_between", ok_window, f"window: {window}"))
    if "chart_value" in expect:
        add(
            Check(
                "chart_value",
                obs.data.get("value") == expect["chart_value"],
                f"value: {obs.data.get('value')}",
            )
        )
    if "chart_groups" in expect:
        groups = obs.data.get("groups")
        add(Check("chart_groups", groups == expect["chart_groups"], f"groups: {groups}"))
    if "chart_tasks" in expect:
        got_titles = sorted(obs.data.get("task_titles") or [])
        ok_titles = got_titles == sorted(expect["chart_tasks"])
        add(Check("chart_tasks", ok_titles, f"tasks: {got_titles}"))

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

    # Phase 7.5: files (spec §11.3). obs.data["tool_calls"] = [{name, args, ok, output}]
    calls: list[dict[str, Any]] = list(obs.data.get("tool_calls") or [])
    outputs = [c.get("output") or {} for c in calls if c.get("ok")]
    if "cites_locator" in expect:
        want_loc = expect["cites_locator"]
        files = [c for c in obs.citations if c.get("type") == "file" and c.get("valid")]
        ok = any(c.get("key") for c in files) and (
            want_loc is True
            or any(_low(str(want_loc)) in _low(str(c.get("key") or "")) for c in files)
        )
        got = [f"{c.get('title')} · {c.get('key')}" for c in files]
        add(Check("cites_locator", ok, f"file citations: {got}"))
    if expect.get("numbers_from_tools"):
        known = _flat_numbers(outputs) | set(_numbers(asked))
        said = _numbers(_BRACKETS.sub(" ", text))
        stray = [n for n in said if not _close(n, known)]
        add(Check("numbers_from_tools", not stray, f"numbers not in any tool output: {stray}"))
    if "query_exact" in expect:
        want = expect["query_exact"]
        queries = [c.get("args") or {} for c in calls if c.get("name") == "query_table"]
        ok = any(
            _query_matches(want.get("query") or {}, q.get("query") or {})
            and all(
                _low(str(q.get(k) or "")) == _low(str(v)) for k, v in want.items() if k != "query"
            )
            for q in queries
        )
        add(Check("query_exact", ok, f"queries: {queries}"))
    if "images_sent" in expect:
        n = int(obs.data.get("images") or 0)
        rule = expect["images_sent"]
        lo, hi = (
            (rule.get("min", 1), rule.get("max", 99)) if isinstance(rule, dict) else (rule, rule)
        )
        add(Check("images_sent", lo <= n <= hi, f"images sent: {n}"))
    if expect.get("answer_contains_number"):
        last = next(
            (
                c.get("output")
                for c in reversed(calls)
                if c.get("name") == "query_table" and c.get("ok")
            ),
            None,
        )
        values = _flat_numbers(((last or {}).get("data") or {}).get("first_row") or {})
        heard = set(_numbers(_BRACKETS.sub(" ", text)))
        ok = bool(values) and any(_close(n, values) for n in heard)
        add(Check("answer_contains_number", ok, f"server: {sorted(values)}, said: {sorted(heard)}"))
    if "paragraphs_min" in expect:  # Phase 7.5 report narratives
        n = int(obs.data.get("paragraphs", 0))
        add(Check("paragraphs_min", n >= int(expect["paragraphs_min"]), f"paragraphs: {n}"))
    if expect.get("cites_from_facts"):
        allowed = {str(c).lower() for c in obs.data.get("citables", [])}
        cites = [str(c) for c in obs.data.get("cites", [])]
        bad = [c for c in cites if c.lower() not in allowed]
        add(Check("cites_from_facts", bool(cites) and not bad, f"bad: {bad}"))
    for secret in expect.get("no_leak", []):
        in_text = _low(secret) in lt and _low(secret) not in _low(asked)
        in_tools = _low(secret) in json.dumps(outputs, ensure_ascii=False).lower()
        add(Check(f"no_leak:{secret}", not in_text and not in_tools, "leaked"))

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
