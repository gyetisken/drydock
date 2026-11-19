"""The state of one job, kept on disk.

A run is slow and costs money, so losing it to a crash or a closed laptop is
not acceptable. Every stage writes itself out as it completes, which also means
the plan can be reviewed, edited by hand and resumed, rather than regenerated
from scratch because a later stage failed.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .agent import PRICES
from .models import Baseline, Inventory, ItemResult, Plan


class Run(BaseModel):
    id: str
    repo: str
    task: str
    started: str
    skills: list[str] = Field(default_factory=list)
    engine: str = "api"
    model: str = "opus"
    # How this is to look, decided once before planning. Kept here because
    # the engineer needs it on every item that renders anything, and until
    # now only the planner ever saw it - which is why the accent colour that
    # was specified appeared nowhere on the page.
    direction: str = ""
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
                    }
                )
            else:
                missed.append(
                    said | {"outcome": result.outcome.value, "note": result.note}
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

    def spend(self, usage) -> None:
        # A station that reported nothing is not an error. Counting is the
        # least important thing happening here and must never be the thing
        # that stops a run.
        if usage is None:
            return
        self.tokens_in += usage.input_tokens
        self.tokens_out += usage.output_tokens
        self.tokens_cached += getattr(usage, "cached_tokens", 0)
        self.dollars += getattr(usage, "dollars", 0.0)

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
