"""S5.1.2: what an agent may do with a write it wants to make (ai-architecture §4).

| risk   | suggest      | confirm | auto                                        |
|--------|--------------|---------|---------------------------------------------|
| low    | suggestion   | propose | apply                                       |
| medium | suggestion   | propose | propose (apply if the workspace allows it)  |
| high   | suggestion   | propose | propose                                     |

A ``suggest`` agent's comments are its suggestions, so ``add_comment`` is applied as is.
Content from outside the workspace (a form submission, an integration) caps autonomy at
``confirm`` (§8).
"""

from __future__ import annotations

from typing import Literal

Decision = Literal["apply", "propose", "suggest"]
AUTONOMY_RANK = {"suggest": 0, "confirm": 1, "auto": 2}
SUGGESTION_TOOL = "add_comment"


def effective_autonomy(autonomy: str, *, external: bool) -> str:
    if external and AUTONOMY_RANK.get(autonomy, 0) > AUTONOMY_RANK["confirm"]:
        return "confirm"
    return autonomy


def decide(autonomy: str, risk: str, tool: str, *, allow_medium_auto: bool = False) -> Decision:
    if autonomy == "suggest":
        return "apply" if tool == SUGGESTION_TOOL and risk == "low" else "suggest"
    if autonomy == "auto":
        if risk == "low" or (risk == "medium" and allow_medium_auto):
            return "apply"
        return "propose"
    return "propose"
