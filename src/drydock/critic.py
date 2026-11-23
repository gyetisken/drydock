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

from .engines import ClaudeCodeEngine, EngineUnavailable, MalformedAnswer
from .route import slug
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
and phone.png. They are all you have, and they are enough: you are here for
the rendered result, judged against what the person asked for.

Each is the whole page, top to bottom, in one shot. The window is 1440
wide, or 390 for the phone, and the picture is as tall as the document -
so what the page looks like on arrival is the top of the image, and
everything below the fold is below it. Nothing is scrolled, nothing is
joined and nothing is scaled: there is no seam for content to be
duplicated across. If something looks like a rendering artefact, a
repeated band or a ghost of content from elsewhere on the page, it is on
the page. Say what you see and say you are unsure if you are, but do not
account for it with a stitch that did not happen.

Judge the arrival by the top of the image and the rest by the rest. A
page whose first screenful is mostly empty ground is a real fault and
you can see it here; so is a section nobody styled, four thousand pixels
down, which you could not see before.

The item above may list things that exist only in the source - that the
hours are table markup rather than a list, that a phone number is an anchor
with a tel: href, that a test was added. Those are not yours and you cannot
see them. The build, the suite, the inspector and the reviewer have already
read the change for exactly that, and they refuse on their own. Do not go
looking for the files, and do not go looking for a tool that would let you:
the files are not in this directory, nothing here will reach them, and every
turn spent trying is a turn not spent on the page. Say what you cannot see,
and judge what you can.

Read both images, then answer: of what this item owed and you can see, is it
on the page, and is the page good?"""


@dataclass
class Verdict:
    """What the one station that can see came back with.

    Three outcomes, not two, and the third is the one this was missing.

    approved        it looked and the page is right
    not approved    it looked and the page is wrong, with a reason
    failed          it could not finish, and nothing was established

    `looked=False` with `approved=True` is a fourth thing and a
    deliberate one: a machine with no browser cannot take a screenshot,
    the check does not exist here, and holding an item against a check
    nobody can run would stop every run on such a machine. That is an
    absence of the capability. `failed` is the opposite - the capability
    was there, the work was done, and the answer was lost - and it must
    never read as approval.
    """

    looked: bool
    approved: bool
    reason: str
    noticed: list
    # Why the check could not be completed, when it could not. Empty on
    # every verdict that is actually a verdict.
    failed: str = ""

    @property
    def verified(self) -> bool:
        """Whether this is an answer about the page at all."""
        return not self.failed


def _shape() -> str:
    return '{"approved": true, "reason": "...", "noticed": ["..."]}'


# Said on the second ask, and only then. The first ask is the ordinary
# one; repeating the warning every time would spend a paragraph of every
# critic's prompt on a failure that is rare.
REPAIR = """

