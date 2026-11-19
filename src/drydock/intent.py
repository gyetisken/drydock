"""Working out what somebody meant, without asking a model.

Typing `/fix` before a sentence that obviously describes a fix is a tax on
using this. The slash commands stay - they are how you overrule this - but
nobody should have to remember them.

The classification is deterministic on purpose. A model call to decide what
a model call should do adds a second and a fraction of a cent to every
message, and the decision is almost always obvious from the sentence and
the state of the repository. Where it is genuinely not obvious this says so
rather than guessing, and the expensive path is never taken on a guess: an
unclear message gets the cheap reading, which can be followed by the
expensive one, and not the other way round.

Everything it decides is shown, with the reason, and can be overruled in one
click. A router that quietly chooses wrong is worse than no router.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Asking rather than instructing. The question mark alone is not enough -
# "can you fix the header?" is an instruction wearing a question mark.
ASKING = re.compile(
    r"^\s*(what|where|which|who|why|how|when|is|are|does|do|did|can i|"
    r"should i|explain|tell me|show me|describe|list)\b",
    re.IGNORECASE,
)
# "can you fix the header?" is an instruction with a question mark on it.
# "why does the build fail?" is a question containing the word build. The
# difference is the opening, not the vocabulary: a polite request starts
# with a modal, and a question starting with why or what never does.
POLITE_INSTRUCTION = re.compile(
    r"^\s*(please\b|(can|could|would|will)\s*(you)\b)",
    re.IGNORECASE,
)

# Saying hello, and whatever comes after it. A greeting is not a request to
# change anything, and `hello, how are you today?` started a baseline suite,
# an Analyst reading the repository and a Planner writing items - a full
# planning run, for a hello. Stripped like a polite prefix rather than
# matched as its own command, so that `hi, add a logout button` is still an
# instruction with a hello on the front of it.
GREETING = re.compile(
    r"^\s*(hey|hi|hello|yo|hiya|howdy|good\s+(morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|ta|cheers|ok|okay|cool|nice|great|"
    r"sorry|bye|goodbye|see\s+you)\b[\s,!.:;-]*",
    re.IGNORECASE,
)

# Nothing left to act on. Punctuation, an emoji, a trailing "there" or
# "mate" - the shapes a bare greeting ends in.
NOTHING_LEFT = re.compile(
    r"^[\s,.!?;:\-–—)(\u2000-\u3300\U0001F000-\U0001FAFF]*"
    r"(there|all|everyone|mate|man|folks|again)?[\s,.!?;:\-]*$",
    re.IGNORECASE,
)

# Starting something that does not exist.
STARTING = re.compile(
    r"\b(build|create|make|start|scaffold|set up|spin up)\b.{0,40}?"
    r"\b(site|website|page|app|service|api|project|tool|landing|shop|blog)\b",
    re.IGNORECASE,
)

# Moving from one thing to another.
MIGRATING = re.compile(
    r"\b(migrate|port|convert|move)\b.{0,60}?\bto\b|\bfrom\s+\S+\s+to\s+\S+",
    re.IGNORECASE,
)
UPGRADING = re.compile(
    r"\b(upgrade|bump|update)\b.{0,40}?\b(to|from)\b.{0,30}?"
    r"(\d+(\.\d+)*|latest|v\d+)",
    re.IGNORECASE,
)

# Looking without changing.
AUDITING = re.compile(
    r"\b(audit|review|look (at|over)|assess|find (problems|issues|bugs)|"
    r"what('s| is) (wrong|fragile|risky))\b",
    re.IGNORECASE,
)

# Just run the thing.
CHECKING = re.compile(
    r"^\s*(run|do) the (tests|suite|build)\b|^\s*(check|test|build) (it|this)\b",
    re.IGNORECASE,
)

# A change small enough not to need a plan: one clause, one target.
SMALL_VERB = re.compile(
    r"\b(fix|rename|change|tweak|correct|adjust|replace|swap|bump|"
    r"remove|delete|drop|add)\b",
    re.IGNORECASE,
)


@dataclass
class Guess:
    command: str
    why: str
    sure: bool


# Every verb that asks for a change. Counting these is how one small change
# is told apart from three of them in a sentence: "add a contact form, wire
# it to the validator, and write the tests" is one sentence and three jobs,
# and planning it is the whole reason the plan exists.
CHANGE_VERBS = re.compile(
    r"\b(fix|rename|change|tweak|correct|adjust|replace|swap|bump|remove|"
    r"delete|drop|add|wire|write|implement|refactor|move|split|extract|"
    r"introduce|support|handle|validate|render|style)\b",
    re.IGNORECASE,
)


def _jobs(text: str) -> int:
    """How many separate changes this is asking for."""
    return len({m.group(0).lower() for m in CHANGE_VERBS.finditer(text)})


def read(text: str, repo: Path | None = None) -> Guess:
    """Which command this sentence is asking for, and why."""
    said = text.strip()
    if said.startswith("/"):
        return Guess(said.split()[0], "you asked for it by name", True)

    # A hello on the front of an instruction is still an instruction; a
    # hello on its own is not one at all.
    if GREETING.match(said):
        rest = GREETING.sub("", said, count=1).strip()
        if NOTHING_LEFT.match(rest):
            return Guess(
                "/ask",
                "this is not asking for anything to be changed",
                True,
            )
        said = rest

    if POLITE_INSTRUCTION.match(said):
        said = POLITE_INSTRUCTION.sub("", said).strip()

    if CHECKING.search(said):
        return Guess("/check", "this is asking to run what is already there", True)

    # Before the general question test: "what is fragile here" is a request
    # for an audit wearing a question mark, and the audit is the better
    # answer to it. Both read and neither changes anything, so being wrong
    # here costs a reading, not a repository.
    if AUDITING.search(said):
        return Guess("/audit", "this is asking to look rather than to change", True)

    if ASKING.match(said) and not POLITE_INSTRUCTION.match(said):
        return Guess("/ask", "this is a question, so nothing will be changed", True)

    if UPGRADING.search(said):
        return Guess("/upgrade", "this names a version to move to", True)

    if MIGRATING.search(said):
        return Guess("/migrate", "this names a thing to move from and to", True)

    # An empty repository settles it: there is nothing here to change.
    empty = False
    if repo is not None:
        try:
            empty = not any(p.name != ".git" for p in repo.iterdir())
        except OSError:
            empty = False

    if STARTING.search(said) or (empty and len(said.split()) > 4):
        return Guess(
            "/new",
            "this is starting something"
            + (" and the folder is empty" if empty else ""),
            True,
        )

    if SMALL_VERB.search(said) and _jobs(said) <= 1 and len(said.split()) <= 30:
        return Guess(
            "/fix",
            "one small change, so it goes straight to the work without a plan",
            True,
        )

    # Anything else is a change of unknown size, and the honest answer to
    # unknown size is the path that writes a plan and asks before touching
    # anything.
    return Guess(
        "/do",
        "this is a change and its size is not obvious, so it will be planned "
        "and shown to you before anything happens",
        False,
    )
