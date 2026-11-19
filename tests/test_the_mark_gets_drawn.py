"""The mark that was written and never asked for.

`draw_mark` was written when the four stations were still the default,
and it was called from that path only. When one worker became the
default, nothing called it - so every site built since has had no mark at
all, and the capability sat in the module as dead code nobody noticed,
because nothing fails when a thing is simply never called.

That is the second time in this project: `at_least` had the same shape
and the same silence.
"""

import inspect

from drydock.session import Session

BEGIN = inspect.getsource(Session._begin_it)


class TestItIsCalledAtAll:
    def test_the_default_path_draws_one(self):
        assert "draw_mark" in BEGIN

    def test_it_runs_beside_the_reading_rather_than_after_it(self):
        """The reading takes minutes. A mark drawn after it is minutes
        nobody is doing anything else in."""
        assert BEGIN.index("drawing = ThreadPoolExecutor") < BEGIN.index(
            "started, usage = begin("
        )

    def test_it_is_joined_before_anything_is_planned_against_it(self):
        """The briefing tells the engineers the mark is there, and the
        item loop refuses a dirty tree - so it is committed by now or it
        is not written."""
        assert BEGIN.index("drawing.result()") < BEGIN.index(
            "self.run.plan = started.plan"
        )


class TestWhenItIsDrawn:
    def test_whenever_anybody_will_look_at_the_result(self):
        """Not only when a look is being directed. A project that already
        has a direction and no mark still has no mark."""
        decision = BEGIN[BEGIN.index("drawing = None") : BEGIN.index("started, usage")]
        assert "if looked_at and not" in decision
        assert "wanted_a_look" not in decision

    def test_not_when_there_is_one_already(self):
        decision = BEGIN[BEGIN.index("drawing = None") : BEGIN.index("started, usage")]
        assert '"brand" / "logo.svg"' in decision
        assert ".exists()" in decision

    def test_a_mark_that_fails_does_not_take_the_job_down(self):
        joining = BEGIN[BEGIN.index("drawing.result()") :]
        assert "except Exception" in joining
        assert "no mark was drawn" in joining


class TestWhatIsWrittenDown:
    def test_an_svg_that_is_not_one_is_not_saved(self, tmp_path):
        from drydock.designer import write_logo

        assert write_logo(tmp_path, {"logo_svg": "sorry, no"}) == ""
        assert not (tmp_path / "brand").exists()

    def test_the_engineers_are_told_it_exists(self):
        from drydock.designer import as_briefing

        said = as_briefing(
            {"idea": "x", "logo_svg": "<svg/>", "logo_reasoning": "a stone arch"}
        )
        assert "brand/logo.svg" in said
        assert "a stone arch" in said

    def test_nothing_is_promised_when_none_was_drawn(self):
        from drydock.designer import as_briefing

        assert "brand/logo.svg" not in as_briefing({"idea": "x"})
