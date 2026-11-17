"""The engineer stopping to ask rather than guessing.

An item that turns on a decision nobody took has three possible endings. It
can be guessed at, which produces work a gate throws away two minutes
later. It can be given up on, which ends the item at the same undecided
question it started from. Or the question can be put to whoever wrote the
item - which is only worth anything if it is bounded, if it does not spend
one of the two attempts, and if an answer of "that is not this item's job"
stops the item instead of letting it grow.
"""

from pathlib import Path

import pytest

from drydock import orchestrate
from drydock.models import Baseline, Check, Item, Outcome, Plan
from drydock.run import Run


def a_run(tmp_path: Path) -> Run:
    run = Run(
        id="20261117-000000",
        repo=str(tmp_path),
        task="show prices on the till",
        started="2026-11-17T00:00:00",
    )
    run.baseline = Baseline(builds=True, tests_run=1, tests_failed=0, tests_skipped=0)
    run.plan = Plan(
        summary="One item.",
        items=[
            Item(
                id=1,
                title="a till display",
                plain="The till shows what things cost.",
                rationale="because",
                files=["till.js"],
                verify_with="tests",
            )
        ],
    )
    return run


def asks(question: str) -> dict:
    return {"done": False, "summary": "", "files_changed": [], "question": question}


def finished() -> dict:
    return {
        "done": True,
        "summary": "wrote till.js",
        "files_changed": ["till.js"],
        "question": "",
    }


def gave_up() -> dict:
    return {"done": False, "summary": "could not do it", "files_changed": []}


class Fake:
    """Everything around the question, pinned to its simplest answer.

    Only one path is under test here, so the gates pass, the tests pass and
    the commit succeeds - and what is left visible is what was asked, who
    was told, and how many attempts it cost.
    """

    def __init__(self, monkeypatch, reports, said="the VAT-inclusive price"):
        self.reports, self.said = list(reports), said
        self.asked: list[str] = []
        self.briefed: list[str] = []
        self.gates: list[tuple[str, str]] = []

        monkeypatch.setattr(orchestrate, "work", self._work)
        monkeypatch.setattr(orchestrate, "answer", self._settle)
        monkeypatch.setattr(orchestrate, "Repo", _Quiet)
        monkeypatch.setattr(orchestrate, "detect", lambda path: _Chain())
        monkeypatch.setattr(orchestrate, "verify", lambda *a, **k: _Passed())
        monkeypatch.setattr(orchestrate, "look", lambda *a, **k: _Clean())
        monkeypatch.setattr(orchestrate, "_judge", lambda *a, **k: "")

    def _work(self, repo, task, item, build, failure="", *a, **k):
        self.briefed.append(failure)
        return (self.reports.pop(0) if self.reports else gave_up()), None

    def _settle(self, repo, plan, item, question, **k):
        self.asked.append(question)
        return self.said, None

    def run_it(self, run):
        return orchestrate._one_item(
            Path(run.repo),
            _Quiet(Path(run.repo)),
            run,
            run.plan.items[0],
            "claude",
            "opus",
            True,
            0.0,
            None,
            lambda item, who, ok, note: self.gates.append((who, note)),
        )[0]


class _Chain:
    build_command = "npm run build"
    test_command = "npm test"


class _Passed:
    passed = True
    reason = "2 tests pass"
    tests_run = 2
    check = Check(
        name="tests", command="npm test", passed=True, seconds=1.0, detail="2 pass"
    )


class _Clean:
    clean = True
    reason = "nothing to report"


class _Quiet:
    """A repository where committing and discarding always work."""

    def __init__(self, path):
        self.path = path

    def pending(self):
        return "+++ b/till.js\n+export const display = () => [];\n"

    def commit(self, message):
        return "abc1234"

    def discard(self):
        pass

    def sweep(self):
        pass


@pytest.fixture
def shop(tmp_path):
    return tmp_path


class TestItIsBounded:
    def test_the_question_goes_to_whoever_wrote_the_item(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [asks("raw price, or with VAT?"), finished()])
        result = fake.run_it(a_run(shop))

        assert fake.asked == ["raw price, or with VAT?"]
        assert result.outcome is Outcome.DONE

    def test_the_answer_reaches_the_engineer(self, shop, monkeypatch):
        """An answer nobody is told is the same as no answer."""
        fake = Fake(monkeypatch, [asks("raw, or with VAT?"), finished()])
        fake.run_it(a_run(shop))

        assert fake.briefed[0] == ""
        assert "the VAT-inclusive price" in fake.briefed[1]
        assert "You asked" in fake.briefed[1]

    def test_asking_does_not_spend_an_attempt(self, shop, monkeypatch):
        """Nothing was written, so nothing was tried. Charging an attempt
        for a question leaves one attempt for the work itself."""
        fake = Fake(monkeypatch, [asks("raw, or with VAT?"), finished()])
        result = fake.run_it(a_run(shop))

        assert result.attempts == 1

    def test_it_is_asked_at_most_once(self, shop, monkeypatch):
        """Two stations that can each reply to the other have no reason to
        ever stop."""
        fake = Fake(monkeypatch, [asks("one?"), asks("two?"), asks("three?")])
        fake.run_it(a_run(shop))

        assert fake.asked == ["one?"]

    def test_a_second_question_ends_the_item_rather_than_looping(
        self, shop, monkeypatch
    ):
        fake = Fake(monkeypatch, [asks("one?"), asks("two?")])
        result = fake.run_it(a_run(shop))

        assert result.outcome is Outcome.BLOCKED


