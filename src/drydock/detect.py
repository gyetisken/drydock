"""Work out how a repository is built and tested, without asking a model.

A pom.xml means Maven. That is not a judgement call, and sending it to a model
would add latency, cost and a chance of being wrong to a question that has one
answer.
"""

from dataclasses import dataclass
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


def detect(repo: Path) -> Toolchain:
    for marker, toolchain in TOOLCHAINS:
        if (repo / marker).exists():
            return toolchain
    raise SystemExit(f"{repo}: no build file recognised (pom.xml, pyproject.toml, ...)")


def count(repo: Path, glob: str) -> int:
    return sum(1 for _ in repo.glob(glob))
