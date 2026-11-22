"""Whether the page does what somebody said it would.

The probe reports facts: the text, the headings, the links, how many rows
are in each list and table. Deciding whether "the hours show the seven-day
week" is true of those facts needs meaning, and meaning is what a model is
for - so one is asked.

What keeps that honest is the shape of the answer. Every verdict has to
quote the thing on the page it rests on, and the quote is then looked for
in the facts. A verdict whose evidence is not there is not a verdict; it
is downgraded to "could not check", which is a true thing to say and a
useless thing to pretend.

So the model supplies meaning and arithmetic supplies the check on it,
which is the arrangement this whole program is built out of.
"""

import re
from dataclasses import dataclass, field

from .agent import API_MODEL, JUDGEMENT, Agent, Tool
from .engines import ClaudeCodeEngine

# What a verdict can be. `MET` and `MISSING` are claims about the page;
# `UNKNOWN` is a claim about this tool, and keeping the two apart is the
# entire point of having three.
MET = "met"
MISSING = "missing"
UNKNOWN = "could not check"

SYSTEM = """You are told what a page was supposed to do, and given what is actually on
it: its text, its headings, its links and where they go, how many rows are
in each list and table, and what happened when each control was pressed.
You are not looking at a picture, and anything that is not in what you were
given, you were not given.

For each thing it was supposed to do, answer one of three:

- met: the page facts show it. Quote the exact text or name the exact
  count you are relying on.
- missing: the page facts show it is not there. Quote what is there
  instead, or say which count is wrong.
- could not check: settling it needs something you were not given -
  hovering, a second page, a login, waiting for something to happen, or
  how it looks rather than what it says. Note that pressing is not in
  that list any more: what each control did when it was pressed is
  given to you, and a control that was not pressed says why.

"could not check" is a real answer and the right one more often than
people expect. A claim about behaviour cannot be settled by text. Guessing
`met` because the words appear nearby is the one failure that matters
here, because somebody will read it as checked.

Quote from what you were given, exactly, in `evidence`. The quote is
looked for in the page afterwards, and a verdict whose evidence is not
there is thrown away."""

PROMPT = """What this was supposed to do:

{claims}

What is on the page:

Title: {title}

Headings:
{headings}

Links and buttons:
{links}

Where the links go:
{going}

What happened when each was pressed:
{pressed}

Lists and tables:
{lists}

The text of the page:

{text}"""


@dataclass
class Checked:
    claim: str
    verdict: str = UNKNOWN
    evidence: str = ""
    why: str = ""
    # Whether the quoted evidence was actually found on the page. False
    # turns any verdict into `could not check`, which is why it is kept
    # rather than only acted on.
    quoted: bool = True

    @property
    def settled(self) -> bool:
        return self.verdict in (MET, MISSING)


@dataclass
class Report:
    checks: list[Checked] = field(default_factory=list)

    def of(self, verdict: str) -> list[Checked]:
        return [c for c in self.checks if c.verdict == verdict]

    @property
    def say(self) -> str:
        met, missing, unknown = (
            len(self.of(MET)),
            len(self.of(MISSING)),
            len(self.of(UNKNOWN)),
        )
        return (
            f"{met} met, {missing} missing, {unknown} could not be checked"
            if self.checks
            else "nothing was claimed"
        )


