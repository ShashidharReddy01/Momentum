"""Spec §11.1: the sample-file builder. The builders live in ``momentum.files.samples`` so the
AI eval workspace and ``momentum seed --onboarding`` can use them too; tests import them here."""

from momentum.files.samples import *  # noqa: F403
from momentum.files.samples import SAMPLES  # noqa: F401
