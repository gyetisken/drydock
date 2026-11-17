"""Reading a test runner's totals.

The count is the whole of the guarantee: a change is allowed to stay only if
the suite still runs at least as many tests as it did before. A runner whose
output cannot be read reports zero, every comparison against zero passes, and
the promise stops being kept without anything appearing to go wrong. Each
sample below is output a real runner produced.
"""

from drydock.parse import read_test_counts

MAVEN = """
[INFO] Tests run: 12, Failures: 0, Errors: 0, Skipped: 1
[INFO] Tests run: 826, Failures: 0, Errors: 0, Skipped: 5
[INFO] BUILD SUCCESS
"""

NODE = """
ℹ tests 14
ℹ suites 3
ℹ pass 13
ℹ fail 1
ℹ cancelled 0
ℹ skipped 0
# tests 14
# suites 3
# pass 13
# fail 1
# cancelled 0
# skipped 0
"""

VITEST = """
 Test Files  3 passed (3)
      Tests  17 passed (17)
   Start at  04:12:33
"""

VITEST_FAILING = """
 Test Files  1 failed | 2 passed (3)
      Tests  2 failed | 15 passed (17)
"""

JEST = """
Test Suites: 1 failed, 4 passed, 5 total
Tests:       3 failed, 1 skipped, 40 passed, 44 total
"""

PYTEST = "=========== 54 passed, 2 skipped in 0.74s ============"

GO = """
--- PASS: TestParse (0.00s)
--- FAIL: TestBroken (0.01s)
--- PASS: TestOther (0.00s)
--- SKIP: TestSlow (0.00s)
FAIL
"""

DOTNET = "Failed!  - Failed:     2, Passed:    38, Skipped:     1, Total:    41"


class TestEachRunner:
    def test_maven_takes_the_grand_total_not_the_sum(self):
        assert read_test_counts(MAVEN) == (826, 0, 5)

    def test_node_test(self):
        assert read_test_counts(NODE) == (14, 1, 0)

    def test_vitest_all_passing(self):
        assert read_test_counts(VITEST) == (17, 0, 0)

    def test_vitest_with_failures(self):
        assert read_test_counts(VITEST_FAILING) == (17, 2, 0)

    def test_jest(self):
        assert read_test_counts(JEST) == (44, 3, 1)

    def test_pytest(self):
        assert read_test_counts(PYTEST) == (54, 0, 2)

    def test_go_counts_its_per_test_lines(self):
        assert read_test_counts(GO) == (4, 1, 1)

    def test_dotnet(self):
        assert read_test_counts(DOTNET) == (41, 2, 1)


class TestWhenItCannotRead:
    def test_unreadable_output_is_zero_rather_than_a_guess(self):
        assert read_test_counts("Everything went fine, probably.") == (0, 0, 0)

    def test_empty_output(self):
        assert read_test_counts("") == (0, 0, 0)

    def test_a_node_run_does_not_get_read_as_pytest(self):
        """node:test prints the word "pass" too, and the pytest shape would
        otherwise half-match it and report the wrong number."""
        assert read_test_counts(NODE)[0] == 14