def _tool() -> Tool:
    return Tool(
        name="submit_checks",
        description="One verdict per thing claimed. Call this once.",
        schema={
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {
                                "type": "string",
                                "description": "The thing, copied as it was given.",
                            },
                            "verdict": {
                                "type": "string",
                                "enum": [MET, MISSING, UNKNOWN],
                            },
                            "evidence": {
                                "type": "string",
                                "description": (
                                    "The exact text from the page, or the exact "
                                    "count, that settles it. Empty only when the "
                                    "verdict is 'could not check'."
                                ),
                            },
                            "why": {
                                "type": "string",
                                "description": "One sentence, if it needs one.",
                            },
                        },
                        "required": ["claim", "verdict", "evidence", "why"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["checks"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def _tidy(said: str) -> str:
    """Whitespace flattened, so a quote that crossed a line still matches."""
    return re.sub(r"\s+", " ", (said or "")).strip().lower()


def _was_said(evidence: str, haystack: str) -> bool:
    """Whether a quoted piece of evidence is actually on the page.

    Loose about whitespace and case, strict about everything else. A
    quote nobody can find is not evidence, and the verdict resting on it
    is worth exactly as much.
    """
    quote = _tidy(evidence)
    if not quote:
        return False
    if quote in haystack:
        return True
    # A count rather than a quote - "7 rows" - is evidence of a different
    # kind, and the numbers in it are what there is to check.
    numbers = re.findall(r"\d+", quote)
    return bool(numbers) and all(n in haystack for n in numbers)


def check(
    repo,
    claims: list[str],
    seen,
    pressed=None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "claude",
    model: str = "opus",
) -> tuple[Report, object]:
    """Hold each claim against what the page actually says."""
    if not claims:
        return Report(), _Spend(0.0, 0)

    prompt = PROMPT.format(
        claims="\n".join(f"- {c}" for c in claims),
        title=seen.title or "(none)",
        headings="\n".join(f"- {h}" for h in seen.headings) or "(none)",
        links="\n".join(f"- {t}" for t in seen.links) or "(none)",
        going="\n".join(
            f"- {link['said'] or '(no text)'} -> {link['to']}"
            for link in getattr(seen, "going", [])
        )
        or "(none)",
        lists="\n".join(
            f"- a {row['what']} with {row['rows']} rows: {row['said'][:160]}"
            for row in seen.lists
        )
        or "(none)",
        pressed="\n".join(
            f"- {one.said}: {one.why or one.did}" for one in (pressed or [])
        )
        or "(nothing was pressed)",
        text=seen.text or "(the page has no text)",
    )

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=2).structured(
            repo,
            SYSTEM,
            prompt,
            '{"checks": [{"claim": "...", "verdict": "met", '
            '"evidence": "...", "why": "..."}]}',
            on_event=on_event,
            tools="",
            without="Bash Read Glob Grep Edit NotebookEdit WebFetch WebSearch Task",
        )
        return _said(found, claims, seen, pressed), _Spend(dollars, turns)

    agent = Agent(
        name="Critic",
        model=API_MODEL.get(model, JUDGEMENT),
        system=SYSTEM,
        tools=[],
        max_turns=2,
        budget=budget,
        on_event=on_event,
    )
    return (
        _said(agent.run(prompt, final_tool=_tool()), claims, seen, pressed),
        agent.usage,
    )


def _said(found: dict, claims: list[str], seen, pressed=None) -> Report:
    """Read the answer back, and check the evidence it rests on."""
    page = _tidy(
        " ".join(
            [seen.title or "", seen.text or ""]
            + list(seen.headings)
            + list(seen.links)
            + [f"{link['said']} {link['to']}" for link in getattr(seen, "going", [])]
            + [f"{row['rows']} {row['said']}" for row in seen.lists]
            + [f"{one.said} {one.why or one.did}" for one in (pressed or [])]
        )
    )
    checks = []
    for said in found.get("checks") or []:
        one = Checked(
            claim=(said.get("claim") or "").strip(),
            verdict=(said.get("verdict") or UNKNOWN).strip(),
            evidence=(said.get("evidence") or "").strip(),
            why=(said.get("why") or "").strip(),
        )
        if one.settled:
            one.quoted = _was_said(one.evidence, page)
            if not one.quoted:
                # It was sure, and the thing it was sure about is not on
                # the page. That is not a verdict about the page.
                one.verdict = UNKNOWN
                one.why = (
                    f"the evidence given for this was not found on the page: "
                    f'"{one.evidence[:80]}"'
                )
        checks.append(one)

    # Anything that came back about nothing anybody asked, and anything
    # asked that came back about nothing.
    answered = {_tidy(c.claim) for c in checks}
    for claim in claims:
        if _tidy(claim) not in answered:
            checks.append(
                Checked(claim=claim, verdict=UNKNOWN, why="no answer came back for it")
            )
    return Report(checks=checks)


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
