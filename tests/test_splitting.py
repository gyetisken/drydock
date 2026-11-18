"""An item that did not land, broken into pieces that might.

This is the one intervention this program has real evidence for. The same
site, the same brief: one item of five landed while its largest item -
tokens, a layout, a page and four component stubs - ran out of its twelve
minutes twice. Split by hand into the stylesheet and the page, six of
seven landed, and the stylesheet went in first try.

What is pinned here is that the split is bounded, that a piece is never
split again, that whatever was waiting for the original ends up waiting
for the whole of it, and that a planner who says it cannot be split is
believed.
"""

import pytest

from drydock.models import Item
from drydock.planner import _pieces


def an_item(**kw) -> Item:
    return Item(
        **{
            "id": 2,
            "title": "tokens, a layout, a page and four stubs",
            "plain": "the page exists",
            "rationale": "because it does",
            "files": ["styles.css", "page.astro"],
            "verify_with": "build",
            "needs": [1],
            **kw,
        }
    )


def two_pieces() -> dict:
    return {
        "can_be_split": True,
        "pieces": [
            {
                "title": "the stylesheet",
                "plain": "there are tokens to draw from",
                "files": ["styles.css"],
                "verify_with": "build",
                "worth_looking_at": False,
            },
            {
                "title": "the page",
                "plain": "the page renders",
                "files": ["page.astro"],
                "verify_with": "build",
                "needs_the_piece_before": True,
                "worth_looking_at": True,
            },
        ],
    }


class TestThePieces:
    def test_they_get_ids_that_are_not_taken(self):
        pieces = _pieces(two_pieces(), an_item(), next_id=8)
        assert [p.id for p in pieces] == [8, 9]

    def test_each_piece_inherits_what_the_original_needed(self):
        pieces = _pieces(two_pieces(), an_item(needs=[1, 4]), next_id=8)
        assert 1 in pieces[0].needs and 4 in pieces[0].needs

    def test_a_later_piece_waits_for_the_one_before_it(self):
        pieces = _pieces(two_pieces(), an_item(), next_id=8)
        assert pieces[0].id in pieces[1].needs

    def test_a_piece_that_does_not_wait_can_run_alongside(self):
        """Two halves that touch different files are the whole point of
        splitting; chaining them anyway throws that away."""
        said = two_pieces()
        said["pieces"][1]["needs_the_piece_before"] = False
        pieces = _pieces(said, an_item(), next_id=8)
        assert pieces[0].id not in pieces[1].needs

    def test_each_piece_says_whether_it_is_worth_looking_at(self):
        pieces = _pieces(two_pieces(), an_item(), next_id=8)
        assert pieces[0].worth_looking_at is False
        assert pieces[1].worth_looking_at is True

    def test_a_piece_falls_back_to_the_original_where_it_is_silent(self):
        said = {"can_be_split": True, "pieces": [{"title": "a"}, {"title": "b"}]}
        pieces = _pieces(said, an_item(), next_id=8)
        assert pieces[0].files == an_item().files
        assert pieces[0].verify_with == "build"


class TestItIsBounded:
    def test_a_piece_is_marked_as_one(self):
        """So that it is never split again. An item that genuinely cannot
        be done must not become six that cannot."""
        pieces = _pieces(two_pieces(), an_item(), next_id=8)
        assert all("piece of a larger one" in " ".join(p.settled) for p in pieces)

    def test_more_than_three_pieces_is_refused(self):
        said = {
            "can_be_split": True,
            "pieces": [{"title": str(n)} for n in range(4)],
        }
        assert _pieces(said, an_item(), next_id=8) == []

    def test_one_piece_is_not_a_split(self):
        said = {"can_be_split": True, "pieces": [{"title": "the whole thing"}]}
        assert _pieces(said, an_item(), next_id=8) == []


class TestWhenItCannotBeSplit:
    """A single function that has to be right, one migration, one file that
    is genuinely one thing. Saying so is a better answer than three pieces
    that each do a third of it and none of which works."""

    def test_the_planner_saying_no_is_believed(self):
        assert _pieces({"can_be_split": False}, an_item(), next_id=8) == []

    @pytest.mark.parametrize(
        "said",
        [
            "nonsense",
            None,
            {},
            {"can_be_split": True},
            {"can_be_split": True, "pieces": "two of them"},
            {"can_be_split": True, "pieces": [{"title": "a"}, {"no_title": "b"}]},
        ],
    )
    def test_an_answer_it_cannot_read_leaves_the_item_alone(self, said):
        """The item stays as it was and is reported as not done, which is
        what happened before splitting existed - not an item invented out
        of a half-read reply."""
        assert _pieces(said, an_item(), next_id=8) == []


