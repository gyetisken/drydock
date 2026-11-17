"""Everything the application knows about, across projects and runs.

The first version of this held one session in a module-level variable, which
was honest about what it was: a way to watch a single job. A tool people use
has several projects, a history of what was done to each, and jobs that
outlive the tab they were started from, so the state moved here.

Nothing about a project is stored except where it is. The repository is the
record; duplicating any of it here would create a second truth that drifts.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .detect import detect
from .run import Run
from .session import Session
from .skills import Skill

HOME = Path.home() / ".drydock"


@dataclass
class Project:
    path: Path
    added: str
    last_used: str = ""

    @property
    def name(self) -> str:
        return self.path.name

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
        if self._file.exists():
            raw = json.loads(self._file.read_text())
            self.projects = [
                Project(Path(p["path"]), p.get("added", ""), p.get("last_used", ""))
                for p in raw
            ]
        return self

    def save(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps(
                [
                    {"path": str(p.path), "added": p.added, "last_used": p.last_used}
                    for p in self.projects
                ],
                indent=2,
            )
        )

    def add_project(self, path: Path) -> Project:
        path = path.expanduser().resolve()
        if not (path / ".git").is_dir():
            raise ValueError(
                f"{path} is not a git repository. The crew needs git to commit "
                "each item separately and to undo one that fails."
            )
        for existing in self.projects:
            if existing.path == path:
                return existing
        project = Project(path, datetime.now(UTC).strftime("%Y-%m-%d"))
        self.projects.insert(0, project)
        self.save()
        return project

    def forget(self, path: str) -> None:
        self.projects = [p for p in self.projects if str(p.path) != path]
        self.save()

    def touch(self, path: Path) -> None:
        for project in self.projects:
            if project.path == path:
                project.last_used = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        self.save()

    def start(
        self, repo: Path, task: str, skills: list[Skill], budget: float
    ) -> Session:
        session = Session(repo, task, skills, budget=budget)
        session.start(auto_run=False)
        # The session has an id only once its run exists, so it is keyed by the
        # same clock the run uses and reconciled when the run appears.
        key = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
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
            except Exception:  # noqa: BLE001 - an old run must not break the list
                continue
        return runs
