"""Everything the application knows about, across projects and runs.

The first version of this held one session in a module-level variable, which
was honest about what it was: a way to watch a single job. A tool people use
has several projects, a history of what was done to each, and jobs that
outlive the tab they were started from, so the state moved here.

Nothing about a project is stored except where it is. The repository is the
record; duplicating any of it here would create a second truth that drifts.
"""

import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .detect import detect
from .repo import Repo
from .run import Run
from .session import Session
from .shell import run
from .skills import Skill

HOME = Path.home() / ".drydock"


def _recency(stamp: str) -> float:
    """A sortable number from a timestamp, and zero when there is not one."""
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M").timestamp()
    except (ValueError, TypeError):
        return 0.0


@dataclass
class Project:
    path: Path
    added: str
    last_used: str = ""
    # A name somebody chose, and whether it sits at the top of the list.
    # Neither changes anything on disk: a folder called `api-v2-final` can be
    # called the thing it actually is without renaming it under whatever else
    # is pointing at that path.
    label: str = ""
    pinned: bool = False
    # A standing instruction for this repository: the thing somebody would
    # otherwise retype at the end of every command. It is kept here rather
    # than in the repository because it is how *this person* wants the crew
    # to behave, which is not a fact about the code and does not belong in
    # somebody else's checkout.
    instructions: str = ""

    @property
    def name(self) -> str:
        return self.label or self.path.name

    @property
    def exists(self) -> bool:
        return (self.path / ".git").is_dir()

    def toolchain(self) -> str:
        try:
            chain = detect(self.path)
            return f"{chain.build_tool} / {chain.language}"
        except SystemExit:
            return "unrecognised"


@dataclass
class Workspace:
    projects: list[Project] = field(default_factory=list)
    sessions: dict[str, Session] = field(default_factory=dict)

    @property
    def _file(self) -> Path:
        return HOME / "projects.json"

    def load(self) -> "Workspace":
        """Read the list back, including everything somebody chose about it.

        Both halves of this used to be hand-written lists of three fields.
        A project could be renamed, pinned, and given a standing
        instruction, and all three were kept for exactly as long as the
        application stayed open - which looks precisely like a feature that
        does not work.
        """
        if not self._file.exists():
            return self
        try:
            raw = json.loads(self._file.read_text())
        except (OSError, ValueError):
            return self

        keep = {f.name for f in fields(Project)} - {"path"}
        found = []
        for said in raw:
            if not isinstance(said, dict) or not said.get("path"):
                continue
            project = Project(Path(said["path"]), said.get("added", ""))
            for name in keep:
                if name in said:
                    setattr(project, name, said[name])
            found.append(project)
        self.projects = found
        return self

    def save(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps(
                [
                    {
                        name: str(value) if name == "path" else value
                        for name, value in (
                            (f.name, getattr(p, f.name)) for f in fields(Project)
                        )
                    }
                    for p in self.projects
                ],
                indent=2,
            )
        )

    def add_project(self, path: Path) -> Project:
        """Take a folder and make it usable, rather than refusing it.

        The crew needs git, because an item that fails is undone by throwing
        away its commit. Telling someone to go and run `git init` themselves is
        asking them to do a thing this can simply do, and the people most
        likely to be stopped by that message are the ones this should work for.
        """
        path = path.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)

        if not (path / ".git").is_dir():
            code, out = run("git init -q", path, timeout=60)
            if code != 0:
                raise ValueError(f"could not start a repository in {path}: {out}")
        # Asked separately from whether `.git` exists, because the two are
        # not the same question. Somebody who runs `git init` and stops has
        # a repository with no commit in it, and the version of this that
        # only looked for `.git` skipped the first commit entirely - every
        # run on that folder then died on `rev-parse --verify HEAD`.
        Repo(path).start_history()
        for existing in self.projects:
            if existing.path == path:
                return existing
        project = Project(path, datetime.now().strftime("%Y-%m-%d"))
        self.projects.insert(0, project)
        self.save()
        return project

    def rename(self, path: str, label: str) -> None:
        for project in self.projects:
            if str(project.path) == path:
                project.label = label.strip()[:60]
        self.save()
        self._order()

    def instruct(self, path: str, text: str) -> None:
        for project in self.projects:
            if str(project.path) == path:
                project.instructions = text.strip()[:4000]
        self.save()

    def pin(self, path: str, pinned: bool) -> None:
        for project in self.projects:
            if str(project.path) == path:
                project.pinned = pinned
        self.save()
        self._order()

    def _order(self) -> None:
        """Pinned first, then whatever was used most recently."""
        self.projects = sorted(
            self.projects, key=lambda p: (not p.pinned, -_recency(p.last_used))
        )
        self.save()

    def forget(self, path: str) -> None:
        self.projects = [p for p in self.projects if str(p.path) != path]
        self.save()

    def touch(self, path: Path) -> None:
        for project in self.projects:
            if project.path == path:
                project.last_used = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.save()

    def busy_with(self, repo: Path) -> str:
        """The key of a crew already working in this repository, if there is
        one.

        One repository, one crew. Two of them work the same item, commit
        into the same tree, and the first to finish cleans up the other's
        worker - which is the worst thing this program can do to somebody's
        code. It was one click away, and the only clue in the record was
        two heartbeats in the same second reporting different amounts of
        elapsed time.
        """
        for key, session in self.sessions.items():
            if session.running and session.repo == repo:
                return key
        return ""

    def start(
        self,
        repo: Path,
        task: str,
        skills: list[Skill],
        budget: float,
        engine: str = "claude",
        model: str = "opus",
        stop_after: str = "planner",
        standing: str = "",
        profile: str = "",
    ) -> Session:
        # What was asked for, or what this person has set, or the default.
        from .policy import of
        from .settings import Settings

        session = Session(
            repo,
            task,
            skills,
            budget=budget,
            engine=engine,
            model=model,
            stop_after=stop_after,
            standing=standing,
            policy=of(profile or Settings.load().profile),
        )
        session.start(auto_run=False)
        # The session has an id only once its run exists, so it is keyed by the
        # same clock the run uses and reconciled when the run appears.
        key = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.sessions[key] = session
        self.touch(repo)
        return session

    def session_for(self, key: str) -> Session | None:
        return self.sessions.get(key)

    def history(self, limit: int = 25) -> list[Run]:
        runs = []
        for path in sorted(Path("runs").glob("*.json"), reverse=True)[:limit]:
            try:
                runs.append(Run.model_validate_json(path.read_text()))
            except Exception as exc:  # noqa: BLE001
                # A run saved by an older version must not take the list down
                # with it; the history is a convenience, not a source of truth.
                print(f"skipping {path.name}: {exc}")
                continue
        return runs
