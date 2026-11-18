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
# Everything that reports against an item. "restarted" is not a gate -
# nothing was judged - but it arrives the same way and is worth counting.
GATES = ("inspector", "reviewer", "critic", "asked", "answered", "restarted")


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
    restarts: int = 0
    # Seconds from the start of the run, so overlapping items in a wave
    # can be laid against each other.
    began: float = 0.0
    ended: float = 0.0

    @property
    def share(self) -> str:
        if self.seconds <= 0:
            return ""
        return f"{self.working / self.seconds * 100:.0f}% working"


@dataclass
class Pace:
    """A whole run, measured.

    Every number here is read off the events a run already writes. The
    point of having them is that nothing about speed gets claimed without
    one: an afternoon went on fixing things that turned out not to be the
    bottleneck, and the bottleneck was never measured until afterwards.
    """

    seconds: float = 0.0
    before_the_plan: float = 0.0
    # When the first file was written, and when something was first
    # committed - the two numbers somebody waiting actually feels.
    to_first_change: float = 0.0
    to_first_landed: float = 0.0
    # Model calls and tool calls, which is what the cost is made of.
    stations: int = 0
    tool_calls: int = 0
    # Times an item had to be tried again, and times a worker had to be
    # restarted because it was taken away rather than because it failed.
    retries: int = 0
    restarts: int = 0
    dollars: float = 0.0
    items: list[Spell] = field(default_factory=list)

    @property
    def working(self) -> float:
        return sum(s.working for s in self.items)

    @property
    def checking(self) -> float:
        return sum(s.checking for s in self.items)

    @property
    def waiting(self) -> float:
        """Time nobody was working on anything.

        Items in a wave finish at different times and the wave does not
        end until the slowest one does, so an item can be finished and
        still be inside its own elapsed time. Reported separately because
        it is the one kind of slowness that is this program's own fault
        rather than the work's.
        """
        return max(0.0, self.seconds - self.before_the_plan - self.busy)

    @property
    def busy(self) -> float:
        """Wall clock during which at least one item was being worked on."""
        # `ended` alone decides: an item that started in the first second
        # of a run has began == 0, which is a real time and a false value.
        spans = sorted((s.began, s.ended) for s in self.items if s.ended)
        total, edge = 0.0, None
        for start, end in spans:
            if edge is None or start > edge:
                total += end - start
                edge = end
            elif end > edge:
                total += end - edge
                edge = end
        return total

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
            if spell.restarts:
                line += f", {spell.restarts} restart(s)"
            out.append(line + ".")

        if self.to_first_change:
            out.append(
                f"{_said(self.to_first_change)} before the first file changed"
                + (
                    f", {_said(self.to_first_landed)} before anything landed."
                    if self.to_first_landed
                    else "."
                )
            )
        if self.waiting > 30:
            out.append(
                f"{_said(self.waiting)} of it was waiting - items in a round "
                "finish at different times and the round ends with the "
                "slowest."
            )
        if self.tool_calls:
            out.append(
                f"{self.stations} stations, {self.tool_calls} tool calls"
                + (f", {self.retries} retried" if self.retries else "")
                + (f", {self.restarts} restarted" if self.restarts else "")
                + "."
            )
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
    to_first_change = to_first_landed = 0.0
    stations = tool_calls = restarts = 0
    dollars = 0.0
    spells: dict[int, Spell] = {}
    started: dict[int, datetime] = {}
    checking_from: dict[int, datetime] = {}

    for event in events:
        at = _clock(event.get("at", ""))
        if at is None:
            continue
        kind = event.get("kind")

        if first is not None:
            at_second = _gap(first, at)
            if kind == "agent.tool":
                tool_calls += 1
                if not to_first_change and _is_a_write(event):
                    to_first_change = at_second
            elif kind == "agent.state" and event.get("state") == "working":
                stations += 1
            elif kind == "spend":
                try:
                    dollars = max(dollars, float(event.get("total") or dollars))
                except (TypeError, ValueError):
                    pass

        if kind == "run.started":
            # One log holds a run and every time it was picked back up. A
            # resumed run is the one somebody is looking at, and adding the
            # attempts together measures nothing anybody experienced.
            first = last = at
            plan_at = None
            spells, started, checking_from = {}, {}, {}
            to_first_change = to_first_landed = 0.0
            stations = tool_calls = restarts = 0
            dollars = 0.0
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
            spell = spells.setdefault(number, Spell(item=number))
            spell.began = _gap(first, at)
        elif kind == "gate":
            number = event.get("id")
            if number is None or event.get("who") not in GATES:
                continue
            spell = spells.setdefault(number, Spell(item=number))
            if event.get("who") == "restarted":
                spell.restarts += 1
                restarts += 1
                continue
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
            spell.ended = _gap(first, at)
            if spell.outcome == "done" and not to_first_landed:
                to_first_landed = spell.ended
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
        to_first_change=to_first_change,
        to_first_landed=to_first_landed,
        stations=stations,
        tool_calls=tool_calls,
        retries=sum(max(0, s.attempts - 1) for s in spells.values()),
        restarts=restarts,
        dollars=dollars,
        items=[spells[k] for k in sorted(spells)],
    )


# Tool calls that changed a file, as opposed to looking at one. The first
# of these is the moment the waiting stops being planning.
WRITES = ("write", "edit", "notebookedit", "multiedit")


def _is_a_write(event: dict) -> bool:
    said = str(event.get("detail") or "").strip().lower()
    return any(said.startswith(name) for name in WRITES)


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
