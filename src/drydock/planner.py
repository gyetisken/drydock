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

As few items as the work honestly needs, and fewer than feels natural.

Every item costs the same whether it is large or small. After the work
itself, each one is built, its suite is run, its diff is read, it is
reviewed against what it was asked to do, and anything it renders is looked
at - between three and four minutes of checking per item, regardless of
whether the item took two minutes or twenty. Splitting a small piece of work
in two does not halve the risk; it doubles the overhead and adds nothing.

So an item exists because it is a separate thing that can fail on its own,
not because the work can be sliced there. Three data modules that are each a
list of facts are one item. A layout and the first page that uses it are one
item. A feature and its tests are always one item. A README is never an item
of its own - it goes with the last piece of work it describes.

The test for a seam: if two pieces would always be written in the same
sitting, and a failure in one would be diagnosed by looking at the other,
they are one item.

A plan for a small site is four items, five if something in it is genuinely
hard. If you have written seven, go back and find the three that were only
split because they could be. If you have written ten, you have planned a
list of files rather than a sequence of working states.

There is an upper bound too, and it is harder than it sounds. One engineer
works one item in one pass: {turns} turns and {minutes:.0f} minutes, no
second sitting, nothing carried over. An item that runs out of either is stopped
with nothing to show, and the usual cause is an item that was three pieces
of work wearing one title. Read each item back as a single sitting. If it
contains a word like "and" joining two different kinds of thing - tokens
and a layout and a page, a parser and a cache and an endpoint - count how
many files it names and how many of them have to be invented from nothing.
Four invented files is the point where it stops being one item.

Both bounds are real and they pull against each other. The resolution is
not a middle number: it is that an item is one working state the project
passes through, and a project passes through fewer of those than there are
files in it.

**Shape the work so it can be done at once.** Two items that edit the same
file cannot be worked on together, so a plan where every item edits the page
is a plan that runs one thing at a time however few items it has. This is
usually avoidable and it is usually better design anyway: one item owns the
page and its composition; each later item owns a component and the data
behind it, and the page imports it. Five items that each own their own files
finish in two rounds. Five that all edit one page finish in five.

The exception is when a change really is to one file. Say so rather than
inventing components nobody wanted - a plan contorted to look parallel is
worse than an honest chain.

**Say what each item actually needs.** Items are worked on at the same time
when they need nothing from each other, so the dependencies are the
difference between a run that takes twenty minutes and one that takes forty.

An item needs another when it imports what that one writes, when it edits a
file that one creates, or when it cannot be verified until that one has
landed. It does not need another merely because it comes after it in the
list. The first item - the one that makes the suite able to tell you
anything - is needed by everything.

Be honest in both directions. Claiming a dependency that is not there costs
time; missing one that is there costs a conflict and a rolled-back item.

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
                            "needs": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": (
                                    "The ids of items that must land before "
                                    "this one can start. Empty when it can be "
                                    "done from the state the run began in. "
                                    "Two items that touch the same file need "
                                    "each other; two that do not, do not."
                                ),
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
                            "needs",
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
            _system(engine) + briefing(chosen, "plan") + briefing(chosen, "verify"),
            filled,
            '{"summary": "...", "items": [{"id": 1, "title": "...", '
            '"plain": "...", "rationale": "...", "files": ["..."], '
            '"verify_with": "build|tests", "needs": [], '
            '"removes_tests": false}]}',
            on_event=on_event,
        )
        return Plan.model_validate(result), _Spend(dollars, turns)

    agent = Agent(
        name="Planner",
        model=API_MODEL.get(model, JUDGEMENT),
        # The planner is given both its own guidance and what the skill says
        # counts as proof, because acceptance belongs in the item rather than
        # being remembered later by whoever reads the diff.
        system=_system(engine) + briefing(chosen, "plan") + briefing(chosen, "verify"),
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


def _system(engine: str) -> str:
    """The rules, with the engineer's real limits in them.

    The bound on how large an item can be is the bound on what one worker
    finishes in one pass, so it is read off the worker rather than written
    down twice and left to drift.
    """
    if engine == "claude":
        worker = ClaudeCodeEngine()
        return SYSTEM.format(turns=worker.max_turns, minutes=worker.seconds / 60)
    return SYSTEM.format(turns=30, minutes=12)


ANSWER_SYSTEM = """You wrote this plan, and the engineer doing one of its
items has stopped to ask you something.

It stopped because the item contradicts itself, or turns on a decision
nobody has taken. It has changed nothing and is waiting. Settle it.

Answer the question and nothing else. One or two sentences, in the
imperative, naming what to do: "Use the opening hours from src/hours.js and
leave the holiday list alone" rather than "either approach could work". An
answer that lists options is the question asked back, and the engineer
cannot act on it.

You may decide something the plan did not say. That is the point - you are
the one who gets to. What you must not do is widen the item: if the honest
answer is that this needs work outside what the item was given, say so
plainly and say it belongs in another item, and the item will be stopped
rather than quietly grown.

You are not reviewing the work. Nothing has been written yet."""

ANSWER_PROMPT = """The plan, in summary: {summary}

The item being worked on:

    {id}. {title}
    Why it exists: {rationale}
    Files it was given: {files}

The rest of the plan, for context:
{others}
{direction}
The engineer asks:

    {question}

Settle it."""


def answer(
    repo: Path,
    run_plan,
    item,
    question: str,
    direction: str = "",
    engine: str = "api",
    model: str = "opus",
    on_event=None,
) -> tuple[str, object]:
    """Settle one question about one item. Returns the answer and the spend.

    Narrow on purpose: one question, one answer, no conversation. A loop in
    which the engineer and the planner talk until they agree is a loop with
    no bound on it, and the thing being decided is usually one sentence.
    """
    others = "\n".join(
        f"    {i.id}. {i.plain or i.title}" for i in run_plan.items if i.id != item.id
    )
    prompt = ANSWER_PROMPT.format(
        summary=run_plan.summary,
        id=item.id,
        title=item.title,
        rationale=item.rationale,
        files=", ".join(item.files) or "none named",
        others=others or "    (this is the only item)",
        direction=f"\n{direction}\n" if direction else "",
        question=question,
    )

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=4).structured(
            repo,
            ANSWER_SYSTEM,
            prompt,
            '{"answer": "...", "belongs_elsewhere": false}',
            on_event=on_event,
            tools="",
            without="Bash Read Glob Grep Edit NotebookEdit WebFetch WebSearch Task",
        )
        said = str(found.get("answer") or "").strip()
        if found.get("belongs_elsewhere"):
            said = f"[this belongs in another item] {said}"
        return said, _Spend(dollars, turns)

    agent = Agent(
        name="Planner",
        model=API_MODEL.get(model, JUDGEMENT),
        system=ANSWER_SYSTEM,
        tools=[],
        max_turns=1,
        on_event=on_event,
    )
    return agent.run(prompt), agent.usage
