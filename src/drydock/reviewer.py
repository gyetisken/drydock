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

SYSTEM = """You review one change against the one sentence it was supposed to
carry out. The change is in front of you as a diff and that is all you get;
you cannot read the repository and you do not need to. You are not reviewing style, naming, or how you would have done it,
and you do not ask for improvements. You answer two questions and nothing else:

1. Does this diff do what the item said?
2. Does it do anything the item did not ask for?

Reject only for a real answer of no. A change that does the item and nothing
else is approved even if you would have written it differently. Say plainly
what you saw; a reviewer who hedges is no use to anyone reading the result.

Anything true but outside the item belongs in `noticed`, not in a rejection."""

PROMPT = """Item {id}: {title}

What the item was for: {rationale}

What the engineer says it did: {summary}

The change, as a diff:

{diff}

Decide. Approve if it does the item and nothing else. Reject if it does
something other than the item, or does only part of it, or reaches the result
by weakening what was being checked rather than by making the change."""


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
) -> tuple[dict, object]:
    clipped = diff[:MAX_DIFF]
    if len(diff) > MAX_DIFF:
        clipped += (
            f"\n\n[the diff is {len(diff)} characters; the rest is not shown. "
            "An item this large cannot be reviewed as one change, and that is "
            "itself worth saying in the verdict.]"
        )

    prompt = PROMPT.format(
        id=item.id,
        title=item.title,
        # Anything since decided about this item comes with it. A question
        # the planner settled used to live for the length of one attempt,
        # and the attempt after it read the original item, made the same
        # discovery, and was refused for not doing what the item still said.
        rationale=_with_decisions(item),
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
