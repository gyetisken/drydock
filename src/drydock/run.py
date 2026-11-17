"""The state of one job, kept on disk.

A run is slow and costs money, so losing it to a crash or a closed laptop is
not acceptable. Every stage writes itself out as it completes, which also means
the plan can be reviewed, edited by hand and resumed, rather than regenerated
from scratch because a later stage failed.
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Baseline, Inventory, ItemResult, Plan


class Run(BaseModel):
    id: str
    repo: str
    task: str
    started: str
    skills: list[str] = Field(default_factory=list)
    baseline: Baseline | None = None
    inventory: Inventory | None = None
    plan: Plan | None = None
    results: list[ItemResult] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0

    @classmethod
    def start(cls, repo: Path, task: str, skills: list[str] | None = None) -> "Run":
        now = datetime.now(UTC)
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

    def save(self) -> None:
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, run_id: str) -> "Run":
        return cls.model_validate_json((Path("runs") / f"{run_id}.json").read_text())

    @classmethod
    def latest(cls) -> "Run":
        runs = sorted(Path("runs").glob("*.json"))
        if not runs:
            raise SystemExit("no runs yet")
        return cls.model_validate_json(runs[-1].read_text())

    def spend(self, usage) -> None:
        self.tokens_in += usage.input_tokens
        self.tokens_out += usage.output_tokens

    @property
    def cost(self) -> float:
        """Claude Opus 5 list pricing, in dollars."""
        return self.tokens_in / 1e6 * 5 + self.tokens_out / 1e6 * 25


def event_printer(prefix: str = "  "):
    def printer(kind: str, text: str) -> None:
        first = text.strip().splitlines()[0] if text.strip() else ""
        print(f"{prefix}{kind:<9} {first[:120]}", flush=True)

    return printer
