"""The record of one job, and what it is allowed to stop for.

Two things here have gone wrong in ways that looked like success. A cap in
dollars stopped a four-item site after three on a subscription where
nothing is billed per run - reported, at the time, as "rolled back". And a
station that reported no usage took the whole run down with an attribute
error on the counting, which is the least important thing happening.
"""

from pathlib import Path

import pytest

from drydock.run import Run


class Usage:
    def __init__(self, into=0, out=0, cached=0, dollars=0.0):
        self.input_tokens = into
        self.output_tokens = out
        self.cached_tokens = cached
        self.dollars = dollars


def a_run(tmp_path: Path, **kw) -> Run:
    run = Run.start(tmp_path, "build something")
    for key, value in kw.items():
        setattr(run, key, value)
    return run


class TestCounting:
    def test_what_a_station_spent_is_added_up(self, tmp_path):
        run = a_run(tmp_path)
        run.spend(Usage(into=1000, out=200, dollars=0.5))
        run.spend(Usage(into=500, out=100, dollars=0.25))

        assert run.tokens_in == 1500
        assert run.tokens_out == 300
        assert run.dollars == 0.75

    def test_a_station_that_reported_nothing_is_not_an_error(self, tmp_path):
        """It is not even unusual - a worker stopped by the wall clock has
        no final reply to read a count off. Counting must never be the thing
        that ends a run."""
        run = a_run(tmp_path)
        run.spend(None)
        assert run.tokens_in == 0

    def test_a_usage_without_a_price_still_counts_its_tokens(self, tmp_path):
        run = a_run(tmp_path)
        run.spend(Usage(into=10, out=5))
        assert run.tokens_in == 10
        assert run.dollars == 0.0


class TestWhatIsLeft:
    def test_no_budget_means_no_limit(self, tmp_path):
        """The subscription engine bills nothing per run. A cap of zero has
        to mean 'no cap', not 'stop immediately'."""
        run = a_run(tmp_path, budget=0.0)
        assert run.left == float("inf")

    def test_a_budget_counts_down(self, tmp_path):
        run = a_run(tmp_path, budget=4.0)
        run.spend(Usage(dollars=1.5))
        assert run.left == 2.5

    def test_it_never_goes_below_nothing(self, tmp_path):
        """Negative room left reads as credit to anything comparing it."""
        run = a_run(tmp_path, budget=1.0)
        run.spend(Usage(dollars=3.0))
        assert run.left == 0.0


class TestItSurvivesBeingClosed:
    def test_a_run_is_written_and_read_back(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run = a_run(tmp_path, direction="One amber accent.")
        run.spend(Usage(into=100, out=50, dollars=0.2))
        run.save()

        back = Run.load(run.id)
        assert back.direction == "One amber accent."
        assert back.tokens_in == 100
        assert back.dollars == 0.2

    def test_the_loaded_skill_bodies_are_not_written_to_disk(
        self, tmp_path, monkeypatch
    ):
        """They come from files, and a copy in the record is a copy that goes
        stale the moment a skill is corrected."""
        monkeypatch.chdir(tmp_path)
        run = a_run(tmp_path, skills=["greenfield"])
        run.skills_loaded = [object()]
        run.save()

        assert "skills_loaded" not in run.path.read_text()
        assert Run.load(run.id).skills == ["greenfield"]

    def test_the_newest_run_is_the_one_most_recently_written(
        self, tmp_path, monkeypatch
    ):
        """Not the one whose name sorts last. Names are local clock times,
        and on the hour the clocks go back the newest would sort an hour
        early."""
        monkeypatch.chdir(tmp_path)
        first = a_run(tmp_path)
        first.id = "20261117-020000"
        first.save()

        second = a_run(tmp_path)
        second.id = "20261117-013000"  # written later, named earlier
        second.task = "the one that matters"
        second.save()

        assert Run.latest().task == "the one that matters"

    def test_no_runs_at_all_says_so(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            Run.latest()


class TestTheComparison:
    def test_a_subscription_run_is_left_out_rather_than_guessed_at(self, tmp_path):
        """It reports a price and no tokens, so there is nothing to price."""
        run = a_run(tmp_path, dollars=7.74)
        assert run.as_opus == 0.0

    def test_an_api_run_is_priced_as_if_nothing_had_been_routed(self, tmp_path):
        run = a_run(tmp_path)
        run.spend(Usage(into=1_000_000, out=0))
        assert run.as_opus > 0
