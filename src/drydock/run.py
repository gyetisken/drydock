"""The state of one job, kept on disk.

A run is slow and costs money, so losing it to a crash or a closed laptop is
not acceptable. Every stage writes itself out as it completes, which also means
the plan can be reviewed, edited by hand and resumed, rather than regenerated
from scratch because a later stage failed.
"""

from datetime import datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from .agent import PRICES
from .models import Baseline, Inventory, ItemResult, Plan


class Spent(BaseModel):
    """One model invocation, what it was, and what it cost.

    Appended by `Run.spend` and nowhere else, so a station cannot be
    counted twice: the same call that adds to the totals writes the line.
    Dollars are the reliable number on both engines; token counts are
    zero on the subscription engine, which reports a price and not a
    count (see `engineer._AsUsage`).
    """

    station: str
    item: int | None = None
    attempt: int = 0
    seconds: float = 0.0
    dollars: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class Run(BaseModel):
    id: str
    repo: str
    task: str
    started: str
    # What was asked for, what it actually ran as, and what raised it.
    #
    # Three fields rather than one, because the interesting case is when
    # they differ: a task that names a migration or money is raised to
    # `deep` however it was requested, and a record that keeps only the
    # effective profile cannot say whether somebody chose it or the floor
    # did. Measured before this existed: the CLI never passed a policy at
    # all, so `drydock run` executed `balanced` whatever the person had
    # set, and the record said nothing either way.
    profile_asked: str = ""
    profile_used: str = ""
    profile_floor: str = ""
    # Every model invocation, in order.
    timeline: list[Spent] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    engine: str = "claude"
    model: str = "opus"
    # The original request this work is answering, which is not always what
    # was typed this time. `task` is this instruction; a second job in the
    # same repository is usually a follow-up, and a run planned against
    # "could you please continue what you do ?" alone plans twelve items
    # against nothing. Carried on the record rather than looked up, so
    # planning, every retry and a resume days later all read the same one.
    objective: str = ""
    # How this is to look, decided once before planning. Kept here because
    # the engineer needs it on every item that renders anything, and until
    # now only the planner ever saw it - which is why the accent colour that
    # was specified appeared nowhere on the page.
    direction: str = ""
    # The request written out by the one that read the repository, and what
    # it settled that nobody said. Kept apart from the request rather than
    # merged into it, for two reasons that cost real runs: the request is
    # what the work is judged against and must stay readable as itself, and
    # a reading nobody asked for is enforced exactly as hard as a price
    # somebody named the moment the two become one piece of text.
    #
    # Apart from `direction` as well, which is about how a thing looks and
    # exists only for work somebody looks at. A payments endpoint has no
    # direction and still needs saying what it is for.
    expanded: str = ""
    assumptions: list[str] = Field(default_factory=list)
    # The loaded skill bodies for this run. Not written to disk - they come
    # from files - but carried so a worker in a worktree can be handed the
    # same briefing as one in the repository.
    skills_loaded: list = Field(default_factory=list, exclude=True)
    baseline: Baseline | None = None
    inventory: Inventory | None = None
    plan: Plan | None = None
    results: list[ItemResult] = Field(default_factory=list)
    integration_error: str = ""
    # What was said back, when the job was a question rather than a change.
    # Kept on the record because the history is read as a conversation now,
    # and a conversation that shows what was asked and not what was said is
    # half of one. It went to the feed and to memory and nowhere durable.
    answer: str = ""
    # Why each unfinished item was refused last time it was tried. Kept
    # because a resumed run used to throw this away: the results for items
    # that did not land are dropped so they can be attempted again, and the
    # engineer then started from nothing and made the identical mistake. The
    # same hours band was refused three times for the same missing times.
    refused: dict[int, str] = Field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    dollars: float = 0.0
    budget: float = 0.0
    # The commit on `branch` right after it was first checked out, before any
    # worker could write to it. Older records saved before this existed read
    # back as "", which `expected_tip` treats the same as having no anchor at
    # all - the commit of the last accepted item is used instead, when there
    # is one.
    anchor: str = ""

    @classmethod
    def start(cls, repo: Path, task: str, skills: list[str] | None = None) -> "Run":
        # Local, like everything else anybody reads. The offset is kept in
        # `started` so the record stays unambiguous.
        now = datetime.now().astimezone()
        return cls(
            id=now.strftime("%Y%m%d-%H%M%S"),
            repo=str(repo),
            task=task,
            started=now.isoformat(timespec="seconds"),
            skills=skills or [],
        )

    @property
    def brief(self) -> str:
        """What is being asked for, as every station should read it.

        The objective first, because that is what the finished thing is
        judged against, then this instruction - which adds to it or
        revises it, and does not replace it. When there is no objective,
        or it is the thing that was just typed, this is the task and
        nothing is said twice.
        """
        aim, now = self.objective.strip(), self.task.strip()
        if not aim or aim == now or aim in now:
            return self.task
        return (
            "The original request, which is what the finished work is "
            f"judged against:\n\n{aim}\n\nWhat is being asked for now. "
            "It adds to the request above, or revises it where the two "
            "disagree. It does not replace it, and nothing above stops "
            f"being true because of it:\n\n{now}"
        )

    @property
    def as_briefed(self) -> str:
        """The request, and then the request written out, in that order.

        What everything downstream reads. The order is the whole point:
        the request is first and is said to outrank what follows, because
        the expansion is one worker's reading of a sentence and the
        sentence is the thing somebody actually asked for. An engineer
        handed the two as one block has no way to tell which half it may
        depart from.

        When nothing was written out this is the request and nothing else,
        so a run that needed no expansion reads exactly as it did before.
        """
        asked = self.brief
        more = self.expanded.strip()
        if not more:
            return asked
        return (
            f"{asked}\n\n---\n\nWhat that was taken to mean, written out "
            "by whoever read the repository. It is context, not the "
            "standard: everything above was asked for and holds, and "
            "anything here that disagrees with it is wrong and loses. "
            "Where the request left something open, this is the sensible "
            f"reading of it and a good starting point:\n\n{more}"
        )

    @property
    def handoff(self) -> str:
        """What the start of this run already found out, said once.

        The reading, the toolchain and the commands were worked out by
        somebody with the repository open, written onto `inventory` -
        and read by nothing but the command line's own printout. So
        every engineer began by working out the language, the test
        command and the shape of the project again, once per item, and
        a five-item plan paid for that discovery five times.

        Short on purpose. This is a handoff, not a briefing: the facts
        that stop somebody re-deriving them, and nothing that would
        read as instructions. What the item is for still comes from the
        item.

        Said as of the start of the run, and said to be checkable. A
        fact about a tree is only a fact until something changes it,
        and the first item of a greenfield job changes most of them.
        """
        chain = self.inventory
        if chain is None:
            return ""
        lines = []
        if chain.build_tool:
            lines.append(f"- Built with: {chain.build_tool}")
        if chain.language and chain.language != "unknown":
            lines.append(f"- Language: {chain.language}")
        if chain.build_command:
            lines.append(f"- Run it with: `{chain.build_command}`")
        if chain.test_command:
            lines.append(f"- Test it with: `{chain.test_command}`")
        for said in chain.findings[:5]:
            lines.append(f"- Found: {said.strip()[:300]}")
        for said in chain.risks[:3]:
            lines.append(f"- Watch: {said.strip()[:300]}")
        if not lines:
            return ""
        return (
            "What was already worked out about this repository, when this "
            "run started. It is here so you do not spend your turns "
            "finding it again:\n\n"
            + "\n".join(lines)
            + "\n\nIt was read once, at the start. If what you see "
            "disagrees with it - a command that does not exist, a file "
            "that moved, a version that is not what it says - then what "
            "you see is right and this is stale. Check anything you are "
            "about to rely on and are not sure of; this replaces the "
            "routine look around, not your judgement." + self.established
        )

    # How much of the earlier items is carried, and how much of each.
    # Bounded because this is a handoff and not a history: an engineer
    # reading ten items of someone else's notes is an engineer with less
    # room for the item it was given.
    CARRIED_ITEMS: ClassVar[int] = 3
    CARRIED_LINES: ClassVar[int] = 3
    CARRIED_WIDTH: ClassVar[int] = 260

    @property
    def established(self) -> str:
        """What the items before this one measured, in this run.

        `handoff` says what the survey found before anything was touched.
        It stops there, which is why a later item re-derives what an
        earlier one has already measured. On run 20261124-142030 the
        second item spent 32 tool calls and a second attempt working out
        a query plan the first item's engineer had already read, and both
        it and the reviewer then reported that the item it was given
        rested on a premise that was not true.

        So the measurements come forward. This decides nothing and skips
        nothing: an item is still worked unless somebody says otherwise,
        and whether a finding makes the item pointless is a judgement the
        engineer makes with the evidence in front of it rather than one
        this property makes by arithmetic. Public tests passing is not
        evidence of anything here and is not consulted.

        Only items that landed. A reverted item's notes describe work
        that was thrown away.
        """
        landed = [r for r in self.results if getattr(r.outcome, "value", "") == "done"]
        if not landed:
            return ""
        blocks = []
        for result in landed[-self.CARRIED_ITEMS :]:
            said = [
                line.strip()[: self.CARRIED_WIDTH]
                for line in (result.noticed or [])[: self.CARRIED_LINES]
                if line and line.strip()
            ]
            if not said:
                continue
            blocks.append(
                f"- Item {result.item.id}, {result.item.title.strip()[:120]} "
                f"({result.note.strip()[:80] or 'landed'}):\n"
                + "\n".join(f"    - {line}" for line in said)
            )
        if not blocks:
            return ""
        return (
            "\n\nWhat the items before this one measured, while this run "
            "was going. Unlike the list above, this was read after the "
            "repository started changing, so it is the most recent thing "
            "anybody here actually ran:\n\n"
            + "\n".join(blocks)
            + "\n\nIt is here so you do not pay to find the same thing "
            "out again. If any of it makes your item unnecessary or rests "
            "on something that turns out not to be true, say so in your "
            "report and do not do the work twice - but it is evidence, "
            "not an instruction, and the item is still yours to do."
        )

    @property
    def path(self) -> Path:
        return Path("runs") / f"{self.id}.json"

    @property
    def branch(self) -> str:
        return f"drydock/{self.id}"

    @property
    def verification_baseline(self) -> Baseline:
        base = self.baseline or Baseline(builds=False)
        tests_run = max(
            [base.tests_run]
            + [
                r.tests_run
                for r in self.results
                if r.outcome.value == "done" and r.verified_commit
            ]
        )
        return base.model_copy(update={"tests_run": tests_run})

    @property
    def expected_tip(self) -> str:
        """Where `branch` must be for this run to be resumed safely.

        The last item that was actually verified on the branch, if there is
        one - its commit is the one real, checked state the branch has been
        in since. Before any item has landed, the only honest answer is the
        anchor taken right after the branch was first checked out. Empty
        means neither exists: an older record with nothing safe to compare
        against, which is refused rather than guessed at.
        """
        for r in reversed(self.results):
            if r.outcome.value == "done" and r.verified_commit:
                return r.verified_commit
        return self.anchor

    def what_happened(self) -> dict:
        """The record, said in the terms somebody reading it needs.

        Built from what was written down while the work happened and from
        nothing else. Where a thing was not recorded it says so: a check
        that did not run is not a check that passed, and a field nobody
        filled in is `None`, not a cheerful default.
        """
        landed, missed = [], []
        for result in self.results:
            item = result.item
            said = {
                "id": item.id,
                "plain": item.plain or item.title,
                "attempts": result.attempts,
            }
            if result.outcome.value == "done":
                commit = result.verified_commit or result.commit
                landed.append(
                    said
                    | {
                        "commit": (commit or "")[:10] or None,
                        "verified": bool(result.verified_commit),
                        "files": list(result.files_changed),
                        "checks": [
                            {
                                "name": check.name,
                                "command": check.command,
                                "passed": check.passed,
                            }
                            for check in result.checks
                        ],
                        "note": result.note,
                        # Kept, and said against it. An item that was
                        # allowed to stay with something true written
                        # against it is not the same as a clean one, and
                        # a summary that cannot tell them apart is the
                        # thing this whole record exists to avoid.
                        "outstanding": result.outstanding,
                        # Informational, and kept apart from the things
                        # that stopped anything. Three stations produce
                        # these and all three were being dropped.
                        "noticed": list(result.noticed),
                    }
                )
            else:
                missed.append(
                    said
                    | {
                        "outcome": result.outcome.value,
                        "note": result.note,
                        "noticed": list(result.noticed),
                    }
                )

        planned = {i.id for i in self.plan.items} if self.plan else set()
        judged = {r.item.id for r in self.results}
        for item in self.plan.items if self.plan else []:
            if item.id not in judged:
                missed.append(
                    {
                        "id": item.id,
                        "plain": item.plain or item.title,
                        "attempts": 0,
                        "outcome": "never attempted",
                        "note": "the run ended before this item was reached",
                    }
                )

        return {
            "branch": self.branch,
            "landed": landed,
            "missed": missed,
            "planned": len(planned),
            "integration_error": self.integration_error or None,
            # What this cost, and what that number is worth. On a plan that
            # bills nothing per run it is an observation, not a budget that
            # was enforced, and saying "$2.24 of work" without that is a
            # claim this program cannot stand behind.
            "cost": round(self.dollars, 2),
            "cost_is_enforced": bool(self.budget),
        }

    def save(self) -> None:
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, run_id: str) -> "Run":
        return cls.model_validate_json((Path("runs") / f"{run_id}.json").read_text())

    @classmethod
    def latest(cls) -> "Run":
        # By when it was written, not by its name. Names are local clock
        # times, and on the hour the clocks go back the newest run would
        # sort an hour early.
        runs = sorted(Path("runs").glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not runs:
            raise SystemExit("no runs yet")
        return cls.model_validate_json(runs[-1].read_text())

    def spend(
        self,
        usage,
        station: str = "",
        item: int | None = None,
        attempt: int = 0,
        seconds: float = 0.0,
    ) -> None:
        """Count one invocation, and write down what it was.

        `usage` is either a usage object or a bare number of dollars: the
        critic returns the second kind and used to add straight to
        `self.dollars`, which kept it out of the totals it belongs in and
        out of any record of what the run did.

        Naming the station is optional so an unlabelled caller still
        counts correctly, and the line is written here rather than at the
        call sites so a station cannot be added to the totals once and to
        the timeline twice.
        """
        # A station that reported nothing is not an error. Counting is the
        # least important thing happening here and must never be the thing
        # that stops a run.
        if usage is None:
            return
        if isinstance(usage, (int, float)):
            usage = Spent(station=station or "unnamed", dollars=float(usage))
        went_in = int(getattr(usage, "input_tokens", 0) or 0)
        came_out = int(getattr(usage, "output_tokens", 0) or 0)
        cost = float(getattr(usage, "dollars", 0.0) or 0.0)
        self.tokens_in += went_in
        self.tokens_out += came_out
        self.tokens_cached += int(getattr(usage, "cached_tokens", 0) or 0)
        self.dollars += cost
        if station:
            self.timeline.append(
                Spent(
                    station=station,
                    item=item,
                    attempt=attempt,
                    seconds=round(seconds, 2),
                    dollars=round(cost, 4),
                    tokens_in=went_in,
                    tokens_out=came_out,
                )
            )

    # Which stations happen before a line of the thing anybody asked for
    # exists, and which happen because it does. Named rather than
    # inferred: on run 20261124-153354 the preparation was 323 of 497
    # seconds and $1.53 of $2.22, and nothing in the record said so -
    # the figure had to be added up by hand from the station lines.
    BEFORE_ANY_CODE: ClassVar[tuple[str, ...]] = (
        "analyst",
        "architect",
        "designer",
        "planner",
        "start",
    )

    def phases(self) -> dict[str, dict]:
        """What was spent getting ready, and what was spent working.

        `planner-answer` and `planner-split` are work, not preparation:
        they happen because an item is being worked on and would not
        happen without one.
        """
        out = {
            "preparation": {"calls": 0, "seconds": 0.0, "dollars": 0.0},
            "execution": {"calls": 0, "seconds": 0.0, "dollars": 0.0},
        }
        for line in self.timeline:
            which = (
                "preparation" if line.station in self.BEFORE_ANY_CODE else "execution"
            )
            out[which]["calls"] += 1
            out[which]["seconds"] += line.seconds
            out[which]["dollars"] += line.dollars
        for held in out.values():
            held["seconds"] = round(held["seconds"], 1)
            held["dollars"] = round(held["dollars"], 4)
        return out

    def by_station(self) -> dict[str, dict]:
        """What each station cost and how long it took, in call order."""
        totals: dict[str, dict] = {}
        for line in self.timeline:
            held = totals.setdefault(
                line.station, {"calls": 0, "seconds": 0.0, "dollars": 0.0}
            )
            held["calls"] += 1
            held["seconds"] += line.seconds
            held["dollars"] += line.dollars
        for held in totals.values():
            held["seconds"] = round(held["seconds"], 1)
            held["dollars"] = round(held["dollars"], 4)
        return totals

    @property
    def left(self) -> float:
        """What is still allowed to be spent. Infinite when no budget was set."""
        return float("inf") if not self.budget else max(0.0, self.budget - self.dollars)

    @property
    def cost(self) -> float:
        """What this run has actually cost, priced per model as it went."""
        return self.dollars

    @property
    def as_opus(self) -> float:
        """What the same tokens would have cost on the most expensive model.

        This is only knowable for runs that went through the API, where the
        token counts come back with every reply. It is the comparison worth
        making: the work was split between a model that thinks and a model
        that looks things up, and this is the bill for not having split it.
        Runs on the subscription engine report a price and no tokens, so they
        are left out rather than guessed at.
        """
        if not self.tokens_in and not self.tokens_out:
            return 0.0
        rate_in, rate_out = PRICES["claude-opus-5"]
        billed_in = self.tokens_in + self.tokens_cached
        return round(billed_in / 1e6 * rate_in + self.tokens_out / 1e6 * rate_out, 4)


def event_printer(prefix: str = "  "):
    def printer(kind: str, text: str) -> None:
        first = text.strip().splitlines()[0] if text.strip() else ""
        print(f"{prefix}{kind:<9} {first[:120]}", flush=True)

    return printer
