"""The pull request body.

It is deliberately not a description of the change - the diff is the
description. It is the part a reviewer cannot get from the diff: that the
suite was this size before and this size now, and that four separate checks
looked at each commit and what each of them concluded.
"""

import json
from pathlib import Path

from drydock.models import Baseline, Item, ItemResult, Outcome, Plan
from drydock.publish import Evidence, body, evidence_from
from drydock.run import Run


def a_run(tmp_path: Path) -> Run:
    run = Run(
        id="20261117-120000",
        repo=str(tmp_path),
        task="Build a website for Salt, a bakery in Red Hook.",
        started="2026-11-17T12:00:00",
    )
    run.baseline = Baseline(builds=True, tests_run=0, tests_failed=0, tests_skipped=0)
    items = [
        Item(
            id=1,
            title="package.json and a test command",
            plain="One command runs the tests.",
            rationale="first",
            files=[],
            verify_with="tests",
        ),
        Item(
            id=2,
            title="the hours module",
            plain="The site knows when it is open.",
            rationale="second",
            files=[],
            verify_with="tests",
        ),
    ]
    run.plan = Plan(summary="Two items.", items=items)
    run.results = [
        ItemResult(
            item=items[0],
            outcome=Outcome.DONE,
            note="3 tests pass",
            commit="aaa1111111",
        ),
        ItemResult(
            item=items[1],
            outcome=Outcome.DONE,
            note="9 tests pass",
            commit="bbb2222222",
        ),
    ]
    return run


def a_log(tmp_path: Path) -> Path:
    log = tmp_path / "run.log"
    log.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                {
                    "kind": "gate",
                    "id": 1,
                    "who": "inspector",
                    "note": "nothing to report",
                },
                {"kind": "gate", "id": 1, "who": "reviewer", "note": "does the item"},
                {
                    "kind": "gate",
                    "id": 2,
                    "who": "inspector",
                    "note": "nothing to report",
                },
                {"kind": "gate", "id": 2, "who": "critic", "note": "the week renders"},
                {"kind": "item.done", "id": 2, "outcome": "done"},
            ]
        )
    )
    return log


class TestWhatItSays:
    def test_every_landed_item_appears_with_its_commit(self, tmp_path):
        run = a_run(tmp_path)
        out = body(run, evidence_from(run, a_log(tmp_path)))
        assert "One command runs the tests." in out
        assert "aaa1111111"[:10] in out
        assert "The site knows when it is open." in out

    def test_the_test_count_before_and_after(self, tmp_path):
        run = a_run(tmp_path)
        out = body(run, evidence_from(run, a_log(tmp_path)))
        assert "Before any of this | 0 tests" in out
        assert "Now | 9 tests" in out

    def test_what_each_gate_said_is_carried(self, tmp_path):
        """The thing no other tool publishes, and the reason this is worth
        opening rather than summarising."""
        run = a_run(tmp_path)
        out = body(run, evidence_from(run, a_log(tmp_path)))
        assert "does the item" in out
        assert "the week renders" in out
        assert "**Verifier**" in out

    def test_a_rolled_back_item_is_not_claimed(self, tmp_path):
        run = a_run(tmp_path)
        run.results[1].outcome = Outcome.REVERTED
        run.results[1].commit = None
        out = body(run, evidence_from(run, a_log(tmp_path)))
        assert "The site knows when it is open." not in out

    def test_it_says_where_it_was_running(self, tmp_path):
        run = a_run(tmp_path)
        out = body(run, evidence_from(run, a_log(tmp_path)), "http://localhost:4321")
        assert "localhost:4321" in out


class TestGatheringTheEvidence:
    def test_gates_are_matched_to_their_item(self, tmp_path):
        run = a_run(tmp_path)
        found = {e.item: e for e in evidence_from(run, a_log(tmp_path))}
        assert found[1].gates["reviewer"] == "does the item"
        assert "reviewer" not in found[2].gates
        assert found[2].gates["critic"] == "the week renders"

    def test_the_verifier_is_always_recorded(self, tmp_path):
        run = a_run(tmp_path)
        for e in evidence_from(run, a_log(tmp_path)):
            assert e.gates["verifier"]

    def test_a_run_with_no_log_still_produces_a_body(self, tmp_path):
        """The log is a convenience. The run is the record."""
        run = a_run(tmp_path)
        out = body(run, evidence_from(run, None))
        assert "One command runs the tests." in out
        assert "nothing to report" in out

    def test_a_damaged_log_line_is_skipped_not_fatal(self, tmp_path):
        log = tmp_path / "bad.log"
        log.write_text(
            '{"kind": "gate", "id": 1, "who": "critic", "note": "ok"}\nnot json\n'
        )
        run = a_run(tmp_path)
        found = {e.item: e for e in evidence_from(run, log)}
        assert found[1].gates["critic"] == "ok"


def test_the_body_never_claims_more_than_happened(tmp_path):
    """Every sentence in it has to be true of this run specifically."""
    run = a_run(tmp_path)
    out = body(run, [Evidence(item=1, title="t", plain="p", commit="c", note="n")])
    assert "rolled back before the next one began" in out
    assert "nothing touched the default branch" in out
