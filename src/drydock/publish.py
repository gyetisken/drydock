"""Turning a finished run into something somebody can review.

Everything this program does already produces the shape of a good pull
request: one branch, one commit per item, a test count before and after, and
four recorded judgements on every change. None of it was reachable without a
terminal.

So this writes it out. The body is not a summary of the work - it is the
evidence that was gathered while the work was done, which is the thing a
reviewer actually wants and the thing nobody else publishes.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .repo import Repo


@dataclass
class Evidence:
    """What was recorded about one item while it was being checked."""

    item: int
    title: str
    plain: str
    commit: str
    note: str
    gates: dict = field(default_factory=dict)


def _gh() -> str:
    return shutil.which("gh") or ""


def signed_in() -> tuple[bool, str]:
    """Whether a GitHub login is available, and who it is."""
    binary = _gh()
    if not binary:
        return False, "the GitHub command line is not installed"
    try:
        out = subprocess.run(
            [binary, "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except OSError as exc:
        return False, str(exc)
    user = out.stdout.strip()
    if out.returncode or not user:
        return False, "gh is installed but not signed in; run `gh auth login`"
    return True, user


def has_remote(repo: Path) -> bool:
    return bool(Repo(repo)._git("remote")[1].strip())


def _unfinished(run) -> list[str]:
    """What was planned and is not here, said plainly.

    This matters more now that nothing is opened by a person who watched it
    happen. A draft that quietly omits the two items that were rolled back
    is a draft that misrepresents the branch.
    """
    landed = {r.item.id for r in run.results if r.outcome.value == "done"}
    judged = {r.item.id: r for r in run.results}
    said = []
    for item in run.plan.items if run.plan else []:
        if item.id in landed:
            continue
        result = judged.get(item.id)
        why = result.note if result else "never attempted"
        said.append(f"**{item.id}. {item.plain or item.title}** — {why}")
    return said


def body(run, evidence: list[Evidence], url: str = "") -> str:
    """The pull request body: what was checked, and what it said.

    Deliberately not a description of the change - the diff is the
    description. This is the part a reviewer cannot get from the diff: that
    the suite was this size before and is this size now, and that four
    separate checks looked at each commit and what each of them concluded.
    """
    base = run.baseline
    before = base.tests_run if base else 0
    after = max((e.gates.get("tests", 0) for e in evidence), default=before)

    lines = [
        f"{run.task.splitlines()[0]}",
        "",
        "## What landed",
        "",
    ]
    for e in evidence:
        lines.append(f"**{e.item}. {e.plain or e.title}**  ")
        lines.append(f"`{e.commit[:10]}` — {e.note}")
        lines.append("")

    missing = _unfinished(run)
    if missing:
        lines += ["## What did not", ""]
        lines += [f"- {m}" for m in missing]
        lines += [
            "",
            (
                "These are not in this branch. Nothing was kept that did not "
                "pass every check, so the work that is here stands on its own "
                "- but it is less than was planned."
            ),
            "",
        ]

    lines += [
        "## The suite",
        "",
        "| | |",
        "|---|---|",
        f"| Before any of this | {before} tests |",
        f"| Now | {after} tests |",
        "",
        (
            "Every item had to leave the suite at least as large as it found "
            "it. An item that did not was rolled back before the next one "
            "began, so nothing on this branch was kept by weakening what was "
            "being checked."
        ),
        "",
        "## What checked it",
        "",
        (
            "Each commit passed four gates, in this order. Any of them could "
            "send it back, and two of them are code rather than judgement."
        ),
        "",
    ]

    for e in evidence:
        said = e.gates
        lines.append(
            f"<details><summary><b>{e.item}. {e.plain or e.title}</b></summary>"
        )
        lines.append("")
        lines.append(f"- **Verifier** — {said.get('verifier', 'not recorded')}")
        lines.append(f"- **Inspector** — {said.get('inspector', 'nothing to report')}")
        if said.get("reviewer"):
            lines.append(f"- **Reviewer** — {said['reviewer']}")
        if said.get("critic"):
            lines.append(f"- **Critic** — {said['critic']}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if url:
        lines += [
            "## Running",
            "",
            f"It was served at `{url}` while it was looked at.",
            "",
        ]

    lines += [
        "---",
        "",
        (
            "Built by [drydock](https://github.com/gyetisken/drydock). One "
            "commit per item on its own branch; nothing touched the default "
            "branch."
        ),
    ]
    return "\n".join(lines)


def open_pull_request(
    repo: Path, run, evidence: list[Evidence], url: str = "", draft: bool = True
) -> tuple[bool, str]:
    """Push the branch and open a pull request. Returns (ok, url or reason)."""
    binary = _gh()
    if not binary:
        return False, "the GitHub command line is not installed"
    if not has_remote(repo):
        return False, "this repository has no remote to push to"

    git = Repo(repo)
    branch = git._git("rev-parse --abbrev-ref HEAD")[1].strip()
    if not branch or branch == "HEAD":
        return False, "not on a branch"

    code, out = git._git(f"push -u origin {branch}")
    if code:
        if _no_such_repository(out):
            return False, (
                "the remote points at a repository that does not exist yet. "
                "Create it on GitHub - private - and this will push into it:"
                f"\n{out[-400:]}"
            )
        return False, f"could not push the branch:\n{out[-600:]}"

    title = run.task.splitlines()[0][:72]
    with_body = body(run, evidence, url)

    command = [binary, "pr", "create", "--title", title, "--body", with_body]
    if draft:
        command.append("--draft")

    try:
        made = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, timeout=90, check=False
        )
    except OSError as exc:
        return False, str(exc)

    if made.returncode:
        return False, (made.stderr or made.stdout).strip()[-600:]
    return True, made.stdout.strip().splitlines()[-1]


def _no_such_repository(said: str) -> bool:
    """Whether a failed push means the repository is not there.

    Deliberately narrow, and it only changes what gets said. A push fails
    for a dozen reasons - no network, a rejected non-fast-forward, an
    expired token - and "go and make it" is the wrong advice for all of
    them except this one.
    """
    low = said.lower()
    return "repository not found" in low or "does not appear to be a git repo" in low


def evidence_from(run, gate_log: Path | None = None) -> list[Evidence]:
    """Gather what was recorded, from the run and from its event log."""
    said: dict[int, dict] = {}
    if gate_log and gate_log.exists():
        for line in gate_log.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind") == "gate":
                said.setdefault(event["id"], {})[event["who"]] = event.get("note", "")

    out = []
    for result in run.results:
        if result.outcome.value != "done":
            continue
        gates = dict(said.get(result.item.id, {}))
        gates["verifier"] = result.note
        tests = result.note.split(" tests")[0]
        if tests.isdigit():
            gates["tests"] = int(tests)
        out.append(
            Evidence(
                item=result.item.id,
                title=result.item.title,
                plain=getattr(result.item, "plain", ""),
                commit=result.commit or "",
                note=result.note,
                gates=gates,
            )
        )
    return out
