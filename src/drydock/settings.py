"""The few choices that are not per-project.

Kept small on purpose. A setting is a decision somebody has to make and then
remember, so each one here has to earn it - and the one that does is the
only thing this program does that leaves the machine.
"""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("DRYDOCK_HOME") or (Path.home() / ".drydock"))


@dataclass
class Settings:
    # Open a draft pull request when a run finishes.
    #
    # On by default because a run that ends on a local branch nobody can see
    # is a run that ends in the terminal, which is the thing this exists to
    # avoid. A draft, because a draft is a place to look rather than a
    # request for somebody's time - and it is opened only when at least one
    # item actually landed, on the run's own branch, never on the default
    # one. Turn it off and everything else is unchanged; the branch is there
    # either way.
    publish_when_done: bool = True

    @classmethod
    def load(cls) -> "Settings":
        path = _home() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = _home() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
