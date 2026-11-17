"""Reading the diff for the things a green suite cannot see.

The verification answers one question - did the suite stay at least as healthy
as it was - and it answers it by arithmetic. There is a second question it
cannot answer at all: *how* the suite was kept green. A change that deletes the
assertion that was failing, or marks the test as skipped, or quietly removes a
test file, leaves a green run and a smaller amount of truth.

This is deterministic on purpose. Asking a model whether a diff is honest means
asking the thing that wrote the diff, and the answer costs money and arrives
with a confidence that is not earned. Counting removed test declarations is
arithmetic, like the test count, and arithmetic does not negotiate.
"""

import re
from dataclasses import dataclass, field

# A test, in every language anyone here is likely to be holding. These are
# matched on removed lines only, so a false positive costs one re-run and a
# miss costs a silently smaller suite.
TEST_DECLARATION = re.compile(
    r"""
      @Test\b                      # Java, Kotlin
    | \bdef\s+test\w*\s*\(         # Python
    | \bfunc\s+Test[A-Z]\w*\s*\(   # Go
    | \b(?:it|test)\s*[(.]         # JavaScript, TypeScript, Ruby
    | \b\#\[test\]                 # Rust
    | \[Test(?:Method)?\]          # C#
    """,
    re.VERBOSE,
)

# Ways of keeping a test in the file while taking it out of the run.
SILENCER = re.compile(
    r"""
      @Disabled\b | @Ignore\b | @Skip\b
    | \.skip\s*\( | \.todo\s*\(
    | \bxit\s*\( | \bxdescribe\s*\(
    | pytest\.mark\.skip | unittest\.skip
    | t\.Skip\s*\(
    | \[Ignore\]
    """,
    re.VERBOSE,
)

ASSERTION = re.compile(r"\bassert|\bexpect\s*\(|\bshould\b", re.IGNORECASE)

# Things that must never be committed, whatever the item was about.
SECRET = re.compile(
    r"""
      sk-ant-[A-Za-z0-9_-]{10}
    | \bAKIA[0-9A-Z]{16}\b
    | -----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----
    | ghp_[A-Za-z0-9]{20}
    | xox[baprs]-[A-Za-z0-9-]{10}
    """,
    re.VERBOSE,
)

# Directories that are build output or downloaded dependencies. Committing
# them is not a style disagreement: it puts tens of thousands of files nobody
# wrote into the history, where they cannot be reviewed and cannot be removed
# without rewriting it. A greenfield item that installs dependencies will do
# this by accident on the very first commit unless something stops it.
NOT_OURS = re.compile(
    r"""(^|/)(
          node_modules | bower_components | vendor
        | target | build | dist | out
        | \.venv | venv | __pycache__ | \.mypy_cache | \.pytest_cache
        | \.gradle | \.next | \.nuxt | \.parcel-cache
        | coverage | \.tox | \.eggs
    )/""",
    re.VERBOSE,
)

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.[\w-]+)?|id_rsa|id_ed25519|credentials\.json|"
    r"serviceAccount\w*\.json|[\w-]+\.pem|[\w-]+\.p12)$"
)


@dataclass
class Finding:
    kind: str
    detail: str


@dataclass
class Report:
    clean: bool
    findings: list[Finding] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(f.detail for f in self.findings)


def _added_files(diff: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE)


def look(diff: str, *, allow_removals: bool = False) -> Report:
    """Read a unified diff and report what should stop it from standing.

    `allow_removals` is for the rare item whose whole point is to delete
    tests - a duplicate suite being dropped, a module being removed. It has to
    be asked for by the item, so that losing tests is always a decision
    somebody wrote down rather than something that happened.
    """
    findings: list[Finding] = []
    removed = [
        ln[1:] for ln in diff.splitlines() if ln.startswith("-") and ln[1:3] != "--"
    ]
    added = [
        ln[1:] for ln in diff.splitlines() if ln.startswith("+") and ln[1:3] != "++"
    ]

    gone = sum(1 for ln in removed if TEST_DECLARATION.search(ln))
    back = sum(1 for ln in added if TEST_DECLARATION.search(ln))
    if gone > back and not allow_removals:
        findings.append(
            Finding(
                "tests removed",
                f"{gone - back} test declarations were removed and not put back. "
                "A suite made smaller is a suite made quieter, and the run cannot "
                "tell the difference.",
            )
        )

    silenced = [ln.strip() for ln in added if SILENCER.search(ln)]
    if silenced:
        findings.append(
            Finding(
                "tests silenced",
                f"{len(silenced)} test(s) were switched off rather than fixed: "
                + "; ".join(s[:70] for s in silenced[:3]),
            )
        )

    lost = sum(1 for ln in removed if ASSERTION.search(ln))
    kept = sum(1 for ln in added if ASSERTION.search(ln))
    if lost - kept >= 3:
        findings.append(
            Finding(
                "assertions removed",
                f"{lost - kept} more assertions were removed than added. The code "
                "may now be checked less than it was before this item.",
            )
        )

    junk = set()
    for path in _added_files(diff):
        if SECRET_FILE.search(path):
            findings.append(Finding("secret file", f"{path} must not be committed"))
        hit = NOT_OURS.search(path)
        if hit:
            junk.add(hit.group(2))
    if junk:
        findings.append(
            Finding(
                "not ours to commit",
                f"files under {', '.join(sorted(junk))} are in the diff. That is "
                "build output or downloaded dependencies, and once it is in the "
                "history it cannot be reviewed and cannot be taken out without "
                "rewriting it. Add it to .gitignore instead.",
            )
        )

    for ln in added:
        if SECRET.search(ln):
            findings.append(
                Finding(
                    "secret", "a credential appears in the diff and was not committed"
                )
            )
            break

    return Report(clean=not findings, findings=findings)
