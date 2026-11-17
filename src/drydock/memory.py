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
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

HOME = Path.home() / ".drydock" / "memory"


@dataclass
class Note:
    text: str
    commit: str
    learned: str


# Words that carry no meaning for matching one question against another.
NOISE = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "can",
        "could",
        "would",
        "should",
        "will",
        "what",
        "where",
        "which",
        "who",
        "why",
        "how",
        "when",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "about",
        "me",
        "my",
        "our",
        "your",
        "please",
        "tell",
        "show",
        "explain",
    ]
)


def _words(text: str) -> set[str]:
    """The words that carry the question, crudely singular.

    "stay" and "stays" are the same question, and a plural was enough to
    make two phrasings of one question look like two questions.
    """
    found = set()
    for raw in re.findall(r"[a-z0-9_]+", text.lower()):
        if raw in NOISE or len(raw) <= 2:
            continue
        # Crude suffix stripping, enough that "compare", "compares" and
        # "compared" are one word. Without it two phrasings of the same
        # question looked like two questions and were both paid for.
        word = raw
        for ending in ("ing", "ed", "es", "s"):
            if (
                word.endswith(ending)
                and len(word) - len(ending) >= 4
                and not word.endswith("ss")
            ):
                word = word[: -len(ending)]
                break
        found.add(word)
    return found


@dataclass
class Memory:
    repo: str
    toolchain: str = ""
    build_command: str = ""
    test_command: str = ""
    last_test_count: int = 0
    notes: list[Note] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    # How this project looks, decided once. Deciding it again on the second
    # job would cost five minutes and produce a different answer, which is
    # worse than the cost: a project whose palette changes between jobs does
    # not have a palette.
    direction: str = ""
    directed_on: str = ""
    # Questions already answered about this repository, and the answers. The
    # same question asked twice should not be read for twice.
    answers: list[dict] = field(default_factory=list)

    @property
    def path(self) -> Path:
        key = hashlib.sha256(self.repo.encode()).hexdigest()[:16]
        return HOME / f"{key}.json"

    @classmethod
    def about(cls, repo: Path) -> "Memory":
        """Everything known about this repository, or a blank sheet."""
        memory = cls(repo=str(repo))
        if not memory.path.exists():
            return memory
        try:
            raw = json.loads(memory.path.read_text())
        except (OSError, ValueError):
            # A memory that cannot be read is a memory this repository does
            # not have. It must not take the run down with it.
            return memory

        for name, default in cls._fields().items():
            if name == "repo" or name not in raw:
                continue
            setattr(memory, name, raw[name])
        memory.notes = [Note(**n) if isinstance(n, dict) else n for n in memory.notes]
        return memory

    @staticmethod
    def _fields() -> dict:
        """Every field, by name. Derived, so adding one cannot be forgotten.

        This was two hand-written lists - one that wrote and one that read -
        and the look and the answers were added to the class and to neither
        of them. They were kept in memory for the length of one run and
        silently thrown away, which looks exactly like a feature that does
        not work.
        """
        return {f.name: f.default for f in fields(Memory)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keep = {name: getattr(self, name) for name in self._fields()}
        keep["notes"] = [asdict(n) for n in self.notes]
        keep["jobs"] = self.jobs[-20:]
        keep["answers"] = self.answers[-20:]
        self.path.write_text(json.dumps(keep, indent=2))

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

    def direct(self, direction: str) -> None:
        """Keep the look, so the next job here builds the same thing."""
        if not direction.strip():
            return
        self.direction = direction
        self.directed_on = datetime.now(UTC).strftime("%Y-%m-%d")

    def answered(self, question: str, answer: str, commit: str) -> None:
        """Keep an answer, with the commit it was true at.

        Dropped when the commit moves, like any other reading of the code -
        an answer about a file that has since changed is not an answer, it
        is a memory of one.
        """
        self.answers = [a for a in self.answers if a["commit"] == commit][-20:]
        self.answers.append(
            {
                "question": question.strip()[:300],
                "answer": answer.strip()[:4000],
                "commit": commit,
                "at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
            }
        )

    def recall(self, question: str, commit: str) -> str:
        """An answer already given to this question, at this commit.

        Matched on the words that carry meaning rather than on the exact
        sentence, because nobody asks the same question the same way twice.
        """
        wanted = _words(question)
        if not wanted:
            return ""
        for earlier in reversed(self.answers):
            if earlier["commit"] != commit:
                continue
            had = _words(earlier["question"])
            if not had:
                continue
            shared = len(wanted & had) / len(wanted | had)
            if shared >= 0.6:
                return earlier["answer"]
        return ""

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
