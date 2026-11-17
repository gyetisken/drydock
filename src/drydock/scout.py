"""The station that improves the others.

Everything else here works from what it was told when it was written. A skill
is prior knowledge, and prior knowledge goes out of date: a framework's
recommended way of doing something changes, a library everyone used is
deprecated, what a well-made page looks like in 2026 is not what it looked
like in 2023. Nobody notices, because out-of-date guidance does not fail - it
produces confidently dated work.

So this reads what is current and writes it into the skills the crew already
uses. It is not a chat: the output is a file on disk that every later run
loads, which is what makes it compound rather than evaporate.

Two rules, and they are the whole reason this can be trusted:

Sources, or it does not go in. Every claim it writes carries the URL it came
from. A model recalling what it thinks is current is exactly the failure this
exists to fix, and recall with no source attached is indistinguishable from
it.

It adds and it corrects; it does not rewrite. A skill is somebody's
accumulated experience of a kind of work and most of it is not about
versions. Replacing the lot because one paragraph aged is how knowledge gets
lost.
"""

from dataclasses import dataclass
from pathlib import Path

from .engines import ClaudeCodeEngine

SYSTEM = """You keep a team's working knowledge current.

You are given one skill - packaged guidance a crew of agents reads before
doing a kind of work - and a subject to check it against. Find what has
actually changed and say so with sources.

What counts as worth writing down:

- Something that is now wrong. A recommended approach that has been
  superseded, a default that changed, an API that was removed.
- Something that is now true and is not mentioned. A practice that became
  standard, a trap that appeared with a new version.
- Something that is still true and is worth keeping. Say so briefly rather
  than deleting it; most of a good skill is not about versions.

What does not count:

- Your general impressions. If you cannot point at a page that says it, it
  does not go in.
- Rewording. A paragraph that is correct stays exactly as it is.
- News. A release that changes nothing about how the work is done is not a
  change to how the work is done.

Every claim carries the URL it came from, inline, in brackets. A sentence
without one is a sentence you are guessing at, and guessing is the failure
this job exists to correct."""

PROMPT = """The skill, as it stands:

---
{body}
---

Check it against what is current for: {subject}

Search for the authoritative sources - the project's own documentation and
release notes first, and recognised practitioners after that. Today is
{today}.

Report what has changed, each with its source. If nothing has, say that
plainly; an honest "this is still right" is a useful answer and a fabricated
change is not."""


@dataclass
class Finding:
    what: str
    source: str
    kind: str  # "wrong", "missing", "confirmed"


def _shape() -> str:
    return (
        '{"changes": [{"what": "...", "source": "https://...", '
        '"kind": "wrong|missing|confirmed"}], "summary": "..."}'
    )


def check(
    skill_body: str,
    subject: str,
    today: str,
    workspace: Path,
    model: str = "opus",
    on_event=None,
) -> tuple[list[Finding], str, float]:
    """Read what is current and report what the skill has wrong or is missing.

    Runs in a scratch directory rather than anybody's repository: this reads
    the web and writes one answer, and it has no business near a project.
    """
    engine = ClaudeCodeEngine(model=model, max_turns=25)
    found, dollars, _turns = engine.structured(
        workspace,
        SYSTEM,
        PROMPT.format(body=skill_body[:20_000], subject=subject, today=today),
        _shape(),
        on_event=on_event,
        # The one station that is supposed to look outside, and the only one
        # given the tools to do it.
        tools="WebSearch WebFetch",
        without="Bash Edit NotebookEdit Task",
    )
    changes = [
        Finding(
            what=str(c.get("what", "")),
            source=str(c.get("source", "")),
            kind=str(c.get("kind", "missing")),
        )
        for c in (found.get("changes") or [])
        # No source, no claim. This is the whole guarantee.
        if str(c.get("source", "")).startswith("http")
    ]
    return changes, str(found.get("summary", "")), dollars


def as_note(changes: list[Finding], subject: str, today: str) -> str:
    """What gets appended to the skill, or empty when nothing has changed."""
    worth = [c for c in changes if c.kind in ("wrong", "missing")]
    if not worth:
        return ""
    lines = [
        "",
        f"## Checked against what is current ({today})",
        "",
        (
            f"On {subject}. Each line carries the source it came from; "
            "anything that could not be sourced was left out."
        ),
        "",
    ]
    lines += [f"- {c.what} ({c.source})" for c in worth]
    return "\n".join(lines) + "\n"
