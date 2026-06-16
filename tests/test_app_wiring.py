"""Smoke test: the whole app (routes + deps + pollers) assembles and wires
without errors. Catches broken imports / DI mistakes after the repository split."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_main_imports_and_builds_pollers():
    import main  # noqa: F401

    assert main.app is not None
    # Each poller constructs with its injected repositories/services.
    events, eval_wake, friend, sweeper = main._build_pollers()
    assert events.name == "events_poller"
    assert eval_wake.name == "eval_wake_poller"
    assert friend.name == "friend_poller"
    assert sweeper.name == "checkout_sweeper"


def test_all_routers_present():
    import main

    paths = {r.path for r in main.app.routes}
    for expected in (
        "/health",
        "/api/oauth/exchange",
        "/api/register",
        "/api/credentials",
        "/api/notifications",
        "/api/checkin",
        "/api/checkins",
    ):
        assert expected in paths
