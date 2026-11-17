"""Which items can be worked on at the same time.

Items are sequential by default because each one assumes the last one
landed, and that assumption is what makes reverting a single item safe. But
it is not true of every pair: a data module and a stylesheet need nothing
from each other, and making one wait for the other is the difference between
a run that takes twenty minutes and one that takes forty.

So the planner says what each item needs, and this works out the waves. The
rules are deliberately strict, because the cost of being wrong is not a
slower run - it is two workers editing the same file and an item rolled back
for a conflict that was never about the work.

Nothing here talks to a model. Given the same plan it gives the same waves,
every time.
"""

from dataclasses import dataclass


@dataclass
class Wave:
    """A set of items that may be worked on together."""

    items: list
    why: str


def _claimed(item) -> set[str]:
    """The files an item says it will touch, normalised."""
    return {f.strip().lstrip("./") for f in (item.files or []) if f.strip()}


def overlap(a, b) -> bool:
    """Whether two items would be writing in the same place.

    A glob is treated as touching anything under its directory, because an
    item that says `src/**/*.ts` and one that says `src/hours.ts` are going
    to meet. Being too careful here costs a little time; being not careful
    enough costs a conflict.
    """
    for one in _claimed(a):
        for two in _claimed(b):
            if one == two:
                return True
            head_one = one.split("*")[0].rstrip("/")
            head_two = two.split("*")[0].rstrip("/")
            if not head_one or not head_two:
                return True
            if head_one.startswith(head_two) or head_two.startswith(head_one):
                return True
    return False


def plan_waves(items: list, done: set[int] | None = None) -> list[Wave]:
    """Group items into waves that can each be worked on together.

    An item joins a wave when everything it needs has already landed in an
    earlier wave, and when it does not touch a file claimed by anything else
    in the same wave. An item that claims no files at all goes alone: not
    knowing what it will touch is not the same as knowing it touches nothing.
    """
    landed = set(done or ())
    left = [i for i in items if i.id not in landed]
    waves: list[Wave] = []

    while left:
        ready = [i for i in left if all(n in landed for n in (i.needs or []))]
        if not ready:
            # A cycle, or a dependency on something that will never land.
            # Fall back to the order they were written in: a slower run is
            # better than a run that stops.
            waves.append(Wave([left[0]], "its dependencies cannot be satisfied"))
            landed.add(left[0].id)
            left = left[1:]
            continue

        wave: list = []
        for item in ready:
            if not _claimed(item):
                if not wave:
                    wave = [item]
                    break
                continue
            if any(overlap(item, other) for other in wave):
                continue
            if any(not _claimed(other) for other in wave):
                continue
            wave.append(item)

        waves.append(
            Wave(
                wave,
                "nothing in this group needs anything from the others"
                if len(wave) > 1
                else "this one has to be on its own",
            )
        )
        landed.update(i.id for i in wave)
        left = [i for i in left if i.id not in landed]

    return waves


def how_much_faster(waves: list[Wave]) -> str:
    """What the waves buy, in plain terms, or nothing when they buy nothing."""
    items = sum(len(w.items) for w in waves)
    if items <= len(waves):
        return ""
    return (
        f"{items} items in {len(waves)} rounds - "
        f"{items - len(waves)} of them alongside something else"
    )


def stranded(items: list, failed: set[int]) -> dict[int, list[int]]:
    """Which items cannot be attempted because something they need is gone.

    A failed item used to stop the whole run, on the reasoning that a later
    item usually assumes an earlier one landed. Usually is not always, and
    the plan now says which: every item names what it needs. So the ones
    that are genuinely stranded are worked out and the rest are still
    attempted, rather than the run throwing away work it could have done.

    Returns each stranded item's id against the failed items it was waiting
    on, directly or through something else.
    """
    waiting_on: dict[int, list[int]] = {}
    gone = set(failed)
    # Items are in planned order and a need always points backwards, so one
    # pass settles it - but it is written to tolerate a plan where that is
    # not true, because a plan is written by a model.
    for _ in range(len(items)):
        changed = False
        for item in items:
            if item.id in gone:
                continue
            blocked = sorted(n for n in getattr(item, "needs", []) if n in gone)
            if blocked:
                waiting_on[item.id] = blocked
                gone.add(item.id)
                changed = True
        if not changed:
            break
    return waiting_on
