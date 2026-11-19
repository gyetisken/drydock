"""What has to finish before the first line of the thing anybody asked for.

Measured on one run, on an empty folder, for a one-page site:

    architect   71s   ) together
    designer  5m41s   )
    planner   2m54s   serialised behind both
    ---------------
    8m36s before the first item started

Two things were wrong with that, and neither is the model being slow.

The planner waited for the designer, and does not need it. Its items name
files and a test command, which is the architect's answer; what the thing
looks like reaches the engineer at item time through `run.direction`,
which is where it was always read from.

And the designer's five minutes and forty-one seconds was one generation
with no tool call in it, because it was asked for the palette, the type
scale, the composition and a complete SVG mark in a single structured
answer. Drawing is work. It belongs beside the other work rather than in
front of it.
"""

import ast
from pathlib import Path

import pytest

from drydock import designer
from drydock.session import Session

SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "drydock" / "session.py"
).read_text()


class TestTheMarkIsDrawnOnItsOwn:
    def test_the_direction_is_not_asked_for_an_svg(self):
        """The direction and the mark were one structured answer, and the
        answer could not come back until the drawing was finished."""
        fields = designer._tool().schema["properties"]
        assert "logo_svg" not in fields
        assert "logo_reasoning" not in fields

    def test_the_mark_has_its_own_call(self):
        fields = designer._mark_tool().schema["properties"]
        assert set(fields) == {"logo_svg", "logo_reasoning"}
        assert designer._mark_tool().schema["required"] == [
            "logo_svg",
            "logo_reasoning",
        ]

    def test_it_is_told_to_inherit_its_colour(self):
        """It is drawn beside the palette, not after it. A mark that takes
        its colour from the page needs to know nothing about the palette -
        and is the right answer anyway."""
        assert "currentColor" in designer.MARK_SYSTEM
        assert (
            "currentColor"
            in designer._mark_tool().schema["properties"]["logo_svg"]["description"]
        )

    def test_the_direction_no_longer_asks_for_a_drawing(self):
        assert "Draw the mark" not in designer.PROMPT


class TestWhatTheBriefingPromises:
    def a_direction(self, **extra):
        return {
            "idea": "a warm room",
            "palette": ["#f4ede1"],
            "type_scale": "big",
            "composition": "one column",
            "words": "plain",
            **extra,
        }

    def test_a_mark_that_was_drawn_is_named(self):
        said = designer.as_briefing(
            self.a_direction(logo_svg="<svg></svg>", logo_reasoning="a cup")
        )
        assert "brand/logo.svg" in said
        assert "a cup" in said

    def test_a_mark_that_was_not_drawn_is_not_promised(self):
        """The two calls can finish in either order, and one of them can
        fail. Telling the engineer to use a file that is not there is worse
        than saying nothing about it."""
        said = designer.as_briefing(self.a_direction())
        assert "brand/logo.svg" not in said
        assert said.strip(), "the rest of the direction still has to arrive"


class TestThePlannerDoesNotWaitForTheDesigner:
    def test_it_is_started_inside_the_pool(self):
        """The claim is about wall clock, so what is pinned is the shape of
        the code that produces it: the planner is submitted while the
        designer is still running, before anything waits on its result."""
        tree = ast.parse(SOURCE)
        pools = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.With)
            and "ThreadPoolExecutor" in ast.unparse(node.items[0].context_expr)
        ]
        assert len(pools) == 1, "one pool shapes this; a second would need reading"
        body = ast.unparse(pools[0])

        assert "self._plan_it" in body, "the planner is outside the pool again"
        assert body.index("planning = pool.submit") < body.index("looking.result()")

    def test_it_is_given_the_shape_and_not_the_direction(self, tmp_path, monkeypatch):
        from drydock import session as session_module
        from drydock.run import Run

        (tmp_path / "package.json").write_text("{}\n")
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        seen = {}

        def fake_plan(repo, task, inventory, base, skills, on_event, **kw):
            seen.update(kw)
            return "a plan", "some usage"

        monkeypatch.setattr(session_module, "plan", fake_plan)
        sess = Session(tmp_path, "build a page", [])
        sess.run = Run.start(tmp_path, "build a page")

        sess._plan_it("THE STACK IS NODE", True, None)

        assert seen["shape"] == "THE STACK IS NODE"
        assert "palette" not in seen["shape"].lower()

    @pytest.mark.parametrize("name", ["decide", "draw_mark", "design"])
    def test_every_station_in_the_pool_is_still_imported(self, name):
        """A rename that silently drops one of these would leave the pool
        running two things and waiting for a third that never starts."""
        from drydock import session as session_module

        assert callable(getattr(session_module, name))
