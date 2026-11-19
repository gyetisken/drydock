"""Reading a change nobody is about to commit, and saying what is wrong.

The Reviewer station already exists and does something narrower: it holds
one item against the one sentence it was given, during a run, and can
send it back. This is the thing a person does instead - open what has
changed, read all of it at once, and say what they would say in a pull
request.

It changes nothing, so it can be run on anything at any time: a branch
somebody else wrote, a working tree halfway through an afternoon, the
last commit. Nothing is reverted and nothing is approved; the output is
an opinion with the lines it is about.

The deterministic half runs first and costs nothing. Removed tests,
weakened assertions, committed credentials and dependency directories are
arithmetic over the diff, and arithmetic does not need a model and does
not hedge. What is left for the model is the half that needs judgement.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent, Tool
from .engines import ClaudeCodeEngine

SYSTEM = """You are reading a change and saying what is wrong with it, the
way somebody does in a pull request.

What you are looking for, in this order:

1. Things that are wrong. A bug, an unhandled case, a condition the wrong
   way round, something that works on the author's machine and will not
   work on another.
2. Things that are missing. A behaviour with no test, an error path that
   returns nothing, a case the change creates and does not cover.
3. Things that will be wrong later. A silent assumption, a duplicated
   fact that will drift, an abstraction that will have to be undone.

What you are not looking for: style, naming you would have chosen
differently, or how you would have structured it. If the change works, is
tested and is clear enough to read, say so and stop. A review that always
finds something teaches people to ignore reviews.

Every finding names the file and what in it. "Error handling could be
better" is not a finding; "`parse` returns None on a malformed line and
the caller indexes into it" is. Where you are unsure, say which it is -
something you checked and something you suspect are different claims and
the difference matters more than the count.

Say what is good only when it is load-bearing: a decision that looks
wrong and is right is worth a line, so the next person does not undo it.

You may open files the diff calls into - a review that cannot look at the
function being called is guessing. Read what you need and then answer.
Reading until you run out of turns leaves no review at all, which is
worse than a review written from the diff alone."""

PROMPT = """{what}

{counted}

The change:

{diff}"""


@dataclass
class Finding:
    where: str
    what: str
    sure: bool = True


@dataclass
class Reading:
    verdict: str = ""
    findings: list[Finding] = field(default_factory=list)
    good: list[str] = field(default_factory=list)
    counted: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings and not self.counted


def _tool() -> Tool:
    return Tool(
        name="submit_review",
        description="What is wrong with this change. Call this once.",
        schema={
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "description": (
                        "Two or three sentences: what this change does, and "
                        "whether you would let it through as it is."
                    ),
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "where": {
                                "type": "string",
                                "description": "The file, and the function or line in it.",
                            },
                            "what": {
                                "type": "string",
                                "description": (
                                    "What is wrong, specifically enough to act "
                                    "on without opening anything else."
                                ),
                            },
                            "sure": {
                                "type": "boolean",
                                "description": (
                                    "True when you read enough to know. False "
                                    "when it is a suspicion worth checking - "
                                    "which is worth saying, not worth hiding."
                                ),
                            },
                        },
                        "required": ["where", "what", "sure"],
                        "additionalProperties": False,
                    },
                },
                "good": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Only decisions that look wrong and are right, so the "
                        "next person does not undo them. Empty is the normal "
                        "answer."
                    ),
                },
            },
            "required": ["verdict", "findings", "good"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def _said(found: dict, counted: list[str]) -> Reading:
    return Reading(
        verdict=(found.get("verdict") or "").strip(),
        findings=[
            Finding(
                where=(f.get("where") or "").strip(),
                what=(f.get("what") or "").strip(),
                sure=bool(f.get("sure", True)),
            )
            for f in found.get("findings") or []
        ],
        good=[g for g in (found.get("good") or []) if g.strip()],
        counted=counted,
    )


def read_it(
    repo: Path,
    diff: str,
    what: str,
    counted: list[str],
    on_event=None,
    budget: float = 0.0,
    engine: str = "api",
    model: str = "opus",
) -> tuple[Reading, object]:
    """Read a diff and report. Changes nothing, ever."""
    prompt = PROMPT.format(
        what=what,
        counted=(
            "Already found by counting, so do not repeat them:\n"
            + "\n".join(f"- {c}" for c in counted)
            if counted
            else "Nothing was found by counting."
        ),
        diff=diff,
    )

    if engine == "claude":
        # Enough turns to read and still answer. Six was the first number
        # here and it read the repository with all of them - thirteen tool
        # calls, then the turn limit, then nothing written. A station given
        # tools needs the turns the tools cost plus the one that answers.
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=24).structured(
            repo,
            SYSTEM,
            prompt,
            '{"verdict": "...", "findings": [{"where": "...", "what": "...", '
            '"sure": true}], "good": ["..."]}',
            on_event=on_event,
            # The diff is in the prompt. Reading the repository around it is
            # allowed, because a review that cannot look at the function
            # being called is guessing.
            tools="Read Glob Grep",
            without="Bash Edit NotebookEdit WebFetch WebSearch Task",
        )
        return _said(found, counted), _Spend(dollars, turns)

    agent = Agent(
        name="Reviewer",
        model=API_MODEL.get(model, JUDGEMENT),
        system=SYSTEM,
        tools=[],
        max_turns=2,
        budget=budget,
        on_event=on_event,
    )
    return _said(agent.run(prompt, final_tool=_tool()), counted), agent.usage


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
