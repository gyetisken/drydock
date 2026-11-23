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


def verify_build(repo: Path, command: str) -> Verdict:
    """Run a separate build, or leave the test-only check to integration."""
    if not command:
        return Verdict(
            passed=True,
            reason="no separate build command",
            check=Check(name="build", command="", passed=True, seconds=0.0),
        )
    result = check("build", command, repo)
    # A build command is often the test command. `"build": "npm test"` is
    # what a greenfield worker writes when there is nothing to compile, and
    # then the counts are sitting in the output and nothing read them: one
    # run reported `tests_run: 0` and "compiles" for an item whose own
    # check detail said `# tests 22 / # pass 22 / # fail 0`. This does not
    # decide anything - a build still passes or fails on its exit status -
    # it only records what the output already said. A build with no test
    # report in it parses as nought, which is what it was before.
    run, failed, _ = read_test_counts(result.detail)
    return Verdict(
        passed=result.passed,
        reason=(
            (f"compiles, {run} tests pass" if run else "compiles")
            if result.passed
            else "does not compile"
        ),
        check=result,
        tests_run=run,
        tests_failed=failed,
    )


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

    # An item verified by the build still runs the suite when the project
    # has one. This escape is for the project that has no tests at all -
    # a greenfield repository before the item that creates them lands, or
    # a build-only project - where demanding a suite refuses an item for
    # something nobody did wrong.
    #
    # It was not asking that question. It asked whether the item said
    # "build", and an item on a greenfield job says "build" because the
    # baseline had no tests - so the whole of a site's own suite was
    # skipped the moment the engineer wrote one. Measured: a run recorded
    # `tests_run: 0` and "compiles" for a project whose `npm test` passes
    # fourteen tests, and the acceptance for an entire website was that
    # its static site generator exited 0.
    #
    # `has_tests` is the project declaring a test script; equal commands
    # mean the build is the suite, which the path below runs once.
    a_suite = bool(commands.get("has_tests")) and commands.get("tests") != commands.get(
        "build"
    )
    if (
        item_verify == "build"
        and not needs_suite
        and commands.get("build")
        and not a_suite
    ):
        return verify_build(repo, commands["build"])

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
