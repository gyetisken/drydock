"""The Engineer: do one item, and only that item.

The scope rule is the whole discipline here. An agent asked to migrate a test
suite will wander: it notices a typo, a dead import, a test that could be
clearer, and fixes them, and the diff that was meant to prove one idea now
contains six. When the suite then goes red, nothing points at a cause.

So the item is the contract. Anything outside it that deserves attention is
reported, not fixed.
"""

from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent, Tool, for_work
from .engines import ClaudeCodeEngine, EngineResult
from .models import Item
from .skills import Skill, briefing
from .tools import write_tools

SYSTEM = """You are making one change to a codebase that currently works.

The item you are given is the entire scope. Not the task it belongs to, not the
next item, not something adjacent that is obviously wrong. If you find a real
problem outside the item, say so in your report and leave it alone.

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

Ask rather than guess, once. An item that contradicts itself, or that turns
on a decision nobody has taken, cannot be done well by picking one reading
and hoping. Say what needs settling, change nothing, and it will be settled
and handed back to you. This is for decisions that are not yours - not for
anything you could answer by reading the repository, which you should do
instead.

Finishing means writing the report. An item that was done perfectly and never
reported is an item that is thrown away, so leave yourself the turn."""

PROMPT = """Repository: {repo}
Build: {build_command}

Overall task, for context only:
{task}

Your item, which is the entire scope:

  {id}. {title}

  {rationale}

  files: {files}
  verified by: {verify_with}

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
) -> tuple[dict, object]:
    prompt = PROMPT.format(
        repo=repo.name,
        build_command=build_command,
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

    if engine == "claude":
        # The worker is whatever Claude Code is signed in as. Everything that
        # decides whether its work survives still happens here.
        # A retry is the expensive case. The first attempt is given the
        # faster model because most items are ordinary and it is checked
        # hard either way; once an item has come back refused, the attempt
        # that follows is the one that must not fail, and another ten
        # minutes of the same mistake costs far more than the difference.
        result = ClaudeCodeEngine(
            model=model if retry_of else for_work(model),
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
            SYSTEM + briefing(skills or [], "engineer") + direction,
            prompt,
            build_command,
            on_event,
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
        model=API_MODEL.get(for_work(model), JUDGEMENT),
        system=SYSTEM + briefing(skills or [], "engineer") + direction,
        tools=write_tools(repo, build_command),
        max_turns=30,
        budget=budget,
        on_event=on_event,
    )
    return agent.run(prompt, final_tool=_report_tool()), agent.usage
