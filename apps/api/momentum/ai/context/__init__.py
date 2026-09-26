"""Context builders (ai-architecture §5, S3.1.5): compact, permission-checked, token-budgeted
text blocks that prompts are assembled from. See ``builders.py``."""

from momentum.ai.context.builders import (
    BUDGETS,
    Screen,
    project_ctx,
    retrieval_ctx,
    screen_ctx,
    system_base,
    task_ctx,
    user_ctx,
)
from momentum.ai.context.tokens import Block, estimate_tokens

__all__ = [
    "BUDGETS",
    "Block",
    "Screen",
    "estimate_tokens",
    "project_ctx",
    "retrieval_ctx",
    "screen_ctx",
    "system_base",
    "task_ctx",
    "user_ctx",
]
