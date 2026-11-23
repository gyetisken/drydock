"""One worker that reads, decides and plans, instead of four that queue.

Measured on an empty folder, for a one-page site: seventy-one seconds in
the Architect, five minutes and forty-one seconds in the Designer, two
minutes and fifty-four in the Planner - eight minutes and thirty-six
seconds before a line of the thing anybody asked for existed.

Almost none of that is the model being slow. Each station is its own
process with its own cold start, reads the task again from nothing,
writes its answer as prose for the next one, and dies. The next station
re-derives what the last one already knew. And every decision is made
ahead of the work, in prose, by somebody who will never see the result -
which is why the designer spends five minutes writing a brief for a page
it does not look at, and why the critic is surprised by what got built.

A person given this job reads the folder, decides the stack while reading
it, decides how it should look while deciding what it is, and writes the
plan - in one sitting, with the repository in front of them. That is one
call with tools, not four calls passing notes.

What is deliberately NOT folded in is everything after the code exists.
The verifier, the inspector, the reviewer and the critic stay separate
for the one reason that matters: the thing that writes the code must not
be the thing that says it may stay. Every failure this project has had
was the harness believing its own report.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent, Tool
from .engines import ClaudeCodeEngine
from .models import Inventory, Plan
from .planner import PLAN_SCHEMA
from .skills import Skill, briefing

# What the worker says out loud when it moves on. It says it by running a
# command, not by writing a sentence somebody has to interpret: the office
# then shows a desk because a desk was named, which is the difference
# between reporting and guessing.
PHASES = ("reading", "stack", "direction", "plan")
PHASE_DESK = {
    "reading": "Analyst",
    "stack": "Architect",
    "direction": "Designer",
    "plan": "Planner",
}
PHASE_MARK = "DRYDOCK PHASE:"


# The word after the mark, and nothing else that is on the line. The first
# version of this split on whitespace and took the first piece, which on a
# real event - `Bash command=echo "DRYDOCK PHASE: plan", description=...` -
# is `plan",` and matches no desk. Six minutes of a measured run went by
# with the room showing nobody working, because the test for it was written
# against a tidier string than the one that arrives.
_PHASE = re.compile(re.escape(PHASE_MARK) + r"""\s*["'`]*([a-zA-Z]+)""")


def desk_for(said: str) -> str:
    """The station a phase line names, or empty if it names none."""
    found = _PHASE.search(said or "")
    return PHASE_DESK.get(found.group(1).lower(), "") if found else ""


