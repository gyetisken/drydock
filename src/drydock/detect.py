"""Work out how a repository is built and tested, without asking a model.

A pom.xml means Maven. That is not a judgement call, and sending it to a model
would add latency, cost and a chance of being wrong to a question that has one
answer.
"""

import contextlib
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Toolchain:
    language: str
    build_tool: str
    build_command: str
    test_command: str
    source_glob: str
    test_glob: str
    has_tests: bool = True


TOOLCHAINS = [
    (
        "pom.xml",
        Toolchain(
            language="Java",
            build_tool="Maven",
            build_command="mvn -B -q compile",
            test_command="mvn -B test",
            source_glob="src/main/**/*.java",
            test_glob="src/test/**/*.java",
        ),
    ),
    (
        "build.gradle",
        Toolchain(
            language="Java",
            build_tool="Gradle",
            build_command="./gradlew compileJava",
            test_command="./gradlew test",
            source_glob="src/main/**/*.java",
            test_glob="src/test/**/*.java",
        ),
    ),
    (
        "pyproject.toml",
        Toolchain(
            language="Python",
            build_tool="uv",
            build_command="uv sync --frozen",
            test_command="uv run pytest -q",
            source_glob="src/**/*.py",
            test_glob="tests/**/*.py",
        ),
    ),
    (
        "package.json",
        Toolchain(
            language="TypeScript",
            build_tool="npm",
            build_command="npm run build",
            test_command="npm test",
            source_glob="src/**/*.ts",
            test_glob="**/*.test.ts",
        ),
    ),
]


# A repository with nothing in it is not an error. It is where a greenfield
# job starts, and the first item of that plan is the one that creates the build
# file this would otherwise be looking for.
NOTHING = Toolchain(
    language="unknown",
    build_tool="none yet",
    build_command="",
    test_command="",
    source_glob="**/*",
    test_glob="**/*test*",
    has_tests=False,
)


def detect(repo: Path) -> Toolchain:
    """Work out how this repository is built, as it stands right now.

    Called again after every item rather than once at the start, because a
    greenfield job changes the answer: there is no build file until the first
    item writes one, and from then on there is.
    """
    for marker, toolchain in TOOLCHAINS:
        if (repo / marker).exists():
            return _refine(repo, toolchain)
    return NOTHING


def _refine(repo: Path, chain: Toolchain) -> Toolchain:
    """Replace assumptions about a project with what it actually declares.

    A package.json means npm; it does not mean `npm run build` exists. Plenty
    of Node projects have no build step at all, and running a script that is
    not there fails - so an item verified by the build was rolled back for
    not compiling, when nothing had failed to compile and there was nothing
    to compile. A check that cannot pass is not a check.
    """
    if chain.build_tool != "npm":
        return chain

    import json

    try:
        scripts = json.loads((repo / "package.json").read_text()).get("scripts") or {}
    except (OSError, ValueError):
        return chain

    build = next(
        (f"npm run {name}" for name in ("build", "compile") if name in scripts), ""
    )
    test = "npm test" if "test" in scripts else ""
    return replace(
        chain,
        # With no build step, "does it still build" is answered by the thing
        # that does run. With neither, there is nothing to answer it with,
        # and verify already refuses to pass an item it cannot check.
        build_command=build or test,
        test_command=test or build,
        has_tests=bool(test),
    )


# Words that mean somebody is going to look at this. Matched on word
# boundaries, because "ui" sits inside "suite" and a JUnit migration was
# being sent to a designer.
FACES = re.compile(
    r"\b(web ?site|site|web ?page|page|landing|web ?app|app|ui|ux|"
    r"frontend|front-end|dashboard|portal|blog|shop|storefront|"
    r"interface|home ?page|marketing)\b"
)

# Where a project that serves pages keeps them.
A_FACE_ON_DISK = ("public", "static", "views", "templates", "src/pages")


def has_a_face(repo: Path, task: str) -> bool:
    """Whether this job produces something a person looks at.

    A parser, a migration or a CLI does not need a palette, and asking
    for one costs a minute and produces an answer nobody reads.

    Here rather than on the session, because the command line asks the
    same question and a second copy of this would be a second answer.
    """
    if FACES.search((task or "").lower()):
        return True
    # An existing repository that already serves pages has a face whether
    # or not the request mentions one.
    return any((repo / name).exists() for name in A_FACE_ON_DISK)


def is_empty(chain: Toolchain) -> bool:
    return chain is NOTHING


def count(repo: Path, glob: str) -> int:
    return sum(1 for _ in repo.glob(glob))


# What a planner would otherwise find out by running three commands and
# waiting for each. Measured on one run: `node --version 2>&1; npm
# --version 2>&1`, then the same probe again without the redirection
# because the fence refused the first, then `python3 --version` - three
# round trips and about twenty seconds to learn two version numbers that
# this process can read in under a tenth of a second.
#
# Only what decides something. A planner choosing a stack for an empty
# folder needs to know what is installed; one reading a repository that
# already declares its toolchain does not, and is not told.
RUNTIMES = (
    ("node", "node --version"),
    ("npm", "npm --version"),
    ("python3", "python3 --version"),
    ("uv", "uv --version"),
    ("go", "go version"),
    ("cargo", "cargo --version"),
    ("java", "java -version"),
)


def installed(timeout: int = 4) -> str:
    """The runtimes on this machine and their versions, as a short list.

    Never raises and never waits long. A probe that hangs is worse than
    a planner finding out for itself, so each one is given seconds and
    anything that does not answer is simply not mentioned.
    """
    from .shell import run

    here = Path.cwd()
    found = []
    for name, command in RUNTIMES:
        if not shutil.which(name):
            continue
        # A probe that fails is a probe that tells us nothing, which is
        # exactly where this started. It is never a reason to stop.
        code, out = -1, ""
        with contextlib.suppress(Exception):
            code, out = run(command, here, timeout=timeout)
        said = (out or "").strip().splitlines()
        if code == 0 and said:
            found.append(f"{name} {said[0].strip()}")
    if not found:
        return ""
    return (
        "What is installed on this machine, read before you were started "
        "so you do not spend turns asking: "
        + ", ".join(found)
        + ". Anything not listed is not installed. If you need to know "
        "something else about the environment, go and find out."
    )
