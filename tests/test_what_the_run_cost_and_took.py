"""What each station cost and how long it took.

Run 20261124-142030 spent $3.40 and recorded one number: $3.40. Its
`tokens_in` and `tokens_out` were zero, no event log was written at all
because only the application writes one, and the per-item split had to
be reconstructed afterwards from git commit timestamps. None of the
questions worth asking about an 8m52s run could be answered from its own
record.

Deterministic: no CLI, no model, no clock that matters.
"""

import inspect

from drydock import cli, orchestrate, session
from drydock.run import Run, Spent


class Usage:
    def __init__(self, dollars=0.25, went_in=100, came_out=50):
        self.input_tokens = went_in
        self.output_tokens = came_out
        self.cached_tokens = 0
        self.dollars = dollars


def a_run() -> Run:
    from pathlib import Path

    return Run.start(Path("/tmp/nowhere"), "a task")


class TestOneCallCountsOnce:
    def test_the_totals_and_the_timeline_agree(self):
        """The line is written by the same call that adds to the totals,
        so a station cannot be counted in one and not the other."""
        run = a_run()
        run.spend(Usage(0.25), station="analyst", seconds=12.5)
        run.spend(Usage(0.50), station="engineer", item=1, attempt=1, seconds=60.0)
        run.spend(Usage(0.10), station="reviewer", item=1, seconds=9.0)
        assert round(sum(line.dollars for line in run.timeline), 4) == round(
            run.dollars, 4
        )

    def test_a_station_that_said_nothing_is_not_an_error(self):
        run = a_run()
        run.spend(None, station="reviewer")
        assert run.timeline == []
        assert run.dollars == 0.0

    def test_an_unlabelled_caller_still_counts(self):
        """Naming the station is optional. Counting is not."""
        run = a_run()
        run.spend(Usage(0.3))
        assert run.dollars == 0.3
        assert run.timeline == []

    def test_a_bare_number_of_dollars_counts_too(self):
        """The critic returns a float rather than a usage object, and
        used to be added straight to `run.dollars` - outside the token
        totals and outside any record of what the run did."""
        run = a_run()
        run.spend(0.4, station="critic", item=2, seconds=9.0)
        assert run.dollars == 0.4
        assert run.timeline[0].station == "critic"
        assert run.timeline[0].dollars == 0.4

    def test_nothing_writes_to_dollars_behind_the_chokepoint(self):
        for module in (orchestrate, session):
            assert "run.dollars +=" not in inspect.getsource(module)


class TestEveryStationIsNamed:
    EXPECTED = ("analyst", "planner", "engineer", "reviewer", "critic")

    def test_the_cli_names_the_two_it_runs_itself(self):
        source = cli.__file__ and inspect.getsource(cli)
        assert 'station="analyst"' in source
        assert 'station="planner"' in source

    def test_the_loop_names_the_rest(self):
        source = inspect.getsource(orchestrate)
        for station in ("engineer", "reviewer", "critic"):
            assert f'station="{station}"' in source

    def test_an_engineer_attempt_is_told_apart_from_its_retry(self):
        source = inspect.getsource(orchestrate)
        assert "attempt=attempt," in source
        run = a_run()
        run.spend(Usage(), station="engineer", item=1, attempt=1)
        run.spend(Usage(), station="engineer", item=1, attempt=2)
        assert [line.attempt for line in run.timeline] == [1, 2]

    def test_the_planner_is_told_apart_when_it_answers_mid_item(self):
        """Two different things wearing one name: planning the work, and
        answering an engineer that stopped to ask."""
        source = inspect.getsource(orchestrate)
        assert 'station="planner-answer"' in source
        assert 'station="planner-split"' in source

    def test_the_app_names_them_as_well(self):
        """Equally observable, or the measurement only exists on the
        path nobody used to take."""
        source = inspect.getsource(session)
        assert "station=who.lower()" in source


class TestItSaysHowLongAsWellAsHowMuch:
    def test_duration_is_recorded_per_call(self):
        run = a_run()
        run.spend(Usage(), station="engineer", item=1, attempt=1, seconds=61.4)
        assert run.timeline[0].seconds == 61.4

    def test_the_loop_measures_rather_than_estimates(self):
        source = inspect.getsource(orchestrate)
        assert "time.monotonic()" in source
        assert source.count("seconds=time.monotonic()") >= 2

    def test_the_app_measures_from_when_the_station_started(self):
        source = inspect.getsource(session)
        assert "self._began[who] = time.monotonic()" in source
        assert "self._began.pop(who, None)" in source

    def test_a_summary_adds_up_per_station(self):
        run = a_run()
        run.spend(Usage(0.5), station="engineer", item=1, attempt=1, seconds=60.0)
        run.spend(Usage(0.7), station="engineer", item=1, attempt=2, seconds=45.0)
        run.spend(Usage(0.1), station="reviewer", item=1, seconds=9.0)
        held = run.by_station()
        assert held["engineer"] == {"calls": 2, "seconds": 105.0, "dollars": 1.2}
        assert held["reviewer"]["calls"] == 1