SYSTEM = """You are starting a piece of work. You read the repository, decide
what is missing, decide what it is built with and how it should look where
that is not already settled, and write the plan - in one sitting, with the
code in front of you.

This replaces four separate specialists who each read the task again from
nothing and wrote the next one a memo. You have what they had and you have
the repository as well, so decide things when you reach them rather than in
advance.

Three rules about scope.

**This folder is the whole world.** The repository you were pointed at is
the only one that exists for this job. Whatever is in the directory above
it is somebody else's and is not evidence about this: not its conventions,
not its instructions, not its house style, and not what its neighbours
settled. A folder that happens to sit inside another checkout is still its
own project. You will be refused if you try, and the refusal is not a
puzzle to route around - it is the answer.

Do not write any of the work. You read; the engineers write. The only thing
you produce is the plan and the direction.

And do not write it in prose either. An item says what has to be true
afterwards and how anybody would know - which files, what it must do, what
must not break. The markup, the structure inside a file, the values, the
layout and the names belong to the engineer, which is a capable one with
the repository open and the page in front of it. An item written out to the
last padding value gets you a transcription of your own guess instead of
the best version of the work. Anything the person asking actually fixed -
an order, a price, a word, a number - is a constraint and is repeated
exactly; everything they left open stays open.

**One item is a real answer.** If the whole job is one cohesive piece of
work - one family of files, written in one sitting, where a failure in any
part would be diagnosed by looking at the others - then it is one item,
and the range below does not override that. A page and the stylesheet it
needs are one item. Splitting a cohesive job to reach a number costs a
full round of building, testing, diff-reading and reviewing for every
slice and buys nothing back: the slices all touch the same files so none
of them can run beside another, and every boundary is a place for a
correct change to be refused for crossing it.

Several items are right when the pieces can fail on their own and can be
worked on at the same time - different files, different data, different
endpoints. That is what the range is for.

**Count the dependencies before you believe your own split.** If every
item needs the first one, you have not written five items; you have
written one item and four of its paragraphs, and each paragraph will
now cost a full round of building, testing, diff-reading and reviewing.
A plan whose own summary says the first item "lays the spine" is that
plan. Measured on a one-page site: six items took twenty-six minutes
and nine dollars, one item took ten minutes and three, and the single
item produced the better page.

**An item nobody asked for is not an item.** The criteria come in two
groups below, and an item whose "From what was asked" group is empty -
"nothing specific, this is all decided here" - is a feature you
invented, given the same weight as the thing the person wanted. Either
it belongs inside an item they did ask for, or it does not exist. A
thing you decided may shape **how** an item is done. It may not be
**why** an item exists.

Watched happen, and the reason this paragraph is here: "a website for
an Italian restaurant called LUMI" became five items, of which the
second was a timezone and daylight-saving module with its own test
suite, because the brief had decided the page should say whether the
door is open right now. Two of the remaining items then depended on it.
Nobody asked for live opening hours, and the first item alone ran for
longer than the whole job should have taken.

**An item's files must cover its own criteria.** The list of files is
what an item is allowed to write, and something that is not you refuses
a change that touches anything else. So read each criterion back and ask
what it needs on disk: "runs with one command" needs whatever serves or
starts it, "the suite passes" needs the test file. An item that asks for
something it did not authorise the files for cannot be done, and will be
refused for doing it - twice, because that is how many attempts it gets.

**The least machinery that answers the request.** A server, a build
step, a data layer, a module computing something at runtime - each is a
thing to write, test, review and keep working, and each needs the
request to have asked for it. A page of text and a stylesheet is a
complete answer to "build me a website" and is the right answer until
something in the request says otherwise. If you are about to plan
infrastructure, say in the item's reasoning which words in the request
made it necessary. If you cannot point at any, do not plan it.

**Say which of it is theirs and which of it is yours.** An item's
criteria get read as requirements by everything downstream, so a reading
you invented is enforced exactly as hard as a price the person named.
One run turned "different payload" into "judged on the three fields the
service acts on" - a defensible reading nobody asked for - and the work
was built, reviewed and delivered against it as though it had been.

So the criteria come in two groups. What the person actually said goes
under "From what was asked:" and is a requirement. What you settled
because the request did not say goes under "Decided here:" and is the
smallest reasonable reading, not a requirement: the engineer may do it
differently with a reason, and nothing downstream refuses work for
departing from it. If there is nothing in the second group, say so;
inventing one to look thorough is the failure this is here to stop.

**And a thing you decided may not be made permanent by a test.** Watched
happen: a reading that a hotel page should carry no images went under
"Decided here", and the item then asked for a test asserting no image
references anywhere on the page. A departure the engineer was explicitly
allowed to make had been turned into a failing suite. Tests are for what
the person asked for and for what the thing must not get wrong - never
for holding your own reading in place. If you find yourself writing "a
test asserts" about something in the second group, it belongs in the
first group or it does not belong at all.

**Write the request out before you plan against it.** Most requests are
one sentence. "A site for a bike shop" is a real request and a thin
brief: an engineer handed that sentence alone invents a bike shop, and
every run invents a different one. So say what the thing is - the
outcome somebody wanted, who it is for, what it has to get right - in
the `brief` field, and plan against that.

Four rules about writing it out, and they are the whole of it.

It is scaled to the request. A vague request for something creative
earns a real brief: the audience, the character of the thing, the
sections that earn their place, what a person is there to do, and what
"good" means for this particular business. A backend request earns a
different one: the behaviour, the interface, the edge cases, what
correctness means here, and the conventions this repository already
follows. **A small fix earns two sentences.** "The footer phone number
is wrong" is not an invitation to redesign the footer, and a brief that
turns it into one is a worse brief than no brief - say what is wrong,
say what right looks like, and stop.

It never invents facts. You may decide how something should feel, what
sections a page wants, what an endpoint should do when it is called
twice. You may not invent a business: no prices nobody named, no
addresses, no opening hours, no staff, no history, no third-party
service, no integration, no requirement the person did not ask for.
Placeholder content is a decision and is named as one. A fact that
arrives in a brief is enforced downstream as though somebody had asked
for it, and nobody did.

It is about outcomes, not typing. The same rule the items are under: no
hex values, no spacing scales, no file layouts, no library choices
unless the person named one or the repository already settled it. What
the thing has to be, not how to type it.

And it never argues with the request. Everything the person actually
said outranks everything you write. Where the brief and the request
disagree, the request is right and the brief is wrong - so do not write
one that disagrees. A constraint they gave - a file, a stack, a colour,
an order, a number, "no frameworks" - is repeated exactly, not softened
into a preference and not quietly widened.

**Say what you assumed, separately.** Anything you settled that they
did not say goes in `assumptions`, one per line, in the plainest words
you have: "no prices were given, so the cards say what each service is
without a price". That list is shown to the person before any of this
runs, and it is the only chance they get to catch a reading that is
wrong before it is built against. An empty list is a fine answer for a
request that left nothing open. Inventing entries to look thorough
makes the list useless, which is worse than not having one.

Do not stop to ask a question that the approval screen already asks. The
person sees the brief, the assumptions and the items before anything is
built, and that is where a wrong reading gets caught. Write down what
you assumed and carry on.

Two kinds of item are never worth their own slot: an implementation detail
of another item, and a checking item. Every item is already built, run
against the recorded test count, read for honesty, reviewed against what it
was asked for, and looked at if it renders - so "look at it on a phone" or
"run the suite green" is an item asking for work that is already happening,
delivered after the thing it was meant to catch was accepted.

Say when you move on. Before each phase, run exactly:

    echo "{mark} reading"      - before you read the repository
    echo "{mark} stack"        - before you decide what it is built with
    echo "{mark} direction"    - before you decide how it looks
    echo "{mark} plan"         - before you write the plan

Skip the phases that do not apply: a repository that already has a stack
does not need one decided, and a job nobody looks at does not need a
direction. Announce the ones you do.

{guide}"""

