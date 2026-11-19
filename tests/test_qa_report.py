"""What `/qa` says, and how much each part of it is worth.

The report has four kinds of line in it and the difference between them
is the whole arrangement:

    broken          measured. a number or an event, not an opinion
    met / missing   checked against the page, with the quote looked for
    looks wrong     somebody's eye. useful and can be mistaken
    could not check this tool could not settle it

Collapsing any of those into another is the failure this program exists
to stop, so they are kept apart in the event, in the window, and here.
"""

import inspect
from pathlib import Path

from drydock.session import Session

SESSION = inspect.getsource(Session._qa)
CHAT = (
    Path(__file__).resolve().parents[1] / "src" / "drydock" / "static" / "chat.js"
).read_text()


class TestWhatCountsAsBroken:
    def test_what_the_browser_measured_is_in_it(self):
        assert "one.findings()" in SESSION

    def test_what_happened_when_things_were_pressed_is_too(self):
        """A control that throws, or does nothing, or cannot be reached is
        a finding like any other. This line was written once, did not
        apply because the file had been reformatted under it, and was
        claimed in a commit message anyway - so it is pinned here."""
        broken = SESSION[SESSION.index("broken = sorted(") :]
        broken = broken[: broken.index("\n        )")]

        assert "one.wrong for one in pressed" in broken

    def test_an_eye_is_not_in_it(self):
        """What somebody noticed is reported, and reported separately."""
        broken = SESSION[SESSION.index("broken = sorted(") :]
        broken = broken[: broken.index("\n        )")]

        assert "noticed" not in broken


class TestTheFourKindsStaySeparate:
    def test_the_event_carries_them_apart(self):
        emitted = SESSION[SESSION.index('"qa",') :]
        for field in ("broken=", "noticed=", "checks=", "unchecked="):
            assert field in emitted, field

    def test_the_window_draws_them_apart(self):
        drawing = CHAT[CHAT.index('"qa": (e) =>') :]
        drawing = drawing[: drawing.index("\n  },")]

        assert 'class="finding no"' in drawing, "measured"
        assert 'class="finding seen"' in drawing, "an eye"
        assert "could not check" in drawing or "unchecked" in drawing

    def test_the_window_says_which_is_which(self):
        drawing = CHAT[CHAT.index('"qa": (e) =>') :]
        drawing = drawing[: drawing.index("\n  },")]

        assert "arithmetic" in drawing
        assert "can be mistaken" in drawing


class TestWhatTheEyeIsToldToLeaveAlone:
    def test_it_is_handed_the_measurements(self):
        assert "what_looks_wrong(" in SESSION
        call = SESSION[SESSION.index("what_looks_wrong(") :]
        assert "broken," in call[:200], "it has to be told what was measured"

    def test_it_is_told_not_to_repeat_them(self):
        from drydock.critic import EYES

        assert "Do not repeat" in EYES
        assert "do not guess at it" in EYES
        for measured in ("contrast", "edge", "did not load", "threw", "pressed"):
            assert measured in EYES, measured

    def test_it_is_allowed_to_find_nothing(self):
        """A page with nothing wrong with it is a real answer, and one of
        these written every time teaches people to stop reading them."""
        from drydock.critic import EYES

        assert "say so and stop" in EYES

    def test_a_look_that_fails_does_not_take_the_run_down(self):
        looking = SESSION[SESSION.index("what_looks_wrong(") :]
        assert "except Exception" in looking
        assert "could not look" in looking