class TestTheExistingRecordIsUnchanged:
    def test_the_old_fields_are_all_still_there(self):
        for field in ("dollars", "tokens_in", "tokens_out", "tokens_cached"):
            assert field in Run.model_fields

    def test_a_record_written_before_this_still_loads(self):
        """The timeline defaults to empty rather than being required, so
        every run already on disk reads back."""
        run = Run.model_validate(
            {
                "id": "20260101-000000",
                "repo": "/tmp/x",
                "task": "t",
                "started": "2026-01-01T00:00:00+00:00",
                "dollars": 1.0,
            }
        )
        assert run.timeline == []
        assert run.by_station() == {}
        assert run.profile_used == ""

    def test_a_timeline_line_carries_what_a_person_would_ask(self):
        assert set(Spent.model_fields) >= {
            "station",
            "item",
            "attempt",
            "seconds",
            "dollars",
        }


class TestGettingReadyIsToldApartFromWorking:
    """On run 20261124-153354 the preparation was 323 of 497 seconds and
    $1.53 of $2.22. Nothing in the record said so; it had to be added up
    by hand from the station lines."""

    def a_run_like_that(self) -> Run:
        run = a_run()
        run.spend(Usage(1.00), station="analyst", seconds=227.0)
        run.spend(Usage(0.38), station="planner", seconds=45.6)
        run.spend(Usage(0.15), station="planner", seconds=50.6)
        run.spend(Usage(0.69), station="engineer", item=1, attempt=1, seconds=109.8)
        return run

    def test_the_two_halves_are_separately_measurable(self):
        split = self.a_run_like_that().phases()
        assert split["preparation"]["calls"] == 3
        assert split["preparation"]["seconds"] == 323.2
        assert split["preparation"]["dollars"] == 1.53
        assert split["execution"]["calls"] == 1
        assert split["execution"]["seconds"] == 109.8

    def test_they_add_up_to_the_whole(self):
        run = self.a_run_like_that()
        split = run.phases()
        assert round(
            split["preparation"]["dollars"] + split["execution"]["dollars"], 4
        ) == round(run.dollars, 4)

    def test_a_planner_answering_mid_item_is_work_not_preparation(self):
        """It happens because an item is being worked on and would not
        happen without one."""
        run = a_run()
        run.spend(Usage(0.1), station="planner-answer", item=1, attempt=2, seconds=20.0)
        run.spend(Usage(0.1), station="planner-split", item=1, seconds=15.0)
        split = run.phases()
        assert split["preparation"]["calls"] == 0
        assert split["execution"]["calls"] == 2

    def test_every_station_the_loop_names_lands_on_one_side_or_the_other(self):
        run = a_run()
        for station in ("analyst", "planner", "engineer", "reviewer", "critic"):
            run.spend(Usage(0.1), station=station, seconds=1.0)
        split = run.phases()
        assert split["preparation"]["calls"] + split["execution"]["calls"] == 5

    def test_an_empty_run_says_zero_rather_than_raising(self):
        split = a_run().phases()
        assert split["preparation"]["calls"] == 0
        assert split["execution"]["dollars"] == 0.0


class TestAPlanIsNotPaidForTwice:
    """Measured by accident: two planner calls on run 20261124-153354,
    $0.38 and $0.15, and the second one's plan is the one that ran."""

    def test_the_guard_is_there(self):
        source = inspect.getsource(cli._cmd_plan)
        assert "if run.plan and not getattr(args" in source
        assert "--again" in inspect.getsource(cli) or "again" in source

    def test_it_says_what_to_do_instead(self):
        source = inspect.getsource(cli._cmd_plan)
        assert "Pass --again" in source
        assert "drydock run" in source

    def test_planning_over_is_still_possible_when_asked(self):
        source = inspect.getsource(cli)
        assert '"--again"' in source
        assert "costs another planner call" in source

    def test_a_run_with_no_plan_is_not_blocked(self):
        source = inspect.getsource(cli._cmd_plan)
        # The guard reads the plan, so a run without one falls through.
        assert source.index("if run.plan and not") < source.index('print(f"planning:')
