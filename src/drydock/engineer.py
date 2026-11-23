"""The Engineer: do one item, and only that item.

The scope rule is the whole discipline here. An agent asked to migrate a test
suite will wander: it notices a typo, a dead import, a test that could be
clearer, and fixes them, and the diff that was meant to prove one idea now
contains six. When the suite then goes red, nothing points at a cause.

So the item is the contract. Anything outside it that deserves attention is
reported, not fixed.
"""

from pathlib import Path

from .agent import API_MODEL, CHEAP_ENGINEER, JUDGEMENT, Agent, Tool, for_work
from .engines import ClaudeCodeEngine, EngineResult, shell_allowance
from .models import Item
from .repo import OUR_LOOK
from .skills import Skill, briefing
from .tools import write_tools

SYSTEM = """You are making one change to a codebase that currently works.

The item you are given is the entire scope. Not the task it belongs to, not the
next item, not something adjacent that is obviously wrong. If you find a real
problem outside the item, say so in your report and leave it alone.

What is yours to decide. The item fixes the outcome; inside it, the
implementation is yours. Layout, typography, spacing, hierarchy, markup,
structure, names, and every value that goes with them are your decisions,
taken with the code and the rendered page in front of you - which is a
better place to take them from than the plan was. Where the item or the
direction names something exactly, that is a constraint somebody chose and
it holds. Where they are quiet, you are not waiting for permission: decide,
and decide well. "It did not say" is not a reason for the obvious version.

The brief at the top is what the finished thing is judged against. It wins
over anything downstream that drifted from it, including the direction and
including this item's own wording - if they disagree, say so in your report
and build what the brief asked for.

How to work:

Read before you write. The text you give Edit has to match the file exactly,
so read the part you are about to change.

Prefer narrow edits. Edit fails loudly when the text it was given is not
there or appears more than once, which is the moment you want to know.
Write replaces a whole file and hides that - right for a file you are
creating, wrong for a change to one that exists.

Test what could plausibly be wrong, and nothing for the sake of a number.
What that comes to is decided by what the thing does, not by a quota.

Behaviour that can be wrong in a way nobody would notice needs tests, and
needs them to be real: money, concurrency, authentication, permissions,
retries, anything that writes to a store, anything that parses input from
outside. There, the edge cases are the point - the second identical
request, the empty list, the expired key, the two callers at once - and a
suite that covers only the happy path has tested nothing that was going to
break.

Markup, styling and content cannot be wrong in that way. A handful of
checks on what the page must actually contain and hold to - the facts that
have to appear, the ones that must not be invented, the thing the request
fixed - is the whole of it. Asserting the presence of every heading, the
text of every paragraph, or the value of a padding is a suite that fails
whenever somebody improves the page and catches nothing when they break
it. Write the few that would catch a real mistake and stop.

Do not touch the verification. Changing a test so it passes, loosening an
assertion, or skipping a case is a failure of this job, not a solution to it.
If the item cannot be done as written, report that instead.

Run things to find out, not to prove. Those are different and only one of
them is yours.

Finding out is part of building and you should do it freely: compile as you
go, run the one test you just wrote, run the handful that cover the thing
you just changed. A compiler or a failing assertion catches a mistake while
it is still cheap, and that is what they are for.

Proving is not yours. The moment you finish, this item is built and its
whole suite is run by something that is not you, against the count recorded
before anyone touched the repository, and that result decides whether your
change is kept. Running the full suite yourself afterwards to show that it
passes does not change that decision and does not make it likelier - it
spends the turns you need to finish. Once a run has told you what you
wanted to know, you have the answer; running it again for reassurance is
the thing to stop doing.

The same goes for experiments. Do not create a temporary file to see what a
command does and then delete it again. If you genuinely cannot tell what a
tool will do without trying it, try it once.

At the end, you already know what you know. Once the last change is made,
the turns left are for looking at what you built and writing the report -
not for establishing again something you established while building it:
searching the source for a tag you wrote yourself, asking the running page
a question the picture in front of you already answers, checking the same
file's syntax twice. One engineer did all three on its way out, and learned
nothing it did not have before it started.

Three things that are not that, and are worth the turns: reading the page
you changed, reading your own files so the report says what is actually
there, and compiling as you go. Keep doing those.

Ask rather than guess, once. An item that contradicts itself, or that turns
on a decision nobody has taken, cannot be done well by picking one reading
and hoping. Say what needs settling, change nothing, and it will be settled
and handed back to you. This is for decisions that are not yours - not for
anything you could answer by reading the repository, which you should do
instead.

Finishing means writing the report. An item that was done perfectly and never
reported is an item that is thrown away, so leave yourself the turn."""

