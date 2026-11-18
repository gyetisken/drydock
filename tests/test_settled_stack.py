"""Whether the task already says what to build it with.

On a measured run the Architect spent forty-one seconds writing "Node.js
20+, no framework, node:http and node:test" for a task whose first line
was "the stack is already decided: use Node.js built-in modules and the
built-in test runner". That was a third of everything the run spent
working, and the floor for any station here is about twenty-five seconds,
so the saving is in not running one rather than in making one faster.

The two mistakes are not equal, and that asymmetry is what most of this
pins. Running the Architect when the task had settled the stack costs
forty seconds. Skipping it when the task had not leaves nobody deciding.
"""

import pytest

from drydock.stack import already_decided


class TestTasksThatSettleTheirOwnStack:
    @pytest.mark.parametrize(
        "task",
        [
            (
                "Create a tiny Node.js API. The stack is already decided: use "
                "Node.js built-in modules and the built-in test runner."
            ),
            "Build a small Python service using FastAPI, no other dependencies.",
            "Create a Next.js app. Do not change the framework.",
            "A CLI written in Go, no external libraries.",
            "Make a page with Astro. The toolchain is fixed.",
        ],
    )
    def test_the_architect_is_not_needed(self, task):
        assert already_decided(task)

    def test_it_says_what_settled_it(self):
        """A station that is skipped has to say why, or the next person
        reading the run cannot tell a decision from a bug."""
        settled = already_decided(
            "Create a tiny Node.js API. The stack is already decided."
        )
        assert "Node.js" in settled.why
        assert "already decided" in settled.why


class TestTasksThatDoNot:
    @pytest.mark.parametrize(
        "task",
        [
            "Build me a website for my bakery",
            "A small Python script would be nice",
            "Add a function to src/hours that says minutes until close",
            "Use whatever you decided last time",
            "Make something to track my reading",
            "",
        ],
    )
    def test_the_architect_still_runs(self, task):
        assert not already_decided(task)

    def test_naming_a_toolchain_is_not_settling_one(self):
        """'A small Python script would be nice' is a preference. Acting
        on it as a decision is how nobody ends up deciding."""
        settled = already_decided("A small Python script would be nice")
        assert not settled
        assert "does not say it is decided" in settled.why

    def test_settling_without_naming_settles_nothing_actionable(self):
        settled = already_decided("The stack is already decided, as you know.")
        assert not settled
        assert "does not name a toolchain" in settled.why

    def test_an_empty_task_is_not_a_decision(self):
        assert not already_decided("")
        assert not already_decided("   ")


class TestWhatTheSessionDoesWithIt:
    def test_the_architect_is_skipped_only_on_an_empty_repository(self):
        """A repository with files has its shape read by the Analyst, and
        that path already existed. This adds a second reason to skip, not
        a different rule about when the Architect matters."""
        import inspect

        from drydock.session import Session

        source = inspect.getsource(Session)
        assert "wants_shape = empty and not settled" in source

    def test_what_the_task_decided_is_handed_to_the_planner(self):
        """Skipping the Architect without passing on what the task said
        would leave the planner to work out the stack mid-plan, which is
        the thing the Architect exists to prevent."""
        import inspect

        from drydock.session import Session

        source = inspect.getsource(Session)
        assert "The stack was decided by whoever asked for this" in source

    def test_the_skip_is_announced_with_its_reason(self):
        import inspect

        from drydock.session import Session

        source = inspect.getsource(Session)
        assert "the task already decided this" in source


class TestItCostsNothingToAsk:
    def test_no_model_is_called(self):
        """A model call to decide whether a model call is needed costs the
        thing it is trying to save."""
        import inspect

        from drydock import stack

        source = inspect.getsource(stack)
        for word in ("Engine", "Agent", "subprocess", "claude"):
            assert word not in source, word
