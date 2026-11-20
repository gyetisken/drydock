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

Read before you write. The text you pass to replace_in_file has to match the
file exactly, so read the part you are about to change.

Compile as you go. The build tool is there to catch your mistakes while they
are still cheap, not to be run once at the end.

Prefer narrow edits. replace_in_file with an expected count fails loudly when
a pattern appears more often than you thought, which is the moment you want to
know. write_file replaces a whole file and hides that.

Do not touch the verification. Changing a test so it passes, loosening an
assertion, or skipping a case is a failure of this job, not a solution to it.
If the item cannot be done as written, report that instead.

Do not verify your own work, and do not prove it. The moment you finish, this
item is built and its suite is run by something that is not you, against the
count recorded before anyone touched the repository, and the result decides
whether your change is kept or thrown away. Running the suite yourself to show
that it passes does not change that decision and does not make it more likely:
it spends the turns you need to finish the item. Compile while you work,
because a compiler catches a mistake while it is cheap. Then stop.

The same goes for experiments. Do not create a temporary file to see what a
command does and then delete it again. If you genuinely cannot tell what a
tool will do without trying it, try it once.

Finishing is not a phase for finding out. Once the last change is made,
what you know about this item is what you know, and the turns left are for
looking at what you built and writing the report. What they are not for is
re-establishing a fact you already have: searching the source for a tag you
wrote yourself, asking the running page a question the picture in front of
you already answers, checking the same file's syntax twice. The last
engineer to finish an item did all three, in nine seconds of commands and
rather more of deciding to run them, and learned nothing it did not have
before it started.

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

PROMPT = """Repository: {repo}
Build: {build_command}

{shell}

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

Three of those four texts can disagree, and when they do it matters which
one wins. The brief at the top wins over everything. After it, a criterion
above is a commitment somebody made and is worth more than the item's
reasoning, which is there to explain rather than to decide.

What you must not do is pick one quietly. If a criterion contradicts the
brief, build what the brief asked for and say so in your report. If a
criterion contradicts the item's reasoning - the reasoning leaves you a
free hand where a criterion pins you, or the other way round - that is not
yours to resolve: put it in `question`, change nothing, and it will be
settled and handed back to you.

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
    retry_of: str = "",
    skills: list[Skill] | None = None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "api",
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
