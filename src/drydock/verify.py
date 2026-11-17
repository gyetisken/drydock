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


def verify(repo: Path, item_verify: str, base: Baseline, commands: dict) -> Verdict:
    if item_verify == "build":
        result = check("build", commands["build"], repo)
        return Verdict(
            passed=result.passed,
            reason="compiles" if result.passed else "does not compile",
            check=result,
        )

    result = check("tests", commands["tests"], repo)
    run, failed, _ = read_test_counts(result.detail)

    if not result.passed:
        return Verdict(False, f"{failed} tests failing", result, run, failed)

    # The suite is green. Ask the question a green suite cannot answer.
    if base.tests_run and run == 0:
        return Verdict(
            False,
            f"the suite reported success but ran 0 tests, against a baseline of "
            f"{base.tests_run}. The runner is no longer finding them.",
            result,
            run,
            failed,
        )
    if base.tests_run and run < base.tests_run:
        return Verdict(
            False,
            f"{run} tests ran, down from {base.tests_run}. "
            f"{base.tests_run - run} stopped being discovered; none of them failed, "
            "which is worse than if they had.",
            result,
            run,
            failed,
        )

    gained = run - base.tests_run
    note = f"{run} tests pass"
    if gained > 0:
        note += f" ({gained} more than the baseline)"
    return Verdict(True, note, result, run, failed)