# Said to the engineer only when it has the tool, so that a worker without
# it is never told about something it cannot run.
#
# The last paragraph is the important one. A worker that has looked at its
# own page is not a worker that has been checked, and the moment this reads
# as a check the gates become a formality - which is the opposite of the
# reason it exists. Looking is how work that nobody has seen stops being
# handed on; it decides nothing.
LOOKING = """

Looking at what you have built.

This item renders something a person will look at, and you can look at it
yourself before you finish. Run:

    drydock-look            the home page
    drydock-look /menu      another page of the same project

It starts the project the way the project says it starts, measures the
page, and writes pictures of it at two widths into `{look}/`. Open every
picture it names with Read. The measurements are facts; the pictures are
the only way you actually see the thing you wrote.

Then fix what you found and look again. You have {looks} of these for
this item, so spend the first one once there is something to see rather
than on an empty page.

If it says NOT LOOKED, nothing was rendered and nothing about the page has
been established. Say that in your report. Describing a page you have not
seen, or reporting that you checked it, is worse than not looking.

This is not a check that counts. What you write is still built, its suite
still run, its diff still read, and the page still measured and looked at
by somebody who is not you. None of them is told that you looked."""

# What a visual item gets when nothing upstream directed it.
#
# The straight path builds its one item from the request and goes, so it
# never calls the station that writes the direction: measured on two runs
# of the same hotel, the planned one carried 4,515 characters of direction
# and 1,630 of brief, and the straight one carried nought of either. The
# engineer was handed a sentence and asked for a website.
#
# This is not a station and it is not a plan. It is four lines the worker
# writes for itself inside the turn it already has, before it starts
# typing, because deciding what the page is for costs less than a minute
# and is the difference between a page and a template.
DIRECT_YOURSELF = """

Nothing upstream directed this. You are the only one who will decide what
it looks like, so decide it before you write anything, in four or five
lines, and put them at the top of your report:

- Who walks in, what they came to find, and what the place feels like
  standing in it. Specific to this one, not to the category.
- The one gesture the page is carried by, and where it then gets quiet.
- The ground, the ink and the one accent, named the way a person names a
  colour rather than as hex.
- What the generic version of this page would be - the stock hero, the
  carousel nobody asked for, "Welcome to our restaurant" - so it cannot
  arrive by default.

Then build against it. This is your own working decision and nothing
downstream judges the result against it: it is not an acceptance
criterion, it does not become a test, and it does not widen the item. The
item is still the whole of what you touch. If the request or the brief
already says one of these, that wins and you do not restate it."""

