"""Keeping the crew inside the repository it was pointed at.

The worker is Claude Code, which has a real filesystem and no reason of its
own to stay anywhere. Pointed at an empty repository it will do the sensible
thing for an assistant and the wrong thing for this program: look upwards. On
one run it walked out of an empty project folder and surveyed drydock's own
source, then planned against that - a job about somebody's restaurant website
turned into a job about this codebase.

That is not a prompt problem. A system that reads whatever it likes on
somebody's machine is wrong even when it behaves, and telling it nicely is not
a control. This is the control: a hook that Claude Code runs before every file
tool, which reads the path out of the call and refuses anything that is not
inside the repository.

Run as: python -m drydock.confine
Reads the tool call as JSON on stdin and the allowed root from DRYDOCK_ROOT.
Exit 0 lets the call through; exit 2 blocks it and hands the reason back to
the model, which is Claude Code's documented way for a hook to say no.
"""

import json
import os
import sys
from pathlib import Path

# The keys a path can arrive under, across the tools worth guarding.
PATH_KEYS = ("file_path", "path", "notebook_path", "target_file")


def offending(payload: dict, root: Path) -> str | None:
    """The path this call would touch outside the root, if there is one."""
    tool = payload.get("tool_name", "")
    args = payload.get("tool_input") or {}

    candidates = [args[k] for k in PATH_KEYS if isinstance(args.get(k), str)]
    # Grep and Glob take the directory to search as `path`, already covered,
    # but a pattern can also be an absolute path on its own.
    pattern = args.get("pattern")
    if isinstance(pattern, str) and pattern.startswith("/"):
        candidates.append(pattern)

    for raw in candidates:
        try:
            # resolve() follows symlinks, which is the point: a link inside the
            # repository pointing at /etc is still a way out of the repository.
            target = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            return f"{tool} was given a path that cannot be resolved: {raw}"
        if not target.is_relative_to(root):
            return (
                f"{tool} tried to reach {target}, which is outside this "
                f"project. The crew only works inside {root}."
            )
    return None


def main() -> int:
    root_env = os.environ.get("DRYDOCK_ROOT")
    if not root_env:
        # No root means no claim about what is allowed, and a guard that does
        # not know what it is guarding must not pretend to guard it.
        print(
            "DRYDOCK_ROOT is not set; refusing to allow file access.", file=sys.stderr
        )
        return 2
    root = Path(root_env).resolve()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print("the hook could not read the tool call", file=sys.stderr)
        return 2

    reason = offending(payload, root)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
