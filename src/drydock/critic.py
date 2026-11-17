"""The station that looks at it.

Everything else judges by reading. A suite reads behaviour, the inspector
reads a diff, the reviewer reads a change against the item it was given. All
three can pass a page that is a flat column of stacked text on one surface,
because none of them can see, and a design skill that says "the things a
suite cannot see" was being enforced by nobody.

This one is given the rendered page as an image at two widths, and the
direction it was supposed to be built to, and answers one question: does the
thing in front of me look like what was asked for. It can send work back.

It is honest about not running. A machine with no browser cannot take a
screenshot, and a check that silently did not happen is worse than one that
did not exist - so it says so, and the item is not held against a check
nobody made.
"""

from dataclasses import dataclass
from pathlib import Path

from .engines import ClaudeCodeEngine
from .shot import take

SYSTEM = """You are looking at a page somebody has just built, against the
direction it was supposed to be built to.

You have been art-directing for twenty years and your eye is the only one in
this process. Nothing before you can see: the tests check behaviour, the
diff review checks scope. A page that is one flat centred column of stacked
text passes all of it, and that is the page you are here to catch.

**Judge this item, not the whole page.** You are given one item out of a
sequence, and the page in front of you is the page as it stands after that
item and no further. Things the direction asks for that a later item will
bring are not this item's failures - a stylesheet item owes you tokens and a
shell, not a finished hero. Refusing an item for work it was never given is
how a run ends up doing everything twice.

So the question is narrow: of the things this item was responsible for, is
any of them not actually on the page, or on the page wrongly? Everything
else true and wrong goes in `noticed`, where the next item can pick it up.

Two exceptions, which are never out of scope because they are never
intentional: text that overflows or is clipped at either width, and text a
person cannot read against its background. If you can see either, say so and
refuse, whoever introduced it.

Look at the images and answer honestly:

- Does the composition described actually exist on the page? A named
  two-column split that rendered as one column is not a near miss, it is the
  thing not being there.
- Is there real scale contrast, or is everything within a size or two of
  everything else?
- Is there any structure at all - an edge, a band, a rule, a second surface,
  a change of density - or is the whole page one plane?
- Does the eye have somewhere to land, and does it move?
- On the phone image: is it usable, or is it the desktop layout squeezed?
- Contrast, and anything a person would struggle to read.

Be specific and point at what you are looking at. "The hero feels weak" is
not usable; "the display line is about 2.5x the body text where the
direction asked for 6x, so the page opens quietly and nothing on it reads as
a headline" is.

Reject when the page does not carry out the direction. Approve when it does,
even if you would have directed it differently - you are not re-directing
it. If something is wrong but outside this item, put it in `noticed`."""

PROMPT = """The direction the whole project is being built to, for context:

{direction}

The item that was just finished, which is the only thing you are judging:

    {item}

The page has had this item and everything before it, and nothing after it.

Two images of the page as it renders now are in this directory: desktop.png
and phone.png. Read both, then answer: did this item put its part of the
direction on the page?"""


@dataclass
class Verdict:
    looked: bool
    approved: bool
    reason: str
    noticed: list


def _shape() -> str:
    return '{"approved": true, "reason": "...", "noticed": ["..."]}'


def look(
    url: str,
    direction: str,
    item_title: str,
    scratch: Path,
    engine: str = "claude",
    model: str = "opus",
    on_event=None,
) -> tuple[Verdict, float]:
    """Render the page and judge it. `looked` is false when it could not."""
    shots = take(url, scratch)
    if not shots:
        return (
            Verdict(
                looked=False,
                approved=True,
                reason=(
                    "no browser on this machine, so the page was not looked "
                    "at. Install Chrome, Chromium or Edge and this check runs."
                ),
                noticed=[],
            ),
            0.0,
        )

    found, dollars, _turns = ClaudeCodeEngine(model=model, max_turns=8).structured(
        scratch,
        SYSTEM,
        PROMPT.format(direction=direction[:8000], item=item_title),
        _shape(),
        on_event=on_event,
        # It needs to open the images and nothing else.
        tools="Read",
        without="Bash Edit Glob Grep NotebookEdit WebFetch WebSearch Task",
    )

    return (
        Verdict(
            looked=True,
            # Fails closed, like the other reviewer: a station that did not
            # answer has not approved anything.
            approved=bool(found.get("approved")) if "approved" in found else False,
            reason=found.get("reason") or "the critic did not return a verdict",
            noticed=found.get("noticed") or [],
        ),
        dollars,
    )
