"""Deciding whether an item worked.

A green suite is not sufficient. A test runner that has been misconfigured
reports success and runs nothing, and the build that discovers 0 tests exits 0
exactly like the build that passes 838. So the count is compared as well, and a
drop is treated as a failure even when every test that ran passed.

This is the one check that cannot be delegated to a model. It is arithmetic.
"""

from dataclasses import dataclass
from pathlib import Path

from .models import Baseline, Check
from .parse import read_test_counts
from .shell import check


@dataclass
class Verdict:
    passed: bool
    reason: str
    check: Check
    tests_run: int = 0
    tests_failed: int = 0
    build_check: Check | None = None

    @property
    def checks(self) -> list[Check]:
        return [self.build_check, self.check] if self.build_check else [self.check]


def verify(repo: Path, item_verify: str, base: Baseline, commands: dict) -> Verdict:
    needs_suite = base.has_tests or base.tests_run > 0
    if not commands.get("tests") or (
        needs_suite and not commands.get("has_tests", True)
    ):
        # Nothing to run yet. On a greenfield job this is true until the item
        # that creates the project lands, and calling that a pass would be
        # agreeing that an empty repository is working software.
        return Verdict(
            passed=False,
            reason=(
                "the existing test suite no longer has a test command"
                if needs_suite
                else "there is still no way to run anything in this repository"
            ),
            check=Check(name="tests", command="", passed=False, seconds=0.0),
        )

    if item_verify == "build" and not needs_suite:
        result = check("build", commands["build"], repo)
        return Verdict(
            passed=result.passed,
            reason="compiles" if result.passed else "does not compile",
            check=result,
        )

    # An item verified by its tests must still leave something that builds.
    # Without this, a change that breaks the build is invisible until some
    # later item happens to be verified by one - and then it is six commits
    # back and belongs to nobody. It cost exactly that here: a test file put
    # inside a routes directory, found at item seven.
    build = commands.get("build", "")
    compiled = None
    if build and build != commands["tests"]:
        compiled = check("build", build, repo)
        if not compiled.passed:
            return Verdict(
                False,
                "the tests may pass but it no longer builds",
                compiled,
            )

    result = check("tests", commands["tests"], repo)
    run, failed, _ = read_test_counts(result.detail)

    if not result.passed or failed:
        result.passed = False
        reason = f"{failed} tests failing" if failed else "the test command failed"
        return Verdict(False, reason, result, run, failed, compiled)

    # The suite is green. Ask the question a green suite cannot answer.
    if needs_suite and run == 0:
        result.passed = False
        return Verdict(
            False,
            f"the suite reported success but ran 0 tests, against a baseline of "
            f"{base.tests_run}. The runner is no longer finding them.",
            result,
            run,
            failed,
            compiled,
        )
    if base.tests_run and run < base.tests_run:
        result.passed = False
        return Verdict(
            False,
            f"{run} tests ran, down from {base.tests_run}. "
            f"{base.tests_run - run} stopped being discovered; none of them failed, "
            "which is worse than if they had.",
            result,
            run,
            failed,
            compiled,
        )

    gained = run - base.tests_run
    note = f"{run} tests pass"
    if gained > 0:
        note += f" ({gained} more than the baseline)"
    return Verdict(True, note, result, run, failed, compiled)
