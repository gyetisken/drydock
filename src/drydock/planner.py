"""The Planner: turn a survey into an ordered list of small, verifiable changes.

The plan is the only artefact a person is asked to approve, so it has to be
readable and it has to be specific. An item that says "migrate the tests" is
not a plan, it is the task restated; an item that says which files it touches
and what command proves it worked can be checked, reverted and resumed.

Order matters more than it looks. Anything that would make the suite stop
reporting honestly goes first, because every later item is measured against it.
"""

from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent, Tool
from .engines import ClaudeCodeEngine
from .models import Baseline, Inventory, Plan
from .skills import Skill, briefing
from .tools import read_only

SYSTEM = """You are planning a change to an existing codebase that currently works.

Break the task into items that can be done and verified one at a time. An item
is the right size when a single command can tell you whether it worked and,
when it did not, reverting it loses an hour rather than a day.

Rules for the plan:

As few items as the work honestly needs. An item exists because it is a
separate thing that can fail on its own, not because the work can be sliced
there. Three data modules that are each a list of facts are one item; a
layout and the page that uses it are one item. Splitting further does not
make anything safer, it makes a plan nobody reads and a run that spends most
of its time starting and stopping. A small site is five or six items. Twelve
means the knife went in at every joint it could find rather than at the
joints that matter.

The test for a seam: if two pieces would always be written in the same
sitting and would always fail together, they are one item.

Order by what would hide a problem. If one change could make the test suite
stop reporting failures honestly, it comes first, because everything after it
is judged by that suite.

Name files. "The test classes" is not a plan. If the survey counted them, the
item says which ones or how many and on what pattern.

An item that renders something has to say what a visitor gets from it, not
only what gets computed. The failure that survives every check is the page
that is correct and useless: a live "closed now" where somebody wanted the
opening hours. If an item produces a derived status, the item also says what
it sits beside.

Say each item twice. The title and the rationale are for whoever does the
work and are as specific as they need to be. The plain line is for the person
deciding whether to let this happen at all, who is not going to open the
files: one short sentence, no paths, no symbol names, no jargon, saying what
will be true afterwards that is not true now. "The menu page lists the real
dishes" rather than "src/menu.js data and GET /menu rendering it". A plan
nobody outside the work can read is a plan that gets approved without being
read, and the approval is the one thing standing between a suggestion and
somebody's repository.

Separate the mechanical from the judged. A rename that a tool can do belongs in
its own item. A rewrite that changes meaning belongs in another, on its own,
where a failure points at one decision.

Carry the risks through. The survey found places this is likely to break. Every
one of them is either an item or named in the rationale of the item that will
hit it. Do not let a risk disappear between the survey and the plan.

Each item says how it is verified: "build" when compiling is enough, "tests"
when the suite has to run."""

PROMPT = """Repository: {repo}, {build_tool} / {language}
Baseline: {tests_run} tests pass, {tests_failed} fail, {tests_skipped} skipped.

Task:
{task}

The survey found:

{findings}

And these risks:

{risks}

You may read the repository to settle a detail, but the survey is already done
and the facts above are reliable. Produce the plan."""


def _plan_tool() -> Tool:
    return Tool(
        name="submit_plan",
        description="Submit the plan. Call this once, at the end.",
        schema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "What this plan does and the order it does it in, in two or three sentences.",
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "title": {"type": "string"},
                            "plain": {
                                "type": "string",
                                "description": (
                                    "The same item in one short sentence for "
                                    "somebody who will not open the files. No "
                                    "paths, no symbol names, no jargon. Say "
                                    "what will be true afterwards that is not "
                                    "true now. Under 80 characters."
                                ),
                            },
                            "rationale": {
                                "type": "string",
                                "description": "Why this item exists and which risk it answers.",
                            },
                            "files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Paths or globs this item touches.",
                            },
                            "verify_with": {
                                "type": "string",
                                "enum": ["build", "tests"],
                            },
                            "removes_tests": {
                                "type": "boolean",
                                "description": (
                                    "True only for an item whose purpose is to "
                                    "delete tests. Any other item that loses a "
                                    "test will be refused, so say so here when "
                                    "it is deliberate."
                                ),
                            },
                        },
                        "required": [
                            "id",
                            "title",
                            "plain",
                            "rationale",
                            "files",
                            "verify_with",
                            "removes_tests",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "items"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def plan(
    repo: Path,
    task: str,
    inventory: Inventory,
    base: Baseline,
    skills: list[Skill] | None = None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "api",
    model: str = "opus",
    shape: str = "",
) -> tuple[Plan, object]:
    chosen = skills or []
    filled = (
        PROMPT.format(
            repo=repo.name,
            build_tool=inventory.build_tool,
            language=inventory.language,
            tests_run=base.tests_run,
            tests_failed=base.tests_failed,
            tests_skipped=base.tests_skipped,
            task=task,
            findings="\n".join(f"- {f}" for f in inventory.findings),
            risks="\n".join(f"- {r}" for r in inventory.risks),
        )
        + shape
    )

    if engine == "claude":
        result, dollars, turns = ClaudeCodeEngine(model=model).structured(
            repo,
            SYSTEM + briefing(chosen, "plan") + briefing(chosen, "verify"),
            filled,
            '{"summary": "...", "items": [{"id": 1, "title": "...", '
            '"plain": "...", "rationale": "...", "files": ["..."], '
            '"verify_with": "build|tests", "removes_tests": false}]}',
            on_event=on_event,
        )
        return Plan.model_validate(result), _Spend(dollars, turns)

    agent = Agent(
        name="Planner",
        model=API_MODEL.get(model, JUDGEMENT),
        # The planner is given both its own guidance and what the skill says
        # counts as proof, because acceptance belongs in the item rather than
        # being remembered later by whoever reads the diff.
        system=SYSTEM + briefing(chosen, "plan") + briefing(chosen, "verify"),
        tools=read_only(repo),
        max_turns=10,
        budget=budget,
        on_event=on_event,
    )
    result = agent.run(filled, final_tool=_plan_tool())
    return Plan.model_validate(result), agent.usage


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
