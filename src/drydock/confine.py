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
import re
import shlex
import sys
from pathlib import Path

from .route import LOOK, WEB, is_route, is_url

# The keys a path can arrive under, across the tools worth guarding.
PATH_KEYS = ("file_path", "path", "notebook_path", "target_file")

# What a worker may run. Read-only inspection, the version probes that
# decide a toolchain, and the runtimes themselves - a plan for an empty
# folder is partly a question about what is installed on this machine.
#
# `echo` is here because the phases are announced by running one. The
# runtimes are here because `node --version` is how a planner learns the
# thing it would otherwise guess, and because a build command is one of
# these and the engineer has to be able to run it.
ALLOWED = frozenset(
    {
        # Saying something out loud.
        "echo",
        "true",
        "false",
        # Looking.
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "file",
        "stat",
        "find",
        "du",
        "grep",
        "rg",
        "sed",
        "awk",
        "sort",
        "uniq",
        "cut",
        "tr",
        "diff",
        "basename",
        "dirname",
        "realpath",
        "pwd",
        "which",
        "env",
        "date",
        # The repository's own history.
        "git",
        # Toolchains: version probes, installs, builds, tests.
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "bun",
        "deno",
        "node",
        "python",
        "python3",
        "pip",
        "pip3",
        "uv",
        "uvx",
        "pytest",
        "ruff",
        "go",
        "cargo",
        "rustc",
        "mvn",
        "gradle",
        "dotnet",
        "make",
        "ruby",
        "bundle",
        "rake",
        "php",
        "composer",
        "swift",
        "java",
        # This program's own tools, when a worker is allowed them.
        LOOK,
        WEB,
    }
)

# Ways a command can mean something other than what it reads as. None of
# these can be checked by reading the words: `$(cat /etc/passwd)` has no
# path in it until the shell has already run something, and `> ../x`
# writes somewhere this never looked. Refused outright rather than
# parsed, because a guard that reasons about them is a guard nobody can
# check by reading it.
TRICKS = (
    ("$(", "a command substitution"),
    ("`", "a command substitution"),
    ("${", "a shell expansion"),
    ("<(", "a process substitution"),
    (">(", "a process substitution"),
    (">", "a redirection"),
    ("<", "a redirection"),
    ("\n", "a newline"),
    ("\r", "a newline"),
)

# `2>&1` and `2>/dev/null` (and the `1>` forms of the same). Neither can
# put a byte anywhere a person could read it afterwards, and both are in
# every second shell command somebody writes.
_HARMLESS_STDERR = re.compile(r"\s*\d?>\s*(?:&\s*\d|/dev/null\b)")

# Chaining is allowed and each link is checked on its own. `npm run build
# && npm test` is one honest thing somebody does, and refusing it buys
# nothing: both halves still have to be commands this crew may run, with
# paths that stay inside the project.
LINKS = ("&&", "||", ";", "|")

# A switch rather than a thing to open. Everything that is not one is
# treated as a possible path, because the alternative is deciding what
# looks like one - and `ls door`, where `door` is a link out of the
# project, looks like a word. A bare word that is not a path resolves to
# somewhere inside the project and passes; nothing is lost by asking.
_A_SWITCH = re.compile(r"^-")


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


def _one_command(said: str, root: Path) -> str | None:
    """Why this single command may not run here, if it may not."""
    try:
        words = shlex.split(said)
    except ValueError:
        return "this shell command could not be read as one command"
    if not words:
        return None

    name = Path(words[0]).name
    if name not in ALLOWED:
        return (
            f"`{name}` is not a command this crew may run. It may read the "
            "project, read its git history, and run its toolchain."
        )

    # One command takes a page of the project's own site rather than a
    # file, and a route reads exactly like an absolute path: `/rooms`
    # resolved to the directory `/rooms` at the root of the disk and was
    # refused for being outside the project. Narrow on purpose - this one
    # command name, and only for arguments the look tool itself would
    # accept as a route, by the same validator it uses. Everything else
    # that is not a switch is still a path, still resolved, and still has
    # to land inside the project.
    looking = name == LOOK
    # The fetching tool takes https addresses, which resolve as relative
    # paths and would be refused as being outside the project. Only this
    # one command name, only arguments that validate as an address, and
    # only by the same rule the tool itself applies. Its destination
    # argument is a path and is still resolved below, which is what keeps
    # a download inside the project.
    fetching = name == WEB
    for word in words[1:]:
        if _A_SWITCH.match(word) or not word:
            continue
        if looking and is_route(word):
            continue
        if fetching and is_url(word):
            continue
        try:
            target = Path(word).expanduser()
            target = target if target.is_absolute() else root / target
            target = target.resolve()
        except (OSError, RuntimeError):
            return f"{name} was given a path that cannot be resolved: {word}"
        if not target.is_relative_to(root):
            return (
                f"{name} was pointed at {target}, which is outside this "
                f"project. The crew only works inside {root}."
            )
    return None


def _shell_offence(command: str, root: Path) -> str | None:
    """Why this shell command may not run here, if it may not.

    Three questions, in the order they can be answered cheaply.

    Does it mean what it reads as? Anything that can become a different
    command before it runs - a substitution, an expansion, a redirection
    - is refused without being parsed.

    Is every command in it one we allow? A list of names rather than a
    list of patterns, so what is permitted can be read in one sitting.
    Chains are split and each link asked separately, because `npm run
    build && npm test` is one honest thing and refusing it buys nothing.

    And does every path stay inside the project? Resolved, not matched.
    `..` is the obvious way out and the boring ones are an absolute path,
    a symlink and a home directory; `resolve()` answers all four, because
    it answers where the path actually lands rather than how it is spelt.
    """
    said = (command or "").strip()
    if not said:
        return None
    # The root as the filesystem sees it. `/tmp` is a link to
    # `/private/tmp` on a Mac, so an unresolved root compared against a
    # resolved target says every path is outside - which fails closed and
    # would still have been a day of wondering why nothing could read
    # anything.
    root = root.resolve()

    # Sending stderr somewhere harmless is not a redirection anybody
    # needs stopping, and refusing it cost a measured round trip: a
    # planner probing `node --version 2>&1; npm --version 2>&1` was
    # refused and ran the same probe again without it, two seconds
    # later. Both of these write nowhere - one to the same stream, one
    # to the null device - so they are taken out before the check and
    # the rest of the line is judged as it would have been.
    said = _HARMLESS_STDERR.sub(" ", said)

    for mark, what in TRICKS:
        if mark in said:
            return (
                f"this shell command contains {what} (`{mark}`), which this "
                "crew may not run. Run plain commands."
            )

    rest = said
    for link in LINKS:
        rest = rest.replace(link, "\x00")
    # What is left of `&` once the chains are out is a command sent to the
    # background, which finishes after anybody is still watching for it.
    if "&" in rest:
        return (
            "this shell command puts something in the background (`&`), "
            "which this crew may not do."
        )

    for part in rest.split("\x00"):
        reason = _one_command(part, root)
        if reason:
            return reason
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

    if payload.get("tool_name") == "Bash":
        reason = _shell_offence(
            (payload.get("tool_input") or {}).get("command", ""), root
        )
    else:
        reason = offending(payload, root)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
