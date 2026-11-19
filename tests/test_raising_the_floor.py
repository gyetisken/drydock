"""Work that is not allowed to be done cheaply, however it was asked for.

`policy.py` has had `at_least` since profiles existed, with a docstring
saying why it matters - "the cost of being wrong about a migration is not
symmetrical with the cost of twenty extra minutes" - and nothing has ever
called it. The profile came from a settings file and the task was never
read. A one-line typo fix and a database migration got the same ceremony:
whichever one this person had selected.

This does not try to be a classifier, and that is deliberate. Every
production coding agent - Factory's Spec Mode, Cline's Plan mode, Aider's
architect - makes a person choose between the fast path and the planned
one, because classifying from a sentence is guessing from the weakest
signal anybody has. What this does instead is narrower and can be argued
with: it refuses the cheap road for a handful of specific, nameable kinds
of work, and says which words did it.

The asymmetry is the whole case. Reading a one-line fix too carefully
wastes twenty minutes. Treating a migration as a one-line fix loses data.
"""

import pytest

from drydock.policy import (
    BALANCED,
    DEEP,
    FAST,
    at_least,
    floor_for,
    of,
)


class TestWhatCannotBeDoneCheaply:
    @pytest.mark.parametrize(
        "task,names",
        [
            ("migrate the database to postgres", "a migration"),
            ("add a column to the orders table", "a migration"),
            ("backfill the created_at values", "a migration"),
            # Both labels are true of this one and the floor is the same
            # either way; what it is called is what it does to the data.
            ("drop the legacy orders table", "removing data"),
            ("implement login with JWT", "who is allowed in"),
            ("add a password reset flow", "who is allowed in"),
            ("store the api key for the weather service", "who is allowed in"),
            ("take a payment with stripe at checkout", "money"),
            ("refund the last order", "money"),
            ("let admins delete user accounts", "removing data"),
            ("purge the uploads older than a year", "removing data"),
        ],
    )
    def test_it_is_raised_and_says_why(self, task, names):
        raised = floor_for(task)

        assert raised.floor == DEEP
        assert names in raised.why
        assert '"' in raised.why, "the words that did it have to be quoted"


class TestWhatIsLeftAlone:
    """The false positives matter more than the misses here. A floor that
    fires on ordinary work is a floor somebody turns off."""

    @pytest.mark.parametrize(
        "task",
        [
            "add a logout button to the navbar",
            "change the heading colour to blue",
            "fix the typo in the footer",
            "rename the config key",
            "build a landing page for a coffee roaster",
            # The first page this was tried on names a price three times
            # and handles no money at all.
            "show the price on the card",
            "three coffee cards with name, roast notes and price",
            # A deleted source file is in git, and the item that deleted it
            # is one revert away.
            "delete the unused css file",
            "remove the old header component",
        ],
    )
    def test_ordinary_work_keeps_whatever_was_asked_for(self, task):
        assert floor_for(task).floor == ""
        assert floor_for(task).why == ""

    def test_nothing_at_all_is_nothing(self):
        assert not floor_for("")
        assert not floor_for(None)


class TestItOnlyEverRaises:
    def test_a_fast_job_that_touches_a_migration_is_raised(self):
        raised = floor_for("migrate the users table to the new schema")
        assert at_least(of(FAST), raised.floor).profile == DEEP

    def test_a_deep_job_stays_deep(self):
        assert at_least(of(DEEP), DEEP).profile == DEEP

    def test_nothing_raising_it_leaves_it_exactly_alone(self):
        """An empty floor used to read as BALANCED through `.get(floor, 1)`
        and quietly *lower* a job somebody asked to have done fast - the
        one thing this function says it never does. It only showed when
        something started passing "" to mean "nothing raised it"."""
        for profile in (FAST, BALANCED, DEEP):
            assert at_least(of(profile), "").profile == profile

    def test_what_it_raises_to_is_a_real_profile(self):
        raised = floor_for("add a column to orders")
        assert of(raised.floor).profile == raised.floor


class TestTheRunIsTold:
    """A floor nobody can see is a floor nobody can argue with."""

    def test_the_reason_reaches_the_session(self, tmp_path, monkeypatch):
        from drydock import workspace

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
        monkeypatch.setattr(workspace, "HOME", tmp_path)
        seen = {}

        class Fake:
            def __init__(self, *a, **k):
                seen.update(k)

            def start(self, auto_run=False):
                pass

            run = None

        monkeypatch.setattr(workspace, "Session", Fake)
        workspace.Workspace().start(
            tmp_path, "migrate the orders table", [], 0.0, profile="fast"
        )

        assert seen["policy"].profile == DEEP
        assert "a migration" in seen["floor"]

    def test_an_ordinary_job_carries_no_reason(self, tmp_path, monkeypatch):
        from drydock import workspace

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
        monkeypatch.setattr(workspace, "HOME", tmp_path)
        seen = {}

        class Fake:
            def __init__(self, *a, **k):
                seen.update(k)

            def start(self, auto_run=False):
                pass

            run = None

        monkeypatch.setattr(workspace, "Session", Fake)
        workspace.Workspace().start(
            tmp_path, "fix the footer typo", [], 0.0, profile="fast"
        )

        assert seen["policy"].profile == FAST
        assert seen["floor"] == ""

    def test_it_is_announced_on_the_feed(self):
        """Not only recorded. Somebody watching a job take the long road
        is owed the sentence that put it there."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src" / "drydock" / "session.py"
        ).read_text()
        assert '"policy.raised"' in source
        assert "why=self.floor" in source