Your last answer could not be read: the file was not valid JSON. The
usual cause is a quotation mark, a backslash or a newline inside one of
the strings that was not escaped. Answer again, with the same judgement,
and keep `reason` short - two or three sentences, plain, with no quoted
markup in it."""


def _could_not(why: str) -> Verdict:
    """A check that was possible, was attempted, and did not finish.

    Not approved, because nothing about the page was established; and
    marked `failed`, so that whoever reads it can tell this from a page
    that was looked at and found wanting.
    """
    return Verdict(looked=True, approved=False, reason=why, noticed=[], failed=why)


def look(
    url: str,
    direction: str,
    item_title: str,
    scratch: Path,
    brief: str = "",
    engine: str = "claude",
    model: str = "opus",
    on_event=None,
    also: tuple[str, ...] = (),
) -> tuple[Verdict, float]:
    """Render the pages and judge them. `looked` is false when it could not.

    `also` is other routes of the same site, photographed into directories
    of their own beside the home page's. A site is not its front door: one
    run built four pages, the critic was shown one of them, and the other
    three went to a person having been seen by nobody. They are a cap
    rather than a sweep - the caller decides how many, from what the home
    page actually links to, so a one-page site still costs one page.
    """
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

    # The rest of the site, each page in its own directory. A route that
    # will not photograph is not a reason to abandon the look - it is
    # named below as one the critic has not seen.
    pages: list[tuple[str, list]] = [("/", shots)]
    missed: list[str] = []
    for path in also:
        more = take(url.rstrip("/") + path, scratch / (slug(path) or "page"))
        (pages.append((path, more)) if more else missed.append(path))

    # A picture that stopped short says so. Without this a review of the
    # top of a page reads exactly like a review of the page, which is the
    # failure the full-page capture was written to end rather than to
    # move one cap higher.
    short = [s.said() for _, p in pages for s in p if not s.whole]
    asked = PROMPT.format(
        # The brief first and uncut. It is a few hundred characters and it
        # is the thing being judged against; the direction is the long one
        # and it is only context.
        brief=brief.strip() or "(not recorded for this run)",
        direction=direction[:8000] or "(none was written)",
        item=item_title,
    )
    # Which pages are in front of it, where, and which are not. Without
    # this the critic reads a directory of images and infers what it is
    # looking at, and a verdict on "the site" from one page is the exact
    # overreach the rest of this module is built to stop.
    if len(pages) > 1 or missed:
        asked += "\n\nThe pages you have, and where:\n"
        for path, _ in pages:
            where = slug(path) or "page"
            at = "the top of this directory" if path == "/" else f"`{where}/`"
            asked += f"  {path}  desktop.png and phone.png in {at}\n"
        if missed:
            asked += (
                "  not photographed: "
                + ", ".join(missed)
                + ". You have not seen these. Do not describe them, and do "
                "not let them count for or against the item.\n"
            )
        asked += (
            "Judge the item against every page you were given. Where a "
            "page is only reachable and not shown, say so.\n"
        )

    if short:
        asked += (
            "\n\nOne thing about the pictures themselves: "
            + " ".join(short)
            + " Judge what you can see and say plainly that the rest was "
            "not in front of you. Do not describe it and do not approve "
            "it on the strength of the part you were given."
        )

    # One repair, and only for an answer that was written and cannot be
    # read. The pictures are already on disk and are not taken again: what
    # is paid for twice is the judgement, which is the cheap half, and
    # only when the first one came back unreadable.
    spent = 0.0
    for attempt in (1, 2):
        try:
            found, dollars, _turns = ClaudeCodeEngine(
                model=model, max_turns=8
            ).structured(
                scratch,
                SYSTEM,
                asked if attempt == 1 else asked + REPAIR,
                _shape(),
                on_event=on_event,
                # It needs to open the images and nothing else.
                tools="Read",
                without="Bash Edit Glob Grep NotebookEdit WebFetch WebSearch Task",
            )
        except MalformedAnswer as exc:
            spent += 0.0
            if on_event:
                on_event(
                    "critic",
                    f"the verdict could not be read ({exc}); asking once more"
                    if attempt == 1
                    else f"the verdict could not be read twice: {exc}",
                )
            if attempt == 1:
                continue
            return _could_not(f"the critic's answer was not readable: {exc}"), spent
        except (EngineUnavailable, OSError) as exc:
            if on_event:
                on_event("critic", f"the critic could not run: {exc}")
            return _could_not(f"the critic could not run: {exc}"), spent

        spent += dollars
        if "approved" not in found:
            # It answered in the right shape and left out the verdict.
            # That is not an approval and it is not a refusal either.
            if attempt == 1:
                if on_event:
                    on_event("critic", "no verdict in the answer; asking once more")
                continue
            return _could_not("the critic answered without a verdict"), spent

        return (
            Verdict(
                looked=True,
                approved=bool(found.get("approved")),
                reason=found.get("reason") or "the critic gave no reason",
                noticed=found.get("noticed") or [],
            ),
            spent,
        )

    return _could_not("the critic did not produce a verdict"), spent


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
