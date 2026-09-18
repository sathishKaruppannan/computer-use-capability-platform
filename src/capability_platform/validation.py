"""Shared input-validation helpers used across every goal-consuming entry point -- the Intent
Analyzer pipeline (agent/intent_analyzer.py) and the legacy computer-use discovery agent
(agent/discovery.py) -- so a limit set once in Settings is enforced the same way no matter which
path a goal comes in through (CLI, REST, or a future caller neither of those anticipates)."""

from __future__ import annotations

from capability_platform.settings import settings


class GoalTooLongError(ValueError):
    def __init__(self, length: int, max_length: int) -> None:
        self.length = length
        self.max_length = max_length
        super().__init__(
            f"Goal is {length} characters long, which exceeds the {max_length}-character limit "
            "for this demo. Please shorten it."
        )


def validate_goal_length(goal: str) -> None:
    if len(goal) > settings.max_goal_length:
        raise GoalTooLongError(len(goal), settings.max_goal_length)