PROMPT = """What is being asked for: {task}

{where}

{known}

Read what you need to, decide what is not already decided, and submit the
plan. Nothing else - no files written, no code."""

EMPTY = """The folder is empty, or close to it. Nothing here decides the
toolchain, so you do. Choose the smallest thing that can hold a test suite
and be run with one command, and say the run command and the test command
exactly."""

EXISTING = """This repository already works. What it is built with is a fact
to be read, not a decision to be made, and the plan has to fit what is here
rather than what you would have chosen."""

LOOKED_AT = """Somebody is going to look at the result, so direct it: who
walks in and what they came to find, the character of the thing, what the
one memorable moment is, and what the generic version would be so it cannot
arrive by default. Be local to this business - its city, its kind of room.

Direct the intent, not the stylesheet. Name a colour the way a person does
- "a deep oxblood, not a web red" - and leave the hex, the type scale in
rem, the spacing scale and the breakpoints to the engineer, who is a
capable designer, has the repository open, and renders the page and looks
at it before anybody else does. Those are decisions better taken in front
of the thing than here. A direction written as a stylesheet in prose does
not produce a designed page; it produces a transcription.

Anything the person asking for this actually specified - a colour they
named, an order they fixed, a number they gave - is theirs, is a
constraint, and is repeated exactly.

Being vague is the other failure and it is just as bad: "clean and modern"
directs nothing. Be specific about what the page IS and quiet about how to
type it."""

UNSEEN = """Nothing here is looked at by anybody, so do not direct a look.
Spend the words on the plan.

And then do not refer to one. A plan written beside an empty direction
has sent an item to an engineer saying a value was fixed "(see
direction)" when no direction existed, which reads to whoever gets it as
a document they were not given. If a thing matters, the item says it."""