PROMPT = """Repository: {repo}
Build: {build_command}

{shell}

{known}

What is being built, and what it is for. This does not widen your scope -
the item below is still the whole of what you touch - but it is what the
finished thing is judged against, so where the item leaves you a choice,
this is what decides it:

{task}

Your item, which is the entire scope:

  {id}. {title}

  {rationale}

  files: {files}
  verified by: {verify_with}

What has to be true when this item is done. These are the acceptance
criteria the plan was approved on, and something that is not you will read
the change against them:

{criteria}

Those criteria come in two groups and they are not worth the same. What
is under "From what was asked" is the person's requirement and holds.
What is under "Decided here" is the planner's reading of something the
person left open - it is a sensible default and a good starting point,
and you may do it differently when the code in front of you says
otherwise. Say which one you departed from and why, in your report.

Three of those four texts can disagree, and when they do it matters which
one wins. The brief at the top wins over everything. After it, a
requirement from the brief is a commitment somebody made and is worth
more than the item's reasoning, which is there to explain rather than to
decide.

What you must not do is pick one quietly. If a criterion contradicts the
brief, build what the brief asked for and say so in your report. If a
criterion contradicts the item's reasoning - the reasoning leaves you a
free hand where a criterion pins you, or the other way round - that is not
yours to resolve: put it in `question`, change nothing, and it will be
settled and handed back to you.

**Whole first, then better.** Get every part of the item working and
verified - the files written, the command running, the suite passing -
before you improve any of it. Then one pass of improvement over what is
there, and report.

That order is not a style preference, it is what makes the work
survivable. An item that is complete and plain can be committed; an
item that is three-quarters built and beautifully typeset in the parts
that exist is thrown away whole when the clock runs out, and so is
everything it would have become. Measured on one run: twelve minutes
on a one-page site, ending in a run of eight consecutive edits to the
stylesheet, and nothing delivered.

One pass. When the item's criteria are met and the page is not wrong,
it is finished - "could be nicer" is not a defect, and another look at
something that already reads is a turn spent on the thing you have
already done rather than on the thing you have not. Something that is
not you will look at the result and say if it is wrong.

Make the change, then report."""


class _AsUsage:
    """Make the CLI's own accounting look like the API engine's.

    The run does not care which engine produced a number, only that it can add
    it up and show it.
    """

    def __init__(self, result: EngineResult) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0
        self.turns = result.turns
        self.dollars = result.dollars


