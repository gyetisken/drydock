"""Work out how a repository is built and tested, without asking a model.

A pom.xml means Maven. That is not a judgement call, and sending it to a model
would add latency, cost and a chance of being wrong to a question that has one
answer.
"""

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
    )


def is_empty(chain: Toolchain) -> bool:
    return chain is NOTHING


def count(repo: Path, glob: str) -> int:
    return sum(1 for _ in repo.glob(glob))
