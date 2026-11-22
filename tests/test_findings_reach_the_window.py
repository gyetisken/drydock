"""The findings were kept and still nobody could see them.

`c0a0d0d` stopped three stations' `noticed` lists being dropped: the
engineer's, the reviewer's and the critic's now reach `ItemResult` and
the run record. That fixed the losing. It did not fix the reading - the
window renders checks, files, attempts and `outstanding`, and walked
straight past the new field.

So a run could carry a reviewer saying

    If the owner of a claim throws inside createOnce ... any request
    already awaiting claim.settled hangs for the life of the process

and the only way to read it was to open the JSON by hand. paytest's
second run recorded seven of them that way.

They are shown now, folded, under the item they belong to, apart from
the things that refused and apart from `outstanding` - which is a
judgement an item was kept *despite*, and a different thing. These
stopped nothing. They are true and somebody should know.
"""

from pathlib import Path

from drydock.models import Item, ItemResult, Outcome, Plan
from drydock.run import Run

JS = Path("src/drydock/static/chat.js").read_text()
CSS = Path("src/drydock/static/app.css").read_text()


def an_item(n: int = 1) -> Item:
    return Item(
        id=n,
        title=f"item {n}",
        plain="what must be true",
        rationale="because",
        files=["a.js"],
        verify_with="tests",
    )


class TestTheWindowRendersThem:
    def test_there_is_a_renderer(self):
        assert "function noticedBy(it)" in JS

    def test_a_landed_item_calls_it(self):
        landed = JS[JS.index("function whatLanded(") :]
        assert "${noticedBy(it)}" in landed[: landed.index("function noticedBy")]

    def test_an_item_that_did_not_land_calls_it_too(self):
        """A blocked item is exactly the one whose findings somebody
        wants to read."""
        missed = JS[JS.index("function whatDidNot(") :]
        assert "${noticedBy(it)}" in missed[:900]

    def test_nothing_is_rendered_when_there_is_nothing(self):
        said = JS[JS.index("function noticedBy(") :]
        assert 'if (!said.length) return "";' in said[:400]

    def test_the_station_is_shown_apart_from_what_it_said(self):
        """Each line is stored as `engineer: ...`. The window splits it
        so the reader can see who is talking."""
        said = JS[JS.index("function noticedBy(") :][:1400]
        assert 'line.indexOf(": ")' in said
        assert "line.slice(0, at)" in said

    def test_a_line_with_no_station_still_renders(self):
        said = JS[JS.index("function noticedBy(") :][:1400]
        assert "at > 0 ? line.slice(at + 2) : line" in said

    def test_the_text_is_escaped(self):
        said = JS[JS.index("function noticedBy(") :][:1400]
        assert "esc(what)" in said
        assert "esc(who)" in said


class TestTheyAreNotShownAsFailures:
    def test_the_summary_says_they_stopped_nothing(self):
        said = JS[JS.index("function noticedBy(") :][:1400]
        assert "which stopped nothing" in said

    def test_they_are_not_styled_as_an_error(self):
        """`fact bad` is the class a failed check gets. A finding must
        not borrow it."""
        said = JS[JS.index("function noticedBy(") :][:1400]
        assert "fact bad" not in said
        assert "fact flat" in said

    def test_they_are_folded_away_by_default(self):
        said = JS[JS.index("function noticedBy(") :][:1400]
        assert '<details class="noticed">' in said
        assert "open" not in said[: said.index("<summary")]

    def test_the_style_exists_and_is_quiet(self):
        assert ".noticed {" in CSS
        assert ".noticed-one {" in CSS

    def test_outstanding_is_still_its_own_thing(self):
        """A judgement the item was kept despite is not a finding."""
        landed = JS[JS.index("function whatLanded(") :]
        block = landed[: landed.index("function noticedBy")]
        assert "kept, with this against it" in block
        assert block.index("it.outstanding") < block.index("${noticedBy(it)}")


class TestTheDataIsThereToRender:
    def _run(self, **kw):
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
            noticed=["reviewer: a request can hang", "engineer: keys never expire"],
        )
        assert w["landed"][0]["noticed"] == [
            "reviewer: a request can hang",
            "engineer: keys never expire",
        ]

    def test_a_blocked_item_carries_them(self):
        w = self._run(outcome=Outcome.BLOCKED, noticed=["critic: the page is thin"])
        assert w["missed"][0]["noticed"] == ["critic: the page is thin"]

    def test_an_item_with_none_carries_an_empty_list(self):
        w = self._run(outcome=Outcome.DONE, commit="abc", verified_commit="abc")
        assert w["landed"][0]["noticed"] == []

    def test_every_station_survives_the_round_trip(self):
        w = self._run(
            outcome=Outcome.DONE,
            commit="abc",
            verified_commit="abc",
            noticed=["engineer: a", "reviewer: b", "critic: c"],
        )
        said = w["landed"][0]["noticed"]
        assert [line.split(":")[0] for line in said] == [
            "engineer",
            "reviewer",
            "critic",
        ]

    def test_nothing_is_truncated(self):
        long = "reviewer: " + "x" * 2000
        w = self._run(
            outcome=Outcome.DONE, commit="abc", verified_commit="abc", noticed=[long]
        )
        assert w["landed"][0]["noticed"][0] == long
