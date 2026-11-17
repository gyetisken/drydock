"""What a refusal carries back with it.

Four attempts on one item were refused for the same thing: text cut off at
the right edge of a phone. The engineer was told each time, in detail, and
each time it changed something else. It cannot look at the page - being
told is the only thing it has - and a complaint it cannot turn into a
change is a complaint that costs an attempt and teaches nothing.

So where a complaint has one usual cause, the cause goes with it.
"""

import pytest

from drydock.orchestrate import _with_the_usual_cause


class TestAPageWiderThanTheScreen:
    @pytest.mark.parametrize(
        "complaint",
        [
            "The intro line is clipped at the right viewport edge on mobile.",
            "Three lines are cut off mid-word by the edge.",
            "The rule under the name runs off the right edge.",
            "The masthead block is overflowing the viewport.",
            "Text disappears off the screen at 390px.",
            "The block is wider than the viewport at phone width.",
        ],
    )
    def test_the_usual_cause_goes_with_it(self, complaint):
        said = _with_the_usual_cause(complaint)
        assert "100vw" in said
        assert "clamp()" in said

    def test_the_complaint_itself_is_kept(self):
        """It is the evidence. The cause is a hint, not a replacement."""
        said = _with_the_usual_cause("The intro line is clipped at the edge.")
        assert said.startswith("The intro line is clipped at the edge.")


class TestTextThatCannotBeRead:
    def test_contrast_carries_its_cause(self):
        said = _with_the_usual_cause("The times are invisible on the black plane.")
        assert "takes the page's" in said

    def test_both_can_apply_at_once(self):
        said = _with_the_usual_cause(
            "The rows are clipped at the edge, and unreadable against the plane."
        )
        assert "100vw" in said
        assert "takes the page's" in said


class TestEverythingElseIsLeftAlone:
    @pytest.mark.parametrize(
        "complaint",
        [
            "display() is not exported from till.js",
            "the item added a dependency it did not name",
            "the hours are wrong on Sunday",
        ],
    )
    def test_an_ordinary_complaint_is_unchanged(self, complaint):
        assert _with_the_usual_cause(complaint) == complaint

    def test_nothing_refused_says_nothing(self):
        assert _with_the_usual_cause("") == ""
