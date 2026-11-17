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