@dataclass
class Start:
    """Everything the four stations used to produce between them."""

    plan: Plan
    # The request written out, when the request was a sentence. Kept apart
    # from `direction`, which is about how a thing looks and exists only
    # for work somebody looks at - a backend job has no direction and still
    # needs saying what it is for. Kept apart from the request itself
    # because the request outranks it and the two must never be confused.
    brief: str = ""
    assumptions: list[str] = field(default_factory=list)
    direction: str = ""
    shape: str = ""
    findings: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    toolchain: str = ""
    run_command: str = ""
    test_command: str = ""
    # Whether it is worth stopping to show this before any of it is done.
    # Answered after reading the repository, by the one that read it.
    needs_a_plan: bool = True
    why_that: str = ""

    def inventory(self, chain, source_files: int = 0, test_files: int = 0):
        """What the Analyst used to hand on, assembled from one answer.

        The toolchain is taken from this worker where it decided one and
        from the detector where it only read one, because a repository that
        already works states what it is built with and is not a thing to be
        decided again.
        """
        return Inventory(
            build_tool=self.toolchain or chain.build_tool,
            language=chain.language,
            test_command=self.test_command or chain.test_command,
            build_command=self.run_command or chain.build_command,
            source_files=source_files,
            test_files=test_files,
            findings=self.findings,
            risks=self.risks,
        )


def _tool() -> Tool:
    """The plan, plus the two decisions the stations ahead of it used to make.

    Built on the planner's own schema rather than a copy of it. The last
    time this contract lived in two places, one copy was missing
    `worth_looking_at` and the planner answered a shape that could not
    carry the field the orchestrator then went looking for.

    Everything is required, because strict mode wants it so, and the
    fields that do not apply come back empty. An empty palette is a
    designer saying nothing was directed; it is not a missing answer.
    """
    schema = {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "What you found in the repository that bears on this "
                    "job. Empty for a folder with nothing in it."
                ),
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What could go wrong in doing this, specifically.",
            },
            "toolchain": {
                "type": "string",
                "description": (
                    "What this is built with - read from the repository, or "
                    "decided by you when the repository is empty and the "
                    "task did not settle it. Empty if it was already settled "
                    "by whoever asked."
                ),
            },
            "run_command": {"type": "string"},
            "test_command": {
                "type": "string",
                "description": (
                    "The command that runs the suite. On an empty project it "
                    "must fail on an empty suite rather than pass, or the "
                    "first item is verified by a command that proves nothing."
                ),
            },
            "needs_a_plan": {
                "type": "boolean",
                "description": (
                    "Whether this is worth stopping to show somebody before "
                    "any of it is done. True when it is several pieces of "
                    "work, when the order matters, when you had to make a "
                    "decision they might disagree with, or when getting it "
                    "wrong is expensive. False when it is one change you "
                    "could make now and they would recognise when they saw "
                    "it - a copy change, a colour, a rename, one small "
                    "feature in one file. You have read the repository; "
                    "answer from what is in it rather than from the "
                    "wording of the request."
                ),
            },
            "why_that": {
                "type": "string",
                "description": (
                    "One sentence on why it does or does not need showing, "
                    "naming what you found that decided it."
                ),
            },
            "brief": {
                "type": "string",
                "description": (
                    "The request written out for the engineers, scaled to "
                    "what was asked. A vague creative request earns the "
                    "audience, the character, the sections that earn their "
                    "place and what good means here; a backend request "
                    "earns the behaviour, the interface, the edge cases and "
                    "this repository's conventions; a small fix earns two "
                    "sentences and must not become a redesign. Outcomes, "
                    "not typing. No fact the person did not give - no "
                    "price, address, hour, staff member, history or "
                    "third-party service. Nothing in it may disagree with "
                    "what they asked for: where it does, they are right. "
                    "Empty only when the request was already a brief."
                ),
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "What you settled that the person did not say, one per "
                    "line, in plain words. Shown to them before anything "
                    "runs, which is where a wrong reading gets caught. "
                    "Empty is a fine answer for a request that left nothing "
                    "open; inventing entries to look thorough makes the "
                    "list useless."
                ),
            },
            "direction": {
                "type": "string",
                "description": (
                    "How this should look: who it is for, the character of "
                    "it, the one memorable moment, and what the generic "
                    "version would be so it cannot arrive by default. The "
                    "intent, not the stylesheet - the hex, the type scale "
                    "and the spacing are the engineer's, decided with the "
                    "page in front of it. Empty when nobody looks at the "
                    "result, and when it is empty nothing in the plan may "
                    "refer to it."
                ),
            },
            **PLAN_SCHEMA["properties"],
        },
        "required": [
            "findings",
            "risks",
            "toolchain",
            "run_command",
            "test_command",
            "needs_a_plan",
            "why_that",
            "brief",
            "assumptions",
            "direction",
            *PLAN_SCHEMA["required"],
        ],
        "additionalProperties": False,
    }
    return Tool(
        name="submit_start",
        description="The reading, the decisions and the plan. Call this once.",
        schema=schema,
        run=lambda **_: "",
        strict=True,
    )


