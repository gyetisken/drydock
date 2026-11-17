"""Where a run's minutes went.

Every time this program has felt slow, the answer has been a guess. The
events already carry the times - an item starts, four gates report, the item
ends - so the breakdown is arithmetic over a log that is already being
written, with no model and no extra instrumentation.

It is kept honest about one thing: it measures wall clock, and items in the
same wave run at the same time. Adding up the items of a parallel wave and
calling it the run's duration would overstate it, so waves are measured by
when the first one started and the last one finished.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# The order the gates speak in. Two of them are code and take no noticeable
# time; the other two are a model reading a diff and a model looking at a
# page, which is where a surprising share of a run goes.
GATES = ("inspector", "reviewer", "critic", "asked", "answered")


@dataclass
class Spell:
    """One item, and how its time was divided."""

    item: int
    title: str = ""
    seconds: float = 0.0
    working: float = 0.0
    checking: float = 0.0
    outcome: str = ""
    attempts: int = 1

    @property
    def share(self) -> str:
        if self.seconds <= 0:
            return ""
        return f"{self.working / self.seconds * 100:.0f}% working"


@dataclass
class Pace:
    """A whole run, measured."""

    seconds: float = 0.0
    before_the_plan: float = 0.0
    items: list[Spell] = field(default_factory=list)

    @property
    def working(self) -> float:
        return sum(s.working for s in self.items)

    @property
    def checking(self) -> float:
        return sum(s.checking for s in self.items)

    def __str__(self) -> str:
        return "\n".join(self.lines())

    def lines(self) -> list[str]:
        """The breakdown, as short lines meant to be read once."""
        if not self.seconds and not self.items:
            return []
        out = [f"{_said(self.seconds)} from the first word to the last."]
        if self.before_the_plan:
            out.append(
                f"{_said(self.before_the_plan)} of that was before any code was "
                "written - reading the repository, deciding how it should look, "
                "and writing the plan."
            )
        for spell in self.items:
            line = f"Item {spell.item}: {_said(spell.seconds)}"
            if spell.checking:
                line += (
                    f" - {_said(spell.working)} working, "
                    f"{_said(spell.checking)} being checked"
                )
            if spell.attempts > 1:
                line += f", over {spell.attempts} attempts"
            if spell.outcome == "working":
                line += ", still going"
            out.append(line + ".")
        return out


def _said(seconds: float) -> str:
    """Seconds, as somebody would say them out loud.

    The minutes are floored, not rounded. Formatting 392 seconds by rounding
    the minutes reads "7m 32s", which is a minute longer than it took and
    disagrees with its own seconds.
    """
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def _clock(stamp: str) -> datetime | None:
    """Read one of the log's times. They carry no date, only a wall clock."""
    try:
        return datetime.strptime(stamp, "%H:%M:%S")
    except (TypeError, ValueError):
        return None


def _gap(start: datetime | None, end: datetime | None) -> float:
    """Seconds between two wall clocks, allowing for one midnight."""
    if start is None or end is None:
        return 0.0
    if end < start:
        end += timedelta(days=1)
    return (end - start).total_seconds()


def read(events: list[dict]) -> Pace:
    """Measure a run from its events.

    Deliberately tolerant. A log is written while a run happens and can stop
    anywhere - a crash, a kill, a laptop closing - so every one of these
    timings is optional and a missing one reports zero rather than refusing
    to report at all.
    """
    first = last = None
    plan_at = None
    spells: dict[int, Spell] = {}
    started: dict[int, datetime] = {}
    checking_from: dict[int, datetime] = {}

    for event in events:
        at = _clock(event.get("at", ""))
        if at is None:
            continue
        kind = event.get("kind")

        if kind == "run.started":
            # One log holds a run and every time it was picked back up. A
            # resumed run is the one somebody is looking at, and adding the
            # attempts together measures nothing anybody experienced.
            first = last = at
            plan_at = None
            spells, started, checking_from = {}, {}, {}
            continue

        first = first or at
        last = at

        if kind == "plan.ready":
            plan_at = at
        elif kind == "item.start":
            number = event.get("id")
            if number is None:
                continue
            started[number] = at
            checking_from.pop(number, None)
            spells.setdefault(number, Spell(item=number))
        elif kind == "gate":
            number = event.get("id")
            if number is None or event.get("who") not in GATES:
                continue
            spell = spells.setdefault(number, Spell(item=number))
            # The first gate to speak marks the end of the writing. Anything
            # after it is the harness, not the engineer.
            if number not in checking_from:
                checking_from[number] = at
                spell.working = _gap(started.get(number), at)
        elif kind == "item.done":
            number = event.get("id")
            # An item whose result is replayed when a run is picked back up
            # was not worked in this sitting, and reporting it as nought
            # seconds of work is worse than not reporting it.
            if number is None or number not in started:
                continue
            spell = spells.setdefault(number, Spell(item=number))
            spell.outcome = event.get("outcome", "")
            spell.attempts = max(1, int(event.get("attempts") or 1))
            spell.seconds = _gap(started.get(number), at)
            if number in checking_from:
                spell.checking = _gap(checking_from[number], at)
                # An item worked in a worktree beside its neighbours, or one
                # whose start was never recorded, can produce a checking time
                # longer than the item itself. Report the part that is
                # certainly true rather than an impossible number.
                if spell.checking > spell.seconds:
                    spell.checking = 0.0
                    spell.working = spell.seconds
            else:
                # It never reached a gate: stopped, or stopped itself.
                spell.working = spell.seconds

    # An item that started and has not reported is still going. Its time so
    # far is the honest answer to "how long is this taking", which is the
    # question somebody watching is actually asking.
    for number, spell in spells.items():
        if not spell.outcome and number in started:
            spell.seconds = _gap(started[number], last)
            spell.working = spell.seconds - spell.checking
            spell.outcome = "working"

    return Pace(
        seconds=_gap(first, last),
        before_the_plan=_gap(first, plan_at),
        items=[spells[k] for k in sorted(spells)],
    )


def from_log(path: Path) -> Pace:
    """Measure a run from the file its events were written to."""
    import json

    events = []
    for line in path.read_text().splitlines() if path.exists() else []:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return read(events)