class TestWhenTheAnswerIsThatItIsNotThisItem:
    def test_work_belonging_elsewhere_stops_this_item(self, shop, monkeypatch):
        """The failure guarded against here is an item quietly absorbing its
        neighbours because the engineer asked whether it should."""
        fake = Fake(
            monkeypatch,
            [asks("should I write the printer driver too?"), finished()],
            said="[this belongs in another item] item 4 does the printer",
        )
        result = fake.run_it(a_run(shop))

        assert result.outcome is Outcome.BLOCKED
        assert len(fake.briefed) == 1

    def test_both_halves_of_the_exchange_are_in_the_note(self, shop, monkeypatch):
        """Whoever reads the run afterwards needs what was asked and what
        was said, not a verdict."""
        fake = Fake(
            monkeypatch,
            [asks("whose job is the printer?")],
            said="[this belongs in another item] item 4",
        )
        result = fake.run_it(a_run(shop))

        assert "whose job is the printer?" in result.note
        assert "item 4" in result.note


class TestItIsVisible:
    def test_the_exchange_is_announced(self, shop, monkeypatch):
        """It happens between two stations with nobody watching, and an
        unexplained pause is the thing this program is trying not to be."""
        fake = Fake(monkeypatch, [asks("raw, or with VAT?"), finished()])
        fake.run_it(a_run(shop))

        assert ("asked", "raw, or with VAT?") in fake.gates
        assert ("answered", "the VAT-inclusive price") in fake.gates


class TestTheOrdinaryCase:
    def test_an_item_with_no_question_is_untouched(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [finished()])
        result = fake.run_it(a_run(shop))

        assert fake.asked == []
        assert fake.briefed == [""]
        assert result.outcome is Outcome.DONE

    def test_an_empty_question_is_not_a_question(self, shop, monkeypatch):
        """A worker filling in every field of the report shape must not be
        read as having asked something."""
        fake = Fake(monkeypatch, [asks("   "), finished()])
        fake.run_it(a_run(shop))

        assert fake.asked == []

    def test_an_older_report_with_no_question_field_still_works(
        self, shop, monkeypatch
    ):
        fake = Fake(monkeypatch, [gave_up()])
        result = fake.run_it(a_run(shop))

        assert fake.asked == []
        assert result.outcome is Outcome.BLOCKED


class TestWhatWasSaidLastTime:
    """A resumed run drops the results of items that did not land, so they
    can be tried again. It used to drop the reason with them, and the
    engineer started from nothing: the same hours band was refused three
    times for the same missing times."""

    def test_the_engineer_is_told_why_it_was_sent_back(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [finished()])
        run = a_run(shop)
        run.refused = {1: "The hours band has no hours in it."}
        fake.run_it(run)

        assert "no hours in it" in fake.briefed[0]

    def test_it_says_the_tree_is_clean(self, shop, monkeypatch):
        """Otherwise the engineer goes looking for the half-finished work the
        complaint is about, and it was thrown away."""
        fake = Fake(monkeypatch, [finished()])
        run = a_run(shop)
        run.refused = {1: "rejected on two counts"}
        fake.run_it(run)

        assert "thrown away" in fake.briefed[0]

    def test_an_item_never_tried_is_told_nothing(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [finished()])
        fake.run_it(a_run(shop))

        assert fake.briefed == [""]

    def test_a_refusal_about_another_item_is_not_handed_over(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [finished()])
        run = a_run(shop)
        run.refused = {7: "something about item seven"}
        fake.run_it(run)

        assert fake.briefed == [""]

    def test_it_is_said_once(self, shop, monkeypatch):
        """The second attempt has its own, fresher complaint to work from."""
        fake = Fake(monkeypatch, [asks("one?"), finished()])
        run = a_run(shop)
        run.refused = {1: "the old complaint"}
        fake.run_it(run)

        assert "the old complaint" in fake.briefed[0]
        assert "the old complaint" not in fake.briefed[1]