def _said(found: dict) -> Start:
    return Start(
        plan=Plan(
            summary=found.get("summary", ""),
            items=found.get("items", []),
        ),
        brief=(found.get("brief") or "").strip(),
        assumptions=[
            line.strip() for line in (found.get("assumptions") or []) if line.strip()
        ],
        direction=(found.get("direction") or "").strip(),
        shape=_shape(found),
        findings=found.get("findings") or [],
        risks=found.get("risks") or [],
        toolchain=(found.get("toolchain") or "").strip(),
        # Defaulting to True on a missing field, because the question is
        # "may this skip being shown" and silence is not a yes.
        needs_a_plan=bool(found.get("needs_a_plan", True)),
        why_that=(found.get("why_that") or "").strip(),
        run_command=(found.get("run_command") or "").strip(),
        test_command=(found.get("test_command") or "").strip(),
    )


def _shape(found: dict) -> str:
    """What the engineers are told about the toolchain, if anything."""
    chain = (found.get("toolchain") or "").strip()
    if not chain:
        return ""
    lines = [f"Built with: {chain}"]
    for label, key in (
        ("Run it with", "run_command"),
        ("Test it with", "test_command"),
    ):
        said = (found.get(key) or "").strip()
        if said:
            lines.append(f"{label}: `{said}`")
    return "\n\n" + "\n".join(lines) + "\n"


def begin(
    repo: Path,
    task: str,
    empty: bool,
    looked_at: bool,
    known: str = "",
    skills: list[Skill] | None = None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "claude",
    model: str = "opus",
) -> tuple[Start, object]:
    """Read, decide and plan, in one call."""
    system = SYSTEM.format(
        mark=PHASE_MARK,
        guide=briefing(skills or [], "plan"),
    )
    prompt = PROMPT.format(
        task=task,
        where=EMPTY if empty else EXISTING,
        known=(LOOKED_AT if looked_at else UNSEEN)
        + (f"\n\n{known}" if known.strip() else ""),
    )

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=40).structured(
            repo,
            system,
            prompt,
            '{"findings": ["..."], "risks": ["..."], "toolchain": "...", '
            '"run_command": "...", "test_command": "...", '
            '"needs_a_plan": true, "why_that": "...", "brief": "...", '
            '"assumptions": ["..."], "direction": "...", '
            '"summary": "...", "items": [{"id": 1, "title": "...", '
            '"plain": "...", "rationale": "...", "files": ["..."], '
            '"verify_with": "tests", "needs": [], "worth_looking_at": false, '
            '"removes_tests": false}]}',
            on_event=on_event,
            # It reads and it announces its phases. `Write` is not in the
            # refused list, and must not be: the engine delivers a
            # structured answer by appending `Write(.drydock-out.json)` to
            # what is allowed, so refusing Write outright leaves a worker
            # that can read and run things and cannot say what it found.
            # Watched happen - it span for three minutes with nowhere to
            # put its answer. Every other station here refuses `Edit` and
            # leaves `Write` alone for the same reason.
            tools="Read Glob Grep Bash",
            without="Edit NotebookEdit WebFetch WebSearch Task",
        )
        return _said(found), _Spend(dollars, turns)

    agent = Agent(
        name="Start",
        model=API_MODEL.get(model, JUDGEMENT),
        system=system,
        tools=[],
        max_turns=4,
        budget=budget,
        on_event=on_event,
    )
    return _said(agent.run(prompt, final_tool=_tool())), agent.usage


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
