"""Who is in the room, and what each of them is allowed to do.

Kept in one place because it was in three: the office draws them, the
session names them when it skips one, and the slash menu had never heard of
them at all. Three lists of the same nine things is three lists that drift.

What each entry says is deliberately narrow. A station is defined by what it
decides and whether it can refuse, not by a personality.
"""

from dataclasses import dataclass

from .pace import clock, gap


@dataclass(frozen=True)
class Station:
    name: str
    does: str
    # What it is given, and what it hands on. The pairs are the pipeline.
    reads: str
    says: str
    # Whether it can send an item back. Three can, and that is the whole
    # design: the thing that writes the code is not the thing that decides
    # the code may stay.
    can_refuse: bool
    # Whether a model is involved at all. Two of them are arithmetic, which
    # is why they cannot be argued with.
    is_code: bool
    when: str


CREW = (
    Station(
        "Analyst",
        "reads the repository and reports what bears on the job",
        "the repository, and what was learned here before",
        "findings and risks",
        can_refuse=False,
        is_code=False,
        when="when there is something here to read",
    ),
    Station(
        "Architect",
        "decides what it is built with",
        "the task, and an empty folder",
        "a stack, a run command, a test command that fails on an empty suite",
        can_refuse=False,
        is_code=False,
        when="only when the repository is empty",
    ),
    Station(
        "Designer",
        "decides how it looks, for this business and not in general",
        "the task",
        "a palette, a type scale, a composition, a mark it draws itself",
        can_refuse=False,
        is_code=False,
        when="when somebody is going to look at the result",
    ),
    Station(
        "Planner",
        "turns all of that into items that can be done one at a time",
        "the survey, the shape and the direction",
        "an ordered plan, each item saying what it needs",
        can_refuse=False,
        is_code=False,
        when="on anything that is not a question or a one-line change",
    ),
    Station(
        "Engineer",
        "makes one change, and nothing outside it",
        "one item, the direction, and what the last attempt got wrong",
        "a change on disk and a report of what it did",
        can_refuse=False,
        is_code=False,
        when="once per item",
    ),
    Station(
        "Verifier",
        "builds it and runs the suite against the count from before",
        "the working tree",
        "a number, and whether it may stay",
        can_refuse=True,
        is_code=True,
        when="after every item",
    ),
    Station(
        "Inspector",
        "reads the diff for what a green suite cannot see",
        "the diff, and the files it added",
        "removed tests, silenced tests, lost assertions, secrets, "
        "dependencies committed, an image that is not what it claims",
        can_refuse=True,
        is_code=True,
        when="after every item",
    ),
    Station(
        "Reviewer",
        "asks whether the change did the item, and only the item",
        "the diff and the item it was given",
        "a verdict, and anything true but outside the item",
        can_refuse=True,
        is_code=False,
        when="after every item",
    ),
    Station(
        "Critic",
        "looks at the rendered page against the direction",
        "the page as an image, at phone and desktop width",
        "a verdict on what is actually on the screen",
        can_refuse=True,
        is_code=False,
        when="after an item that changed what somebody sees",
    ),
)


def as_rows() -> list[dict]:
    return [
        {
            "name": s.name,
            "does": s.does,
            "reads": s.reads,
            "says": s.says,
            "can_refuse": s.can_refuse,
            "is_code": s.is_code,
            "when": s.when,
        }
        for s in CREW
    ]


# A gate's name in the event, and the station that actually spoke. Only
# these three are verdicts. `on_gate` is also called for an engineer's
# question, a planner's answer, a restart and a split, and the handler used
# to map every unrecognised one onto the Reviewer - so the Reviewer was shown
# as having approved items it never saw.
GATE_STATION = {
    "inspector": "Inspector",
    "reviewer": "Reviewer",
    "critic": "Critic",
}

# A station is no longer working once it says what it decided.
TERMINAL = ("done", "failed", "skipped")

# The run itself finishing. A station still marked working after one of
# these did not finish - it was cut off, and saying "working" about it a
# day later is the one claim this must not make.
OVER = ("run.summary", "run.finished", "run.error")

# How many of a station's tool calls to keep. The whole list is in the log;
# this is what gets sent to a browser, and `tool_calls` carries the real
# count so a cap never reads as "that was all it did".
TOOLS_KEPT = 40


def what_each_did(events: list[dict]) -> list[dict]:
    """Read a run's events and say what each station actually did.

    Everything here is read off the log a run already writes. Nothing is
    inferred from what usually happens: a station that reported nothing is
    idle, a station cut off mid-sentence says so, and a field the log does
    not carry is absent rather than filled in with a plausible value.

    Tolerant on purpose, like `pace.read`. A log is written while a run
    happens and can stop anywhere, so every timing is optional.
    """
    seen = {
        s.name: {
            "name": s.name,
            "does": s.does,
            "is_code": s.is_code,
            "can_refuse": s.can_refuse,
            "when": s.when,
            "state": "idle",
            "note": "",
            "began": None,
            "ended": None,
            "seconds": None,
            "visits": [],
            "tools": [],
            "tool_calls": 0,
            "gates": [],
        }
        for s in CREW
    }
    # When the current spell of work started, per station, so a station
    # visited once per item adds its spells up rather than reporting the
    # span from its first to its last - which on the Engineer is most of
    # the run and is not time it spent working.
    since: dict[str, object] = {}
    over = False

    for event in events:
        kind = event.get("kind")
        at = str(event.get("at") or "")

        if kind in OVER:
            over = True
            continue

        if kind == "agent.state":
            who = seen.get(str(event.get("agent") or ""))
            if who is None:
                continue
            state = str(event.get("state") or "")
            note = str(event.get("note") or "")
            who["state"] = state
            who["note"] = note
            who["visits"].append({"state": state, "note": note, "at": at})
            if state == "working":
                who["began"] = who["began"] or at
                since[who["name"]] = clock(at)
            elif state in TERMINAL:
                who["ended"] = at
                spell = gap(since.pop(who["name"], None), clock(at))
                if spell:
                    who["seconds"] = round((who["seconds"] or 0) + spell)

        elif kind == "agent.tool":
            who = seen.get(str(event.get("agent") or ""))
            if who is None:
                continue
            who["tool_calls"] += 1
            who["tools"].append(
                {
                    "what": str(event.get("what") or ""),
                    "detail": str(event.get("detail") or ""),
                    "at": at,
                }
            )
            del who["tools"][:-TOOLS_KEPT]

        elif kind == "gate":
            who = seen.get(GATE_STATION.get(str(event.get("who") or ""), ""))
            if who is None:
                continue
            who["gates"].append(
                {
                    "item": event.get("id"),
                    "passed": bool(event.get("passed")),
                    "note": str(event.get("note") or ""),
                    "at": at,
                }
            )

    if over:
        for who in seen.values():
            if who["state"] == "working":
                # Not failed: nothing judged it. Not done either.
                who["state"] = "cut"
                who["note"] = who["note"] or "the run ended before this reported"
            elif who["state"] == "idle" and not who["visits"]:
                # On a run still going, idle means waiting for the station
                # before it. On a finished one it means this desk was never
                # needed, and the two must not read the same.
                who["state"] = "never"

    return list(seen.values())
