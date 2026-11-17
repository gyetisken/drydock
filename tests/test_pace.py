"""Where a run's minutes went.

Every time this program has felt slow the answer has been a guess, and a
guess from the person who built it is the least reliable kind. The events
already carry the times, so the breakdown is arithmetic - which means it
can be wrong in the quiet way arithmetic is wrong, and that is what this
pins.
"""

from drydock.pace import _said, read


def event(kind: str, at: str, **data) -> dict:
    return {"kind": kind, "at": at, **data}


def a_run(*events) -> list[dict]:
    return [event("run.started", "10:00:00"), *events]


class TestHowItReads:
    def test_under_ninety_seconds_is_said_in_seconds(self):
        assert _said(43) == "43s"

    def test_the_minutes_are_floored_not_rounded(self):
        """Rounding 392 seconds reads '7m 32s' - a minute longer than it
        took, and disagreeing with its own seconds."""
        assert _said(392) == "6m 32s"

    def test_the_seconds_keep_their_place(self):
        assert _said(3605) == "60m 05s"

    def test_nothing_measured_says_nothing(self):
        assert read([]).lines() == []


class TestOneItem:
    def test_working_and_being_checked_are_separated(self):
        """The whole point. Four minutes of writing and three of checking is
        a different problem from seven minutes of writing."""
        pace = read(
            a_run(
                event("item.start", "10:00:10", id=1),
                event("gate", "10:04:10", id=1, who="inspector"),
                event("gate", "10:06:10", id=1, who="reviewer"),
                event("item.done", "10:07:10", id=1, outcome="done"),
            )
        )
        spell = pace.items[0]
        assert spell.seconds == 420
        assert spell.working == 240
        assert spell.checking == 180

    def test_the_first_gate_to_speak_ends_the_writing(self):
        """Anything after it is the harness, not the engineer."""
        pace = read(
            a_run(
                event("item.start", "10:00:00", id=1),
                event("gate", "10:01:00", id=1, who="inspector"),
                event("gate", "10:03:00", id=1, who="critic"),
                event("item.done", "10:03:30", id=1, outcome="done"),
            )
        )
        assert pace.items[0].working == 60

    def test_an_item_that_never_reached_a_gate_was_all_writing(self):
        """Stopped, or stopped itself. None of that time was checking."""
        pace = read(
            a_run(
                event("item.start", "10:00:00", id=1),
                event("item.done", "10:12:00", id=1, outcome="blocked"),
            )
        )
        assert pace.items[0].working == 720
        assert pace.items[0].checking == 0

    def test_a_question_counts_as_checking_not_writing(self):
        """Nothing is being written while the planner is being asked."""
        pace = read(
            a_run(
                event("item.start", "10:00:00", id=1),
                event("gate", "10:01:00", id=1, who="asked"),
                event("gate", "10:01:30", id=1, who="answered"),
                event("item.done", "10:05:00", id=1, outcome="done"),
            )
        )
        assert pace.items[0].working == 60


class TestWhileItIsStillGoing:
    def test_an_item_in_flight_reports_its_time_so_far(self):
        """Which is the question somebody watching is actually asking."""
        pace = read(
            a_run(
                event("item.start", "10:00:00", id=1),
                event("agent.tool", "10:04:00", id=1),
            )
        )
        assert pace.items[0].seconds == 240
        assert pace.items[0].outcome == "working"

    def test_it_says_so(self):
        pace = read(a_run(event("item.start", "10:00:00", id=1)))
        assert "still going" in pace.lines()[-1]


class TestARunPickedBackUp:
    def test_only_the_sitting_somebody_watched_is_measured(self):
        """One log holds a run and every time it was resumed. Adding the
        attempts together measures nothing anybody experienced."""
        pace = read(
            [
                event("run.started", "09:00:00"),
                event("item.start", "09:00:10", id=1),
                event("item.done", "09:30:00", id=1, outcome="blocked"),
                event("run.started", "10:00:00"),
                event("item.start", "10:00:10", id=1),
                event("item.done", "10:02:10", id=1, outcome="done"),
            ]
        )
        assert pace.items[0].seconds == 120
        assert pace.seconds == 130

    def test_a_replayed_result_is_not_counted_as_work(self):
        """A resume re-announces what already landed so the window can be
        rebuilt. None of it happened in this sitting."""
        pace = read(
            [
                event("run.started", "10:00:00"),
                event("item.done", "10:00:00", id=1, outcome="done"),
                event("item.start", "10:00:05", id=2),
                event("item.done", "10:03:05", id=2, outcome="done"),
            ]
        )
        assert [s.item for s in pace.items] == [2]


class TestBeforeAnyCodeIsWritten:
    def test_the_time_up_to_the_plan_is_called_out(self):
        """Reading the repository, deciding how it looks, writing the plan.
        It is a real share of a short run and nothing showed it."""
        pace = read(
            a_run(
                event("plan.ready", "10:02:30"),
                event("item.start", "10:02:35", id=1),
                event("item.done", "10:05:35", id=1, outcome="done"),
            )
        )
        assert pace.before_the_plan == 150
        assert "before any code was written" in pace.lines()[1]


class TestItNeverRefusesToReport:
    def test_an_event_with_an_unreadable_time_is_skipped(self):
        pace = read(
            a_run(
                event("item.start", "10:00:00", id=1),
                event("gate", "not a time", id=1, who="reviewer"),
                event("item.done", "10:02:00", id=1, outcome="done"),
            )
        )
        assert pace.items[0].seconds == 120

    def test_a_gate_for_an_item_that_never_started_does_not_crash(self):
        assert read(a_run(event("gate", "10:01:00", id=9, who="reviewer"))).items

    def test_a_run_that_crosses_midnight_is_not_negative(self):
        pace = read(
            [
                event("run.started", "23:58:00"),
                event("item.start", "23:59:00", id=1),
                event("item.done", "00:02:00", id=1, outcome="done"),
            ]
        )
        assert pace.items[0].seconds == 180

    def test_an_impossible_split_reports_the_part_that_is_true(self):
        """An item worked in a worktree beside its neighbours can produce a
        checking time longer than the item. Better to report less than to
        report a number that cannot be."""
        pace = read(
            [
                event("run.started", "10:00:00"),
                event("gate", "10:00:30", id=1, who="reviewer"),
                event("item.start", "10:05:00", id=1),
                event("item.done", "10:06:00", id=1, outcome="done"),
            ]
        )
        assert pace.items[0].checking == 0
        assert pace.items[0].seconds == 60
