"""The second opinion on a change that already passed.

A green suite proves the change did not break what was being watched. It says
nothing about whether the change did what it was asked to do, and nothing about
what else it did on the way. Those are the two things a person checks in a pull
request, and they are the two things this station checks.

It runs last and it runs rarely: only on an item that already compiled, already
held the test count, and already came through the inspector clean. By then the
diff is small and the question is narrow, which is why one turn is enough.

It can reject. An item it rejects is reverted exactly like a red one, because a
change that quietly did something else is not improved by being kept.
"""

from pathlib import Path

from .agent import API_MODEL, Agent, Tool
from .engineer import _with_decisions
from .engines import ClaudeCodeEngine

SYSTEM = """You review one change against the one thing it was supposed to
achieve. The change is in front of you as a diff and that is all you get; you
cannot read the repository and you do not need to. You are not reviewing
style, naming, or how you would have done it, and you do not ask for
improvements. You answer three questions and nothing else:

1. Does this diff achieve what the item said?
2. Does it change behaviour the item never mentioned?
3. Does it reach the result by weakening what was being checked - a test
   loosened or deleted, an assertion removed, a check skipped, a guard
   taken out, a secret or a credential put in the source?

**How much changed is not one of the questions.** The item names the files
it authorises and something that is not you has already checked that the
diff stayed inside them. Within those files, how the engineer got there -
rewriting a file rather than editing it, a different structure, different
names, two hundred lines where you expected twenty - is its decision and
not a fault. An item that asks for an outcome does not tell you the size of
the diff that achieves it, and refusing one for being larger than the
sentence sounded is how work that was correct got thrown away twice.

Question 2 is about behaviour, not size: an unrelated feature, a changed
endpoint, a dependency added for something else, work belonging to a
different item. If you cannot name the behaviour that changed and say why
the item did not call for it, you do not have a rejection.

Reject only for a real answer. A change that achieves the item is approved
even if you would have written it differently. Say plainly what you saw; a
reviewer who hedges is no use to anyone reading the result.

Anything true but outside the item belongs in `noticed`, not in a rejection."""

PROMPT = """What is being built, and what it is for. You are not judging
the change against this - the item below is what it was asked to do - but
a criterion can be unclear on its own and clear beside what the work is
for, and until now this station was the only one reading the item with no
idea what the job was:

{brief}

Item {id}: {title}

What the item was for: {rationale}

What had to be true when it was done. These are the acceptance criteria
the plan was approved on, and checking the change against them is the
first of your three questions:

{criteria}

Files this item authorised: {files}
A change outside them has already been caught before you; inside them, the
shape and the size of the change are the engineer's to choose.

What the engineer says it did: {summary}

The change, as a diff:

{diff}

Those criteria come in two groups. What is under "From what was asked" is
the person's requirement: a change that does not meet it is a rejection.
What is under "Decided here" is the planner's reading of something left
open, and departing from it is not a fault - if the change does it
differently and the result still meets what was asked for, that is the
engineer's call and belongs in `noticed` at most. Refusing work for
crossing a line nobody drew is the thing this separation exists to stop.

Those texts can disagree with each other. A criterion that contradicts the
item's reasoning, or either of them contradicting what the person asked
for, is a fault in the plan rather than in this change - put it in
`noticed`, say which two disagree and how, and judge the change against
what the person asked for. Do not quietly pick one and review against it.

Decide. Approve if it achieves the item without changing behaviour the item
never mentioned. Reject if it does only part of it - including a criterion
above that the change does not meet - if it changes something unrelated
that you can name, or if it reaches the result by weakening what was being
checked rather than by making the change."""


def _tool() -> Tool:
    return Tool(
        name="review",
        description="Give the verdict on this change.",
        schema={
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "reason": {
                    "type": "string",
                    "description": "One or two sentences, saying what you saw.",
                },
                "noticed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "True things outside this item. Not reasons to reject.",
                },
            },
            "required": ["approved", "reason", "noticed"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


# A diff bigger than this is not read more carefully by sending more of it; it
# is a sign the item was too large, which the verdict should say out loud.
MAX_DIFF = 24_000


def review(
    repo: Path,
    item,
    diff: str,
    summary: str,
    engine: str = "api",
    model: str = "opus",
    on_event=None,
    brief: str = "",
) -> tuple[dict, object]:
    clipped = diff[:MAX_DIFF]
    if len(diff) > MAX_DIFF:
        clipped += (
            f"\n\n[the diff is {len(diff)} characters; the rest is not shown. "
            "An item this large cannot be reviewed as one change, and that is "
            "itself worth saying in the verdict.]"
        )

    prompt = PROMPT.format(
        # What the job is. Every other station has had this and this one
        # never did: it read an item and a diff with no idea what was
        # being built, which is how a criterion that is obvious in context
        # gets read as an arbitrary line to be measured against.
        brief=(brief or "").strip() or "  (nothing was recorded for this run)",
        id=item.id,
        title=item.title,
        # Anything since decided about this item comes with it. A question
        # the planner settled used to live for the length of one attempt,
        # and the attempt after it read the original item, made the same
        # discovery, and was refused for not doing what the item still said.
        rationale=_with_decisions(item),
        # What the item authorised, so that the shape of the diff is read
        # against a list rather than against the reviewer's expectation of
        # how long the sentence sounded.
        files=", ".join(item.files) or "the item named none",
        # What the item actually promised. A change that failed one of
        # these was approved because the prompt was built from `rationale`
        # and the criteria live in `plain`, which nothing passed on.
        criteria=(item.plain or "").strip()
        or "  (the plan recorded none for this item)",
        summary=summary,
        diff=clipped,
    )

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=6).structured(
            repo,
            SYSTEM,
            prompt,
            '{"approved": true, "reason": "...", "noticed": ["..."]}',
            on_event=on_event,
            # The diff is in the prompt. Everything this station needs is
            # already in front of it, and a reviewer that goes and reads the
            # repository is reviewing the result rather than the change - and
            # spends its turns doing it.
            tools="",
            without="Bash Read Glob Grep Edit NotebookEdit WebFetch WebSearch Task",
        )
        return _verdict(found), _Spend(dollars, turns)

    agent = Agent(
        name="Reviewer",
        model=API_MODEL.get(model, "claude-sonnet-5"),
        system=SYSTEM,
        tools=[],
        max_turns=1,
        on_event=on_event,
    )
    return _verdict(agent.run(prompt, final_tool=_tool())), agent.usage


def _verdict(found: dict) -> dict:
    # A reviewer that failed to answer must not be read as approval. Silence
    # is the one answer that cannot be allowed to let a change through.
    return {
        "approved": bool(found.get("approved")) if "approved" in found else False,
        "reason": found.get("reason") or "the reviewer did not return a verdict",
        "noticed": found.get("noticed", []),
    }


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
