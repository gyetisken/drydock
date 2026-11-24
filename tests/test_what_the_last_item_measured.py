"""What an item is told about the items before it.

Run 20261124-142030: the second item spent 32 tool calls and a second
attempt reading a query plan the first item's engineer had already read,
and then both it and the reviewer reported that the item it was given
rested on a premise that was not true. Measured afterwards: the first
item alone passes the hidden suite 16/16 and the public suite 27/27, so
the second item changed nothing any test can see.

`handoff` stopped at the survey, which is read before anything is
touched. The measurements an item makes while the run is going went
nowhere.

This decides nothing. It carries evidence; the engineer judges.
"""

import inspect
from pathlib import Path

import pytest

from drydock.models import Inventory, Item, ItemResult, Outcome
from drydock.run import Run


def a_run() -> Run:
    run = Run.start(Path("/tmp/nowhere"), "paging returns every article once")
    run.inventory = Inventory(
        language="Python",
        build_tool="uv",
        build_command="uv sync",
        test_command="uv run pytest -q",
        source_files=3,
        test_files=1,
        findings=[],
        risks=[],
    )
    return run


def landed(n: int, title: str, note: str, noticed: list[str], **kw) -> ItemResult:
    return ItemResult(
        item=Item(id=n, title=title, rationale="r", files=["x"], verify_with="v"),
        outcome=kw.get("outcome", Outcome.DONE),
        attempts=kw.get("attempts", 1),
        note=note,
        noticed=noticed,
    )


THE_FINDING = (
    "engineer: id is this table's rowid and SQLite carries the rowid as every "
    "index's trailing key, so the old index already orders by (created_at, id)"
)


class TestItIsCarriedForward:
    def test_nothing_is_said_before_anything_has_landed(self):
        assert a_run().established == ""

    def test_what_an_item_measured_reaches_the_next_one(self):
        run = a_run()
        run.results.append(
            landed(1, "Cursor carries identity", "27 tests pass", [THE_FINDING])
        )
        assert "already orders by (created_at, id)" in run.established

    def test_it_arrives_through_the_handoff_the_engineer_already_reads(self):
        """No new parameter and no new station: the engineer is handed
        `run.handoff` on every item already."""
        run = a_run()
        run.results.append(
            landed(1, "Cursor carries identity", "27 tests pass", [THE_FINDING])
        )
        assert "already orders by" in run.handoff
        assert "run.handoff" in inspect.getsource(
            __import__("drydock.orchestrate", fromlist=["x"])
        )

    def test_the_item_and_its_outcome_are_named(self):
        run = a_run()
        run.results.append(
            landed(1, "Cursor carries identity", "27 tests pass", [THE_FINDING])
        )
        said = run.established
        assert "Item 1, Cursor carries identity" in said
        assert "27 tests pass" in said

    def test_what_the_reviewer_saw_comes_too(self):
        run = a_run()
        run.results.append(
            landed(1, "t", "ok", ["reviewer: the new one may be redundant"])
        )
        assert "may be redundant" in run.established


class TestItIsBoundedAndHonest:
    def test_only_the_last_few_items(self):
        run = a_run()
        for n in range(1, 8):
            run.results.append(landed(n, f"item {n}", "ok", [f"engineer: finding {n}"]))
        assert run.established.count("- Item ") == Run.CARRIED_ITEMS
        assert "finding 1" not in run.established
        assert "finding 7" in run.established

    def test_only_a_few_lines_from_each(self):
        run = a_run()
        run.results.append(
            landed(1, "t", "ok", [f"engineer: line {n}" for n in range(10)])
        )
        assert run.established.count("    - ") == Run.CARRIED_LINES

    def test_a_long_line_is_cut_rather_than_carried_whole(self):
        run = a_run()
        run.results.append(landed(1, "t", "ok", ["engineer: " + "x" * 2000]))
        for line in run.established.splitlines():
            assert len(line) < Run.CARRIED_WIDTH + 40

    @pytest.mark.parametrize("outcome", [Outcome.REVERTED, Outcome.BLOCKED])
    def test_work_that_was_thrown_away_is_not_carried(self, outcome):
        """A reverted item's notes describe code that is not there."""
        run = a_run()
        run.results.append(
            landed(1, "t", "no", ["engineer: nonsense"], outcome=outcome, attempts=2)
        )
        assert run.established == ""

    def test_an_item_that_noticed_nothing_adds_nothing(self):
        run = a_run()
        run.results.append(landed(1, "t", "ok", []))
        assert run.established == ""

    def test_a_run_with_no_survey_still_says_nothing(self):
        """`handoff` needs an inventory; this must not make it raise."""
        run = Run.start(Path("/tmp/nowhere"), "t")
        run.results.append(landed(1, "t", "ok", [THE_FINDING]))
        assert run.handoff == ""


class TestItDecidesNothing:
    def test_it_does_not_skip_an_item(self):
        """Nothing here removes work. The words are chosen so an engineer
        reads evidence rather than an instruction."""
        said = Run.established.__doc__
        assert "decides nothing and skips" in said
        run = a_run()
        run.results.append(landed(1, "t", "ok", [THE_FINDING]))
        carried = run.established
        assert "it is evidence, not an instruction" in carried
        assert "the item is still yours to do" in carried

    def test_public_tests_passing_is_not_the_signal(self):
        """Explicitly not a rule. A green suite says nothing about
        whether an item is redundant."""
        said = Run.established.__doc__
        assert "Public tests passing is not evidence of anything here" in " ".join(
            said.split()
        )

    def test_it_asks_for_a_report_rather_than_silence(self):
        run = a_run()
        run.results.append(landed(1, "t", "ok", [THE_FINDING]))
        assert "say so in your report" in run.established

    def test_no_new_model_call_is_made(self):
        """A property over the record. No agent, no round, no station."""
        source = inspect.getsource(Run.established.fget)
        for calling in ("Agent(", "ClaudeCodeEngine", "structured(", "answer("):
            assert calling not in source
