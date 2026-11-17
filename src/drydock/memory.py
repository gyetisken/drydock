"""What the crew remembers about a project between jobs.

Without this every run starts from nothing: the same repository gets read from
scratch, the same build tool gets discovered again, the same awkward corner
gets found for the first time. That is the single largest avoidable cost here,
and it is avoidable because almost none of it changes between Tuesday and
Wednesday.

What is remembered is deliberately narrow. Facts that were read from the
repository and the shape of what happened to it, with the commit they were
true at. Nothing is carried forward as true once the commit it came from is
no longer current: a stale fact stated confidently is worse than no fact.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

HOME = Path.home() / ".drydock" / "memory"


@dataclass
class Note:
    text: str
    commit: str
    learned: str


@dataclass
class Memory:
    repo: str
    toolchain: str = ""
    build_command: str = ""
    test_command: str = ""
    last_test_count: int = 0
    notes: list[Note] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)

    @property
    def path(self) -> Path:
        key = hashlib.sha256(self.repo.encode()).hexdigest()[:16]
        return HOME / f"{key}.json"

    @classmethod
    def about(cls, repo: Path) -> "Memory":
        memory = cls(repo=str(repo))
        if memory.path.exists():
            raw = json.loads(memory.path.read_text())
            memory.toolchain = raw.get("toolchain", "")
            memory.build_command = raw.get("build_command", "")
            memory.test_command = raw.get("test_command", "")
            memory.last_test_count = raw.get("last_test_count", 0)
            memory.notes = [Note(**n) for n in raw.get("notes", [])]
            memory.jobs = raw.get("jobs", [])
        return memory

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "repo": self.repo,
                    "toolchain": self.toolchain,
                    "build_command": self.build_command,
                    "test_command": self.test_command,
                    "last_test_count": self.last_test_count,
                    "notes": [asdict(n) for n in self.notes],
                    "jobs": self.jobs[-20:],
                },
                indent=2,
            )
        )

    def learn(self, facts: list[str], commit: str, keep: int = 40) -> None:
        """Add what was read this time, and drop what has gone stale.

        A note is kept only while the commit it was learned at is still the one
        in front of us. The moment the repository moves on, a fact about it is
        a claim about the past.
        """
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        known = {n.text for n in self.notes}
        for fact in facts:
            if fact not in known:
                self.notes.append(Note(text=fact, commit=commit, learned=now))
        self.notes = [n for n in self.notes if n.commit == commit][-keep:]

    def record(self, task: str, done: int, total: int, dollars: float) -> None:
        self.jobs.append(
            {
                "task": task,
                "done": done,
                "total": total,
                "dollars": round(dollars, 4),
                "at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
            }
        )

    def briefing(self, commit: str) -> str:
        """What to hand the next survey so it does not start from nothing."""
        fresh = [n for n in self.notes if n.commit == commit]
        # The commands are worth passing on even with nothing else: they are
        # the part a survey would otherwise spend turns working out, and they
        # do not go stale the way a reading of the code does.
        if not fresh and not self.jobs and not self.toolchain:
            return ""

        parts = []
        if self.toolchain:
            parts.append(
                f"This repository has been worked on before. It is {self.toolchain}; "
                f"the build is `{self.build_command}` and the suite is "
                f"`{self.test_command}`, which last ran {self.last_test_count} tests."
            )
        if fresh:
            parts.append(
                "These were read from the repository at the commit you are looking "
                "at now, so they still hold. Do not spend turns rediscovering them; "
                "spend them on what is specific to this job.\n\n"
                + "\n".join(f"- {n.text}" for n in fresh[-25:])
            )
        if self.jobs:
            recent = self.jobs[-3:]
            parts.append(
                "Recent jobs here:\n"
                + "\n".join(
                    f"- {j['task'][:90]} ({j['done']}/{j['total']} items landed)"
                    for j in recent
                )
            )
        return "\n\nWhat is already known:\n\n" + "\n\n".join(parts)
