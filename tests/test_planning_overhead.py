"""What the planner is given, and what it is allowed to go and get.

Measured on one run: the planner took a hundred and forty-eight seconds,
and its first three tool calls were `git ls-files` and two `cat`s over
files the Analyst had spent a hundred and twenty-six seconds reading. The
survey was in its prompt. It went and looked anyway.

The rest of the time was writing: three thousand six hundred characters of
rationale for a single item that adds one function.
"""

from pathlib import Path

import pytest

from drydock.models import Baseline, Inventory


@pytest.fixture
def seen(monkeypatch):
    """What the planner's engine was called with, without calling one."""
    from drydock import planner

    record: dict = {}

    class Fake:
        # _system() reads these off a worker to tell the planner what one
        # engineer gets for one item.
        max_turns = 60
        seconds = 720.0

        def __init__(self, model="opus", **kw):
            record["model"] = model

        def structured(self, repo, system, prompt, shape, **kw):
            record["system"] = system
            record["prompt"] = prompt
            record["tools"] = kw.get("tools", "<not passed>")
            record["without"] = kw.get("without", "")
            return (
                {
                    "summary": "s",
                    "items": [
                        {
                            "id": 1,
                            "title": "t",
                            "plain": "p",
                            "rationale": "r",
                            "files": [],
                            "verify_with": "tests",
                            "needs": [],
                            "removes_tests": False,
                        }
                    ],
                },
                0.0,
                1,
            )

    monkeypatch.setattr(planner, "ClaudeCodeEngine", Fake)
    monkeypatch.setattr(planner, "briefing", lambda skills, role: "")
    return record


def run_the_planner(surveyed: bool):
    from drydock.planner import plan

    plan(
        Path("/tmp"),
        "add a function",
        Inventory(
            build_tool="npm",
            language="TypeScript",
            test_command="npm test",
            build_command="npm run build",
            source_files=3,
            test_files=1,
            findings=["it is a vitest project"],
            risks=[],
        ),
        Baseline(builds=True, tests_run=11, tests_failed=0, tests_skipped=0),
        engine="claude",
        model="opus",
        surveyed=surveyed,
    )


class TestWhenTheSurveyWasMadeForThisCommit:
    """Everything the repository would say is already in the prompt."""

    def test_the_planner_is_given_nothing_to_look_with(self, seen):
        run_the_planner(surveyed=True)
        assert seen["tools"] == ""

    def test_and_is_told_not_to(self, seen):
        """The permission and the instruction have to agree, or the model
        spends turns discovering it cannot do what it was invited to."""
        run_the_planner(surveyed=True)
        assert "Do not read the repository yourself" in seen["prompt"]

    def test_the_tools_it_must_not_reach_for_are_named(self, seen):
        run_the_planner(surveyed=True)
        for tool in ("Bash", "Read", "Glob", "Grep"):
            assert tool in seen["without"]


class TestWhenTheSurveyCameFromMemory:
    """Then the facts are the shape of the project rather than its current
    state, and looking is the right thing to do."""

    def test_the_planner_may_look(self, seen):
        run_the_planner(surveyed=False)
        assert seen["tools"] == "<not passed>", "no allowance was imposed"

    def test_and_is_told_why_it_might_need_to(self, seen):
        run_the_planner(surveyed=False)
        assert "came from memory" in seen["prompt"]


class TestHowLongARationaleShouldBe:
    """Three thousand six hundred characters about a function that returns
    a number is three thousand characters the engineer reads before it can
    start, and most of them say what it already knows."""

    def test_the_planner_is_told_to_match_the_item(self, seen):
        run_the_planner(surveyed=True)
        assert "as long as the item is large" in seen["system"]

    def test_it_is_told_what_to_leave_out(self, seen):
        run_the_planner(surveyed=True)
        assert "would not work out on their own" in seen["system"]
