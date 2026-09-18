from capability_platform.settings import settings
from capability_platform.validation import GoalTooLongError, validate_goal_length


def test_validate_goal_length_allows_goal_at_the_limit():
    goal = "x" * settings.max_goal_length
    validate_goal_length(goal)  # must not raise


def test_validate_goal_length_rejects_goal_over_the_limit():
    goal = "x" * (settings.max_goal_length + 1)
    try:
        validate_goal_length(goal)
        raise AssertionError("expected GoalTooLongError")
    except GoalTooLongError as exc:
        assert exc.length == settings.max_goal_length + 1
        assert exc.max_length == settings.max_goal_length
        assert str(settings.max_goal_length) in str(exc)
