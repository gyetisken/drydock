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
from pathlib import Path

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

# An assertion that names the value it expects. Removing one of these and
# putting back something from WEAK is the quietest way to make a failing
# test pass: the test is still there, still runs, still counted, and no
# longer says anything about what the code produces.
EXACTING = re.compile(
    r"""
      assertEquals | assertArrayEquals | assertSame
    | \.toBe\s*\( | \.toEqual\s*\( | \.toStrictEqual\s*\(
    | \.toHaveBeenCalledWith\s*\( | \.toMatchObject\s*\(
    | isEqualTo\s*\( | containsExactly\s*\(
    | assert_eq! | assert_ne!
    | Assert\.AreEqual | Assert\.AreSame
    | assert\s+[^\n]*\s(?:==|!=)\s
    | assertRaises | pytest\.raises | assertThrows
    """,
    re.VERBOSE | re.IGNORECASE,
)

# An assertion that is true of almost any value. Each of these is a real
# assertion in its own right - there is nothing wrong with checking that
# something is not null - which is why this is only reported when exacting
# ones disappeared in the same change.
WEAK = re.compile(
    r"""
      assertNotNull | assertTrue\s*\(\s*true\s*\) | assertTrue\s*\(\s*\w+\s*\)
    | \.toBeDefined\s*\( | \.toBeTruthy\s*\( | \.toBeFalsy\s*\(
    | \.not\.toBeNull\s*\( | \.toBeInstanceOf\s*\(
    | isNotNull\s*\( | isNotEmpty\s*\(
    | assert\s+[^\n]*\bis\s+not\s+None\s*$
    | assert\s+[^\n=<>!]+$              # bare truthiness, no comparison in it
    | assert\s+True\s*$
    | assert!\s*\(\s*true\s*\)
    | assert!\s*\([^\n]*\.is_(?:some|ok|empty)\(\)
    | \.isPresent\(\) | \.isNotBlank\(\)
    | Assert\.IsNotNull | Assert\.IsTrue\s*\(\s*true\s*\)
    """,
    re.VERBOSE,
)

# Things that must never be committed, whatever the item was about.
# Credentials that are recognisable on sight. Each of these is a prefix a
# provider chose precisely so that a leaked key can be spotted, which is the
# whole reason this can be a regular expression rather than a judgement.
#
# A committed key cannot be taken back by deleting it: the history has it,
# and anything that mirrored the repository has it too. So this is matched in
# the diff, before the commit, rather than looked for afterwards.
SECRET = re.compile(
    r"""
      \bsk-[A-Za-z0-9_-]{20}          # Anthropic, OpenAI, and others alike
                                      # The boundary matters: without it
                                      # `task-list-container-wrapper` is a
                                      # credential, and a refusal nobody can
                                      # act on is worse than no check.
    | \bAKIA[0-9A-Z]{16}\b
    | -----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+|PGP\s+)?PRIVATE\s+KEY-----
    | gh[pousr]_[A-Za-z0-9]{20}       # GitHub, all five token kinds
    | github_pat_[A-Za-z0-9_]{20}     # and the fine-grained ones
    | xox[baprse]-[A-Za-z0-9-]{10}
    | \bAIza[0-9A-Za-z_-]{30}         # Google
    | \b[rs]k_live_[A-Za-z0-9]{20}    # Stripe
    | glpat-[A-Za-z0-9_-]{15}         # GitLab
    | dop_v1_[a-f0-9]{30}             # DigitalOcean
    | SG\.[A-Za-z0-9_-]{20}           # SendGrid
    | npm_[A-Za-z0-9]{30}
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


# What each image format actually starts with. A file claiming to be one
# thing and containing another is never right, and it is the shape a faked
# asset takes: asked for a photograph it cannot produce, a worker writes a
# handful of bytes and names the file .jpg.
MAGIC = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".avif": (b"\x00\x00\x00",),
    ".bmp": (b"BM",),
    ".ico": (b"\x00\x00\x01\x00",),
}

# Below this, an image is not a photograph of anything.
TOO_SMALL = 2048


def check_assets(repo: Path, added: list[str]) -> list[Finding]:
    """Look at image files the diff added, on disk rather than in the diff.

    A binary file is not readable in a patch, so this is the one check that
    has to open the file. It exists because an item asked for a photograph,
    nothing in this system can take one, and what arrived was a hand-written
    bitmap of flat colour blocks named .jpg.
    """
    findings = []
    for path in added:
        suffix = Path(path).suffix.lower()
        if suffix not in MAGIC:
            continue
        here = repo / path
        if not here.exists():
            continue

        head = here.read_bytes()[:16]
        if not any(head.startswith(sig) for sig in MAGIC[suffix]):
            actual = next(
                (
                    ext
                    for ext, sigs in MAGIC.items()
                    if any(head.startswith(sig) for sig in sigs)
                ),
                "something else",
            )
            findings.append(
                Finding(
                    "not what it says",
                    f"{path} is named {suffix} and is {actual}. A file that "
                    "lies about what it is was not made, it was improvised.",
                )
            )
            continue

        size = here.stat().st_size
        if size < TOO_SMALL:
            findings.append(
                Finding(
                    "not a real image",
                    f"{path} is {size} bytes. Nothing that small is a "
                    "photograph or an illustration of anything; if a real "
                    "image cannot be produced, the item has to say so rather "
                    "than ship a placeholder pretending to be the thing.",
                )
            )
    return findings


def look(
    diff: str, *, allow_removals: bool = False, repo: Path | None = None
) -> Report:
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

    # An assertion swapped for a weaker one in the same place. The counts
    # do not move, the suite stays the same size, every test still runs -
    # and the test no longer says anything about what the code produces.
    # This is the quietest way there is to make a failing test pass.
    gave_up = sum(1 for ln in removed if EXACTING.search(ln)) - sum(
        1 for ln in added if EXACTING.search(ln)
    )
    settled_for = sum(1 for ln in added if WEAK.search(ln)) - sum(
        1 for ln in removed if WEAK.search(ln)
    )
    if gave_up >= 1 and settled_for >= 1:
        findings.append(
            Finding(
                "assertions weakened",
                f"{gave_up} assertion(s) that named the value they expected were "
                f"removed, and {settled_for} that hold for almost any value were "
                "put in their place. The tests still run and still pass; they no "
                "longer say what the code should produce.",
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

    if repo is not None:
        findings += check_assets(repo, _added_files(diff))

    return Report(clean=not findings, findings=findings)