class TestAWorkerThatWasTakenAway:
    """Two items ran side by side and one of them was killed by something
    outside the item - exit 143, no report, nothing said. It was treated as
    an item the engineer could not do, so the item was blocked and the four
    items that needed it never ran. Nothing about the item had been learned;
    the right response is to try the same item again."""

    def test_the_item_is_tried_again(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [was_killed(), finished()])
        result = fake.run_it(a_run(shop))

        assert result.outcome is Outcome.DONE

    def test_it_does_not_spend_an_attempt(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [was_killed(), finished()])
        assert fake.run_it(a_run(shop)).attempts == 1

    def test_the_next_attempt_is_not_told_it_failed(self, shop, monkeypatch):
        """There is nothing to tell it. Handing over 'exited 143' as though
        it were a complaint about the work sends it looking for a problem
        that is not in the repository."""
        fake = Fake(monkeypatch, [was_killed(), finished()])
        fake.run_it(a_run(shop))

        assert fake.briefed == ["", ""]

    def test_it_is_restarted_more_than_once(self, shop, monkeypatch):
        """This happened three times on one item in an afternoon and the
        item itself was fine every time."""
        fake = Fake(monkeypatch, [was_killed(), was_killed(), finished()])
        result = fake.run_it(a_run(shop))

        assert result.outcome is Outcome.DONE
        assert result.attempts == 1

    def test_the_restarts_run_out(self, shop, monkeypatch):
        """A worker that cannot stay up three times running is a machine
        problem, and looping on it burns the run instead of reporting it."""
        fake = Fake(monkeypatch, [was_killed()] * 4)
        result = fake.run_it(a_run(shop))

        assert result.outcome is Outcome.BLOCKED

    def test_each_restart_says_which_one_it_is(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [was_killed(), finished()])
        fake.run_it(a_run(shop))

        said = next(note for who, note in fake.gates if who == "restarted")
        assert "restart 1 of 2" in said

    def test_the_restart_is_announced(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [was_killed(), finished()])
        fake.run_it(a_run(shop))

        assert any(who == "restarted" for who, _ in fake.gates)

    def test_an_ordinary_failure_is_still_a_failure(self, shop, monkeypatch):
        """The engineer saying it cannot do this is information. Restarting
        on it would run the same item into the same wall."""
        fake = Fake(monkeypatch, [gave_up(), finished()])
        result = fake.run_it(a_run(shop))

        assert result.outcome is Outcome.BLOCKED


def was_killed() -> dict:
    return {
        "done": False,
        "summary": "the worker stopped without writing a report and exited 143",
        "files_changed": [],
        "died": True,
    }


class TestAnAnswerBecomesPartOfTheItem:
    """It used to live for the length of one worker. The attempt after it
    read the original item, made the same discovery, and the reviewer
    refused it for not doing what the item still said - which it did say,
    because nobody had changed it. Watched happen twice on one item."""

    def test_the_answer_is_written_onto_the_item(self, shop, monkeypatch):
        fake = Fake(monkeypatch, [asks("overhang the inset, or not?"), finished()])
        run = a_run(shop)
        fake.run_it(run)

        settled = run.plan.items[0].settled
        assert len(settled) == 1
        assert "overhang the inset" in settled[0]
        assert "the VAT-inclusive price" in settled[0]

    def test_everybody_downstream_reads_it(self, shop, monkeypatch):
        """The reviewer and the critic judge the item as it now stands, not
        as it was written."""
        run = a_run(shop)
        run.plan.items[0].settled.append("Asked: x\n  Settled: drop the overhang")

        said = run.plan.items[0].as_asked()
        assert "drop the overhang" in said
        assert "win over anything above" in said

    def test_an_item_nobody_asked_about_reads_as_before(self, shop, monkeypatch):
        run = a_run(shop)
        said = run.plan.items[0].as_asked()

        assert "Since this was written" not in said
        assert run.plan.items[0].title in said

    def test_work_belonging_elsewhere_is_not_written_onto_it(self, shop, monkeypatch):
        """That answer is about what the item is not. Recording it as part
        of the item is the opposite of what it says."""
        fake = Fake(
            monkeypatch,
            [asks("should I write the printer driver?")],
            said="[this belongs in another item] item 4 does the printer",
        )
        run = a_run(shop)
        fake.run_it(run)

        assert run.plan.items[0].settled == []

    def test_it_survives_the_run_being_written_down(self, shop, monkeypatch):
        """Which is the whole point: a resumed run has to start from the
        decision rather than make it again."""
        run = a_run(shop)
        run.plan.items[0].settled.append("Asked: x\n  Settled: drop it")

        from drydock.models import Plan

        back = Plan.model_validate_json(run.plan.model_dump_json())
        assert back.items[0].settled == ["Asked: x\n  Settled: drop it"]