class TestPuttingThePiecesIntoThePlan:
    """The riskier half. An item is replaced mid-run by two that stand in
    its place, and everything that pointed at it has to end up pointing at
    something real."""

    def test_the_item_is_replaced_where_it_stood(self, a_run, monkeypatch):
        from drydock import orchestrate

        monkeypatch.setattr(
            orchestrate, "split", lambda *a, **k: (_two_for(a_run, 2), None)
        )
        item = a_run.plan.items[1]
        assert orchestrate._split_it(
            a_run, item, _failed(item), "claude", "opus", None, None
        )
        assert [i.id for i in a_run.plan.items] == [1, 8, 9, 3]

    def test_whatever_waited_for_it_waits_for_the_whole_of_it(self, a_run, monkeypatch):
        """Item three needed item two. It needed all of item two, which is
        now the last piece - pointing it at the first would start it on a
        foundation that is half there."""
        from drydock import orchestrate

        monkeypatch.setattr(
            orchestrate, "split", lambda *a, **k: (_two_for(a_run, 2), None)
        )
        item = a_run.plan.items[1]
        orchestrate._split_it(a_run, item, _failed(item), "claude", "opus", None, None)

        third = next(i for i in a_run.plan.items if i.id == 3)
        assert third.needs == [9]

    def test_the_failed_result_is_removed_with_the_item(self, a_run, monkeypatch):
        """It happened, but the item it belonged to no longer exists, and
        leaving it would count a result against an item nobody planned."""
        from drydock import orchestrate

        monkeypatch.setattr(
            orchestrate, "split", lambda *a, **k: (_two_for(a_run, 2), None)
        )
        item = a_run.plan.items[1]
        a_run.results.append(_failed(item))
        orchestrate._split_it(a_run, item, _failed(item), "claude", "opus", None, None)

        assert all(r.item.id != 2 for r in a_run.results)

    def test_a_piece_is_never_split_again(self, a_run, monkeypatch):
        from drydock import orchestrate

        called = []
        monkeypatch.setattr(
            orchestrate,
            "split",
            lambda *a, **k: called.append(1) or (_two_for(a_run, 2), None),
        )
        piece = a_run.plan.items[1]
        piece.settled.append("This item is a piece of a larger one.")

        assert not orchestrate._split_it(
            a_run, piece, _failed(piece), "claude", "opus", None, None
        )
        assert called == []

    def test_a_planner_that_cannot_split_leaves_everything_as_it_was(
        self, a_run, monkeypatch
    ):
        from drydock import orchestrate

        monkeypatch.setattr(orchestrate, "split", lambda *a, **k: ([], None))
        before = [i.id for i in a_run.plan.items]
        item = a_run.plan.items[1]

        assert not orchestrate._split_it(
            a_run, item, _failed(item), "claude", "opus", None, None
        )
        assert [i.id for i in a_run.plan.items] == before

    def test_a_split_that_raises_is_not_a_failed_run(self, a_run, monkeypatch):
        from drydock import orchestrate

        def no(*a, **k):
            raise RuntimeError("the planner would not answer")

        monkeypatch.setattr(orchestrate, "split", no)
        item = a_run.plan.items[1]

        assert not orchestrate._split_it(
            a_run, item, _failed(item), "claude", "opus", None, None
        )

    def test_the_split_is_announced(self, a_run, monkeypatch):
        from drydock import orchestrate

        monkeypatch.setattr(
            orchestrate, "split", lambda *a, **k: (_two_for(a_run, 2), None)
        )
        said = []
        item = a_run.plan.items[1]
        orchestrate._split_it(
            a_run,
            item,
            _failed(item),
            "claude",
            "opus",
            None,
            lambda i, who, ok, note: said.append((who, note)),
        )
        assert any(who == "split" for who, _ in said)


@pytest.fixture
def a_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from drydock.models import Plan
    from drydock.run import Run

    run = Run(
        id="20261118-000000",
        repo=str(tmp_path),
        task="build it",
        started="2026-11-18T00:00:00",
    )
    run.plan = Plan(
        summary="Three items.",
        items=[
            an_item(id=1, needs=[], title="one"),
            an_item(id=2, needs=[1], title="two"),
            an_item(id=3, needs=[2], title="three"),
        ],
    )
    return run


def _two_for(run, item_id: int):
    item = next(i for i in run.plan.items if i.id == item_id)
    return _pieces(two_pieces(), item, next_id=8)


def _failed(item):
    from drydock.models import ItemResult, Outcome

    return ItemResult(
        item=item, outcome=Outcome.BLOCKED, attempts=2, note="it ran out of its time"
    )
