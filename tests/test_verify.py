"""The verification is the part that must not be wrong, so it is tested hardest."""

from pathlib import Path
from typing import ClassVar

from drydock.models import Baseline, Check
from drydock.parse import read_test_counts
from drydock.verify import verify


def fake_check(passed: bool, detail: str) -> Check:
    return Check(name="tests", command="x", passed=passed, seconds=1.0, detail=detail)


class TestCounts:
    def test_reads_the_maven_total_not_the_per_class_lines(self):
        """Surefire prints a line per class and then a total. Summing them all
        double counts, and the number this returns decides whether work is kept."""
        output = (
            "Tests run: 53, Failures: 0, Errors: 0, Skipped: 0\n"
            "Tests run: 9, Failures: 0, Errors: 0, Skipped: 0\n"
            "Tests run: 838, Failures: 0, Errors: 0, Skipped: 6\n"
        )
        assert read_test_counts(output) == (838, 0, 6)

    def read_test_counts_errors_as_failures(self):
        assert (
            read_test_counts("Tests run: 10, Failures: 1, Errors: 2, Skipped: 0")[1]
            == 3
        )

    def test_reads_pytest(self):
        assert read_test_counts("18 passed in 0.05s") == (18, 0, 0)

    def test_unreadable_output_is_zero_rather_than_a_guess(self):
        assert read_test_counts("something went wrong") == (0, 0, 0)


class TestVerdict:
    BASE = Baseline(builds=True, tests_run=838, tests_failed=0, tests_skipped=6)
    COMMANDS: ClassVar[dict] = {"build": "true", "tests": "true"}

    def test_a_green_suite_at_the_same_count_passes(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.verify.check",
            lambda *a, **k: fake_check(
                True, "Tests run: 838, Failures: 0, Errors: 0, Skipped: 6"
            ),
        )
        assert verify(Path("."), "tests", self.BASE, self.COMMANDS).passed

    def test_zero_tests_on_a_green_build_is_a_failure(self, monkeypatch):
        """The whole reason this module exists. An unconfigured runner exits 0
        having run nothing, and every later item would be measured against it."""
        monkeypatch.setattr(
            "drydock.verify.check", lambda *a, **k: fake_check(True, "BUILD SUCCESS")
        )
        verdict = verify(Path("."), "tests", self.BASE, self.COMMANDS)
        assert not verdict.passed
        assert "0 tests" in verdict.reason

    def test_a_drop_in_count_is_a_failure_even_when_green(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.verify.check",
            lambda *a, **k: fake_check(
                True, "Tests run: 812, Failures: 0, Errors: 0, Skipped: 6"
            ),
        )
        verdict = verify(Path("."), "tests", self.BASE, self.COMMANDS)
        assert not verdict.passed
        assert "26 stopped being discovered" in verdict.reason

    def test_more_tests_than_the_baseline_is_fine(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.verify.check",
            lambda *a, **k: fake_check(
                True, "Tests run: 850, Failures: 0, Errors: 0, Skipped: 6"
            ),
        )
        verdict = verify(Path("."), "tests", self.BASE, self.COMMANDS)
        assert verdict.passed
        assert "12 more" in verdict.reason

    def test_failing_tests_fail(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.verify.check",
            lambda *a, **k: fake_check(
                False, "Tests run: 838, Failures: 3, Errors: 0, Skipped: 6"
            ),
        )
        assert not verify(Path("."), "tests", self.BASE, self.COMMANDS).passed


class TestItAlsoHasToBuild:
    """An item verified by its tests must still leave something that builds.

    Without this a broken build is invisible until some later item happens to
    be verified by one, and by then it is six commits back and belongs to
    nobody. That is exactly what happened: a test file written into a routes
    directory, found at item seven of seven.
    """

    BASE = Baseline(builds=True, tests_run=24, tests_failed=0, tests_skipped=0)
    COMMANDS: ClassVar[dict] = {"build": "false", "tests": "true"}

    def test_green_tests_do_not_excuse_a_broken_build(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.verify.check",
            lambda name, *_: fake_check(name != "build", "Tests run: 24"),
        )
        verdict = verify(Path("."), "tests", self.BASE, self.COMMANDS)
        assert not verdict.passed
        assert "no longer builds" in verdict.reason

    def test_a_project_with_no_separate_build_is_not_asked_for_one(self, monkeypatch):
        """Where the build command and the test command are the same thing,
        running it twice proves nothing and costs a minute."""
        calls = []

        def spy(name, command, *_):
            calls.append(name)
            return fake_check(True, "Tests run: 24, Failures: 0, Errors: 0, Skipped: 0")

        monkeypatch.setattr("drydock.verify.check", spy)
        verdict = verify(
            Path("."), "tests", self.BASE, {"build": "npm test", "tests": "npm test"}
        )
        assert verdict.passed
        assert calls == ["tests"]
