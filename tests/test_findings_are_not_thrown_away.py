"""Three stations said something true and all three were discarded.

The paytest reviewer wrote this and approved the item anyway, correctly,
because the fault was unreachable in the code as it stands:

    If the owner of a claim throws inside createOnce, store.release(key)
    un-spends the key but the claim object handed to concurrent latecomers
    is never settled or rejected, so any request already awaiting
    claim.settled hangs for the life of the process.

The phrase "hangs for the life of the process" appears zero times in the
run log. `ItemResult` had no field for it, `_judge` read only `approved`
and `reason` from the reviewer, and the critic's `noticed` was merged into
a verdict object that nothing read it back out of. The engineer's own
`noticed` - the thing the scope rule exists to collect - went the same
way. All of it survived only in a CLI transcript nobody opens.

So the findings are carried: engineer, reviewer and critic, each tagged
with who said it, onto the item result and into the run record, kept
separate from the things that actually stopped something.
"""

import inspect

from drydock import orchestrate
from drydock.models import Item, ItemResult, Outcome, Plan
from drydock.run import Run


def an_item(n: int = 1) -> Item:
    return Item(
        id=n,
        title=f"item {n}",
        plain="what must be true",
        rationale="because",
        files=["a.js"],
        verify_with="tests",
    )


class TestTheResultCanHoldThem:
    def test_there_is_a_field(self):
        r = ItemResult(item=an_item(), outcome=Outcome.DONE)
        assert r.noticed == []

    def test_it_keeps_what_it_is_given(self):
        r = ItemResult(
            item=an_item(), outcome=Outcome.DONE, noticed=["reviewer: a", "critic: b"]
        )
        assert r.noticed == ["reviewer: a", "critic: b"]

    def test_it_is_not_the_same_field_as_outstanding(self):
        """`outstanding` is the critic's last word on an item that was
        kept anyway. These are informational and did not stop anything."""
        r = ItemResult(
            item=an_item(), outcome=Outcome.DONE, outstanding="the hero is weak"
        )
        assert r.noticed == []
        assert r.outstanding == "the hero is weak"

    def test_a_record_saved_before_this_existed_still_loads(self):
        r = ItemResult.model_validate(
            {"item": an_item().model_dump(), "outcome": "done"}
        )
        assert r.noticed == []


class TestEveryStationIsCarried:
    def test_the_engineers_own_are_collected(self):
        source = inspect.getsource(orchestrate._one_item)
        assert (
            'noticed = [f"engineer: {w}" for w in (report.get("noticed") or [])]'
            in (source)
        )

    def test_the_reviewers_are_collected(self):
        source = inspect.getsource(orchestrate._judge)
        assert (
            'noticed += [f"reviewer: {w}" for w in (answer.get("noticed") or [])]'
            in (source)
        )

    def test_the_critics_are_collected(self):
        source = inspect.getsource(orchestrate._judge)
        assert 'f"critic: {w}"' in source

    def test_judge_hands_them_back(self):
        source = inspect.getsource(orchestrate._judge)
        assert "return _with_the_usual_cause" in source
        assert "unverified, noticed" in source

    def test_one_item_takes_them_from_the_gates(self):
        source = inspect.getsource(orchestrate._one_item)
        assert "refusal, refused_by, unverified, from_gates = _judge(" in source
        assert "noticed += from_gates" in source

    def test_they_reach_the_delivered_result(self):
        source = inspect.getsource(orchestrate._one_item)
        after = source[source.index("here.commit(") :]
        assert "noticed=noticed," in after

    def test_they_reach_a_blocked_result_too(self):
        """An item that could not be verified is exactly the one whose
        findings somebody will want to read."""
        source = inspect.getsource(orchestrate._one_item)
        block = source[source.index("if verdict.passed and unverified:") :][:1200]
        assert "noticed=noticed," in block


class TestTheyAreKeptApartFromFailures:
    def test_a_finding_does_not_refuse_anything(self):
        """The reviewer's hang report was correct and the item was right
        to land. Carrying it must not turn it into a veto."""
        source = inspect.getsource(orchestrate._judge)
        collect = source.index('noticed += [f"reviewer:')
        refuse = source.index('if not answer["approved"]:')
        assert collect < refuse
        between = source[collect:refuse]
        assert "refusals.append" not in between

    def test_refusals_and_findings_are_different_lists(self):
        source = inspect.getsource(orchestrate._judge)
        assert "refusals: " in source or "refusals = []" in source
        assert "noticed: list[str] = []" in source

    def test_unverified_is_still_its_own_thing(self):
        source = inspect.getsource(orchestrate._judge)
        assert "unverified.append(answer.failed)" in source


class TestTheRunRecordReportsThem:
    def _run(self, **kw):
        from pathlib import Path

        item = an_item()
        run = Run.start(Path("/x"), "a task")
        run.plan = Plan(summary="s", items=[item])
        run.results = [ItemResult(item=item, **kw)]
        return run.what_happened()

    def test_a_landed_item_carries_them(self):
        w = self._run(
            outcome=Outcome.DONE,
            commit="abc1234567",
            verified_commit="abc1234567",
            noticed=["reviewer: a request can hang"],
        )
        assert w["landed"][0]["noticed"] == ["reviewer: a request can hang"]

    def test_a_missed_item_carries_them(self):
        w = self._run(outcome=Outcome.BLOCKED, noticed=["critic: the page is thin"])
        assert w["missed"][0]["noticed"] == ["critic: the page is thin"]

    def test_they_are_a_separate_key_from_outstanding(self):
        w = self._run(
            outcome=Outcome.DONE,
            commit="abc",
            verified_commit="abc",
            outstanding="kept with this against it",
            noticed=["engineer: something adjacent"],
        )
        said = w["landed"][0]
        assert said["outstanding"] == "kept with this against it"
        assert said["noticed"] == ["engineer: something adjacent"]

    def test_nothing_is_silently_dropped(self):
        w = self._run(
            outcome=Outcome.DONE,
            commit="abc",
            verified_commit="abc",
            noticed=["engineer: a", "reviewer: b", "critic: c"],
        )
        assert len(w["landed"][0]["noticed"]) == 3


class TestEverythingThatStopsThingsStillStops:
    def test_a_refusal_still_sends_an_item_back(self):
        source = inspect.getsource(orchestrate._judge)
        assert "refusals.append(answer.reason)" in source
        assert "refused_by.append(name)" in source

    def test_an_unverified_check_still_blocks_delivery(self):
        source = inspect.getsource(orchestrate._one_item)
        assert "visual verification could not be completed" in source

    def test_a_failed_item_is_still_discarded(self):
        assert "here.discard()" in inspect.getsource(orchestrate._one_item)

    def test_the_stop_checks_are_still_everywhere(self):
        from pathlib import Path

        whole = Path("src/drydock/orchestrate.py").read_text()
        assert whole.count("_stopping(should_stop)") >= 5
