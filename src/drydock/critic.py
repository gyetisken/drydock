"""The station that looks at it.

Everything else judges by reading. A suite reads behaviour, the inspector
reads a diff, the reviewer reads a change against the item it was given. All
three can pass a page that is a flat column of stacked text on one surface,
because none of them can see, and a design skill that says "the things a
suite cannot see" was being enforced by nobody.

This one is given the rendered page as an image at two widths, what the
person actually asked for, and the direction that was written from it, and
answers one question: does the thing in front of me look like what was
asked for. It can send work back.

The brief is the standard and the direction is only context, because the
direction is a reading of the brief made before anybody had seen a page. A
run that judged against the direction alone ratified it: a page built
exactly to a direction that had drifted passed every gate, and the one
station able to see was the one agreeing with the drift.

It is honest about not running. A machine with no browser cannot take a
screenshot, and a check that silently did not happen is worse than one that
did not exist - so it says so, and the item is not held against a check
nobody made.
"""

from dataclasses import dataclass
from pathlib import Path

from .engines import ClaudeCodeEngine
from .shot import take

SYSTEM = """You are looking at a page somebody has just built, and deciding
whether it is any good and whether it is what was asked for.

What it is judged against is the brief - what the person who asked for this
actually wanted - and your own eye. The direction is one reading of that
brief, written before anybody had seen a page; it tells you what was
intended and it is worth knowing, but matching it is not the standard and
departing from it is not a fault. An engineer who found a better answer in
front of the rendered page than the direction imagined has done the job,
not broken it. A page that follows the direction to the letter and is still
a bad page is a bad page, and saying so is the entire reason you are here.

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
not usable; "the display line is about 2.5x the body text, so the page
opens quietly and nothing on it reads as a headline" is.

Refuse when what this item owed the brief is not on the page, or is on it
badly enough that a person would notice. Approve when it is there and it
works, even if you would have done it differently - you are judging the
page, not re-directing it, and "not how I would have set it" is not a
reason. If something is wrong but outside this item, put it in `noticed`.

Two things that are never a reason on their own: that the page departs
from the direction, and that it follows it. Say what you can see."""

PROMPT = """What the person asked for. This is what the finished thing is
judged against:

{brief}

The direction that was written from it, before anybody had seen a page.
Context for what was intended, not the standard:

{direction}

The item that was just finished, which is the only thing you are judging:

    {item}

The page has had this item and everything before it, and nothing after it.

Two images of the page as it renders now are in this directory: desktop.png
and phone.png. Read both, then answer: of what this item owed, is it on the
page, and is the page good?"""


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
    brief: str = "",
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
        PROMPT.format(
            # The brief first and uncut. It is a few hundred characters
            # and it is the thing being judged against; the direction is
            # the long one and it is only context.
            brief=brief.strip() or "(not recorded for this run)",
            direction=direction[:8000] or "(none was written)",
            item=item_title,
        ),
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


# The second question this module answers, and a different one. `look`
# holds a page against the direction it was built to, during a run, for
# one item. This asks what is wrong with a page when nobody said what it
# was supposed to look like - which is what somebody means by "is this
# any good".
#
# It is told what was already measured, and told not to say any of it
# again. Contrast, overflow, broken images and scripts that threw are
# arithmetic by now; an eye asked about them will guess, and a guess
# dressed as a second opinion is worse than silence.
EYES = """You are looking at a page and saying what is wrong with it.

What you are for is the half nobody can measure. A machine has already
checked, on this page, and reported separately: contrast ratios, anything
running off the edge, images that did not load, scripts that threw, links
that go nowhere, and controls that do nothing when pressed. Do not repeat
any of that and do not guess at it - if it is not in front of you, it has
been handled.

What is left is what only somebody looking can tell:

- Is there a hierarchy, or is it one flat column of text at one size?
- Does anything overlap, crowd, or sit so close to something else that
  they read as one thing?
- Is the spacing even, or does one band have four times the air of the
  one beside it?
- Does it look like the thing it is for, or like a template with the
  words changed?
- Is anything obviously unfinished - a placeholder, lorem, a box with
  nothing in it, an element half off a band?

Be specific about where. "The layout is unbalanced" helps nobody; "the
three cards sit hard against the left edge while the heading above them
is centred" can be acted on.

If it looks right, say so and stop. A page with nothing wrong with it is
a real answer, and one of these written every time somebody asks teaches
people to stop reading them.

Everything you say here is judgement rather than measurement, and will be
labelled as such. That is the reason to be careful with it, not a reason
to hedge: say what you actually see."""

EYES_PROMPT = """Two images of the page are in this directory: desktop.png
and phone.png. Read both.

{measured}

What is wrong with it that nobody could have measured?"""


def what_looks_wrong(
    scratch: Path,
    measured: list[str],
    model: str = "opus",
    on_event=None,
) -> tuple[list[str], float]:
    """What an eye finds on a page, with the measurements already taken."""
    prompt = EYES_PROMPT.format(
        measured=(
            "Already measured and reported, so leave these alone:\n"
            + "\n".join(f"- {m}" for m in measured[:20])
            if measured
            else "The measurements found nothing to report."
        )
    )
    found, dollars, _turns = ClaudeCodeEngine(model=model, max_turns=6).structured(
        scratch,
        EYES,
        prompt,
        '{"looks_right": true, "found": ["..."]}',
        on_event=on_event,
        # It opens two images and nothing else.
        tools="Read",
        without="Bash Edit Glob Grep NotebookEdit WebFetch WebSearch Task",
    )
    said = [f.strip() for f in (found.get("found") or []) if str(f).strip()]
    # The dollars, the way `look` above reports them: this module hands
    # back a number and the caller decides what to do with it.
    return ([] if found.get("looks_right") and not said else said), dollars
