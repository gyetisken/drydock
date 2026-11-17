"""The Analyst: measure first, then look.

Two halves, and the split is the point. Detecting the build tool and running
the suite needs no model, so no model is used; those facts are gathered by
running commands and reading their output. Only the task-specific question —
what in this repository bears on what we are about to do — goes to a model, and
it gets read-only tools to answer it with evidence rather than recall.
"""

from pathlib import Path

from .agent import JUDGEMENT, Agent, Tool
from .detect import Toolchain, count, detect
from .engines import ClaudeCodeEngine
from .models import Baseline, Inventory
from .parse import read_test_counts
from .shell import check
from .skills import Skill, briefing
from .tools import read_only

SYSTEM = """You are surveying a codebase before any change is made to it.

You have read-only tools. Use them. Every statement you make has to come from
something you read, not from what a project of this kind usually looks like.

You are looking for two things.

Findings: facts about this repository that bear on the task. Counts, versions,
the shape of what exists. "47 test files import org.junit.Assert" is a finding.
"The project uses JUnit" is not; it is a guess that happens to be right.

Risks: places this task is likely to break something, and why. Be concrete and
be specific to what you read. If a pattern appears in only one file but that
file is unusual, say so."""

PROMPT = """Repository: {repo}
Build: {build_tool}, {language}
Baseline: {baseline}

The task is:

{task}

Survey the repository and report."""


def baseline(repo: Path, chain: Toolchain) -> Baseline:
    """Run the build and the suite untouched. Nothing is a regression without this.

    An empty repository has nothing to run, and that is a legitimate baseline
    rather than a failure: zero tests pass, and the first thing the crew builds
    is the thing that will say whether anything still does.
    """
    if not chain.build_command:
        return Baseline(builds=True, tests_run=0, tests_failed=0, tests_skipped=0)

    build = check("build", chain.build_command, repo)
    tests = check("tests", chain.test_command, repo)
    run, failed, skipped = read_test_counts(tests.detail)
    return Baseline(
        builds=build.passed,
        tests_run=run,
        tests_failed=failed,
        tests_skipped=skipped,
        checks=[build, tests],
    )


def _report_tool() -> Tool:
    return Tool(
        name="report",
        description="Report what the survey found. Call this once, at the end.",
        schema={
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Facts read from the repository, with numbers where there are numbers.",
                },
                "risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Where this task is likely to break something, and why.",
                },
            },
            "required": ["findings", "risks"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def survey(
    repo: Path,
    task: str,
    base: Baseline,
    skills: list[Skill] | None = None,
    on_event=None,
    model: str | None = None,
    max_turns: int = 20,
    budget: float = 0.0,
    engine: str = "api",
) -> tuple[Inventory, object]:
    chain = detect(repo)

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine().structured(
            repo,
            SYSTEM + briefing(skills or [], "survey"),
            PROMPT.format(
                repo=repo.name,
                build_tool=chain.build_tool,
                language=chain.language,
                baseline=f"{base.tests_run} tests, {base.tests_failed} failing"
                if base.tests_run
                else "nothing to run yet",
                task=task,
            ),
            '{"findings": ["..."], "risks": ["..."]}',
            on_event=on_event,
        )
        return _inventory(chain, repo, found), _Spend(dollars, turns)

    agent = Agent(
        name="Analyst",
        system=SYSTEM + briefing(skills or [], "survey"),
        tools=read_only(repo),
        # The survey is mostly reading, and the judgement it does make is
        # checked by a person before anything is changed, so it runs on the
        # expensive model only when asked to.
        model=model or JUDGEMENT,
        max_turns=max_turns,
        budget=budget,
        on_event=on_event,
    )
    found = agent.run(
        PROMPT.format(
            repo=repo.name,
            build_tool=chain.build_tool,
            language=chain.language,
            baseline=f"{base.tests_run} tests, {base.tests_failed} failing"
            if base.tests_run
            else "no tests found",
            task=task,
        ),
        final_tool=_report_tool(),
    )
    return _inventory(chain, repo, found), agent.usage


class _Spend:
    """What a Claude Code call cost, shaped like the API engine's accounting."""

    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars


def _inventory(chain: Toolchain, repo: Path, found: dict) -> Inventory:
    return Inventory(
        build_tool=chain.build_tool,
        language=chain.language,
        build_command=chain.build_command,
        test_command=chain.test_command,
        source_files=count(repo, chain.source_glob),
        test_files=count(repo, chain.test_glob),
        findings=found.get("findings", []),
        risks=found.get("risks", []),
    )