def _report_tool() -> Tool:
    return Tool(
        name="report",
        description="Report what you did. Call this once, when the item is finished.",
        schema={
            "type": "object",
            "properties": {
                "done": {
                    "type": "boolean",
                    "description": "False if the item could not be done as written.",
                },
                "summary": {
                    "type": "string",
                    "description": "What changed, in one or two sentences.",
                },
                "files_changed": {"type": "array", "items": {"type": "string"}},
                "noticed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Problems outside this item's scope, left alone.",
                },
            },
            "required": ["done", "summary", "files_changed", "noticed"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def _with_decisions(item) -> str:
    """The item's reasons, plus anything settled about it since."""
    said = item.rationale
    if getattr(item, "settled", None):
        said += "\n\nSince this item was written, these questions about it "
        said += "were put to whoever wrote it and answered. They are part of "
        said += "the item now and they win over anything above that "
        said += "disagrees:\n\n"
        said += "\n\n".join(f"- {s}" for s in item.settled)
    return said


def work(
    repo: Path,
    task: str,
    item: Item,
    build_command: str,
    known: str = "",
    retry_of: str = "",
    skills: list[Skill] | None = None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "claude",
    model: str = "opus",
    direction: str = "",
    policy=None,
    can_look: bool = False,
    look_key: str = "",
) -> tuple[dict, object]:
    prompt = PROMPT.format(
        repo=repo.name,
        build_command=build_command,
        shell=shell_allowance(build_command),
        # What the start of the run already found out. It was written
        # onto the record and read by nothing, so every engineer worked
        # out the language, the test command and the shape of the
        # project again - once per item, five times on a five-item plan.
        known=known.strip(),
        task=task,
        id=item.id,
        title=item.title,
        # Anything since decided about this item comes with it. A question
        # the planner settled used to live for the length of one attempt,
        # and the attempt after it read the original item, made the same
        # discovery, and was refused for not doing what the item still said.
        rationale=_with_decisions(item),
        files=", ".join(item.files),
        verify_with=item.verify_with,
        # The acceptance criteria, which used to be written and then shown
        # to nobody. A reviewer approved a change that failed one of them
        # because neither station had ever been handed them: the criteria
        # live in `plain` and both prompts were built from `rationale`.
        criteria=(item.plain or "").strip()
        or "  (the plan recorded none for this item)",
    )
    if retry_of:
        prompt += (
            "\n\nThis item was attempted and sent back. What was said is below. "
            "Work out what broke before changing anything else.\n\n"
            f"{retry_of}\n\n"
            # An item came back with two complaints, the engineer fixed the
            # one it had already been thinking about, and the second refusal
            # named the other one again, word for word. There is nothing
            # subtle to fix there: it had been told, and it answered half.
            "Read that again and count the separate complaints in it. There "
            "is usually more than one, and the one you find least "
            "interesting is the one that gets left. Deal with every one of "
            "them, and in your summary say what you did about each - by "
            "number, in the order they were raised. An item is not done "
            "while any of them still stands, however small."
        )

    # What one engineer gets for one item, from the policy this run was
    # given rather than from a constant in this file.
    from .policy import of

    policy = policy or of(None)

    # The model that will do the typing, named once rather than computed
    # inside the call, so that it can be said out loud before it is used.
    # A retry is never routed to a cheaper model: once an item has come
    # back refused, the attempt that follows is the one that must not fail,
    # and another ten minutes of the same mistake costs far more than the
    # difference.
    typing = model if retry_of else for_work(model)
    # Looking is the subscription engine's only. The API path has no shell
    # at all by design, so there is nothing there to run the tool with -
    # and claiming the capability where it cannot exist is the kind of
    # silent difference this program keeps being bitten by.
    looks = policy.self_looks if (can_look and engine == "claude") else 0
    if not look_key:
        looks = 0
    # An undirected visual item directs itself. Only when there is nothing
    # - a direction that exists wins, and a job nobody looks at does not
    # need a palette.
    if can_look and not direction.strip():
        direction = DIRECT_YOURSELF
    briefed = LOOKING.format(look=OUR_LOOK, looks=looks) if looks else ""
    if typing != model and on_event:
        # Visible, every time, in the feed and in the run log. A routing
        # decision nobody can see is the bug this replaced.
        on_event(
            "model",
            f"this first attempt runs on {typing} rather than the {model} "
            f"chosen for the run, because {CHEAP_ENGINEER} is set; a retry "
            f"would run on {model}",
        )

    if engine == "claude":
        # The worker is whatever Claude Code is signed in as. Everything that
        # decides whether its work survives still happens here.
        result = ClaudeCodeEngine(
            model=typing,
            max_turns=policy.turns,
            # A retry has more to do than the attempt before it: the item,
            # plus everything it was sent back for, read and dealt with one
            # by one. Twelve minutes is the bound on an ordinary attempt and
            # it was being applied to the hardest one. A worker that has
            # genuinely stopped working is caught by the silence limit long
            # before either number matters.
            minutes=policy.retry_minutes if retry_of else policy.minutes,
        ).work(
            repo,
            SYSTEM + briefing(skills or [], "engineer") + briefed + direction,
            prompt,
            build_command,
            on_event,
            look_key=look_key,
            looks=looks,
        )
        return (
            {
                "done": result.done,
                "summary": result.summary,
                "files_changed": result.files_changed,
                "noticed": result.noticed,
                "question": result.question,
                "died": result.died,
            },
            _AsUsage(result),
        )

    agent = Agent(
        name="Engineer",
        model=API_MODEL.get(typing, JUDGEMENT),
        system=SYSTEM + briefing(skills or [], "engineer") + direction,
        tools=write_tools(repo, build_command),
        max_turns=30,
        budget=budget,
        on_event=on_event,
    )
    return agent.run(prompt, final_tool=_report_tool()), agent.usage
