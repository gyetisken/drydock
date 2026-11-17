"""Pull numbers out of build output.

Every test runner announces its totals in a line with a recognisable shape.
Reading that line is better than asking a model to summarise the log: it is
free, instant, and it cannot round 838 down to "most of them".

The count is the whole of the guarantee this program makes. A runner whose
output cannot be read reports zero, every comparison against zero passes, and
the promise quietly stops being kept - which is exactly what happened to the
first JavaScript project that came through here. So each shape below exists
because a real run produced it.
"""

import re

# Maven surefire: one line per class, then a grand total.
_MAVEN = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)\s*$",
    re.MULTILINE,
)

# pytest's summary line.
_PYTEST = re.compile(r"(\d+) passed(?:,\s*(\d+) failed)?(?:,\s*(\d+) skipped)?")

# node:test's TAP-ish summary block.
_NODE = re.compile(
    r"^# tests (\d+)$.*?^# pass (\d+)$.*?^# fail (\d+)$",
    re.MULTILINE | re.DOTALL,
)
_NODE_SKIP = re.compile(r"^# skipped (\d+)$", re.MULTILINE)

# Vitest and jest: "Tests  12 passed (12)" / "Tests: 3 failed, 9 passed, 12 total".
_VITEST = re.compile(
    r"^\s*Tests\s+(?:(\d+) failed[^\n]*?\|\s*)?(\d+) passed"
    r"(?:\s*\|\s*(\d+) skipped)?[^\n]*\((\d+)\)",
    re.MULTILINE,
)
_JEST = re.compile(
    r"^Tests:\s+(?:(\d+) failed,\s*)?(?:(\d+) skipped,\s*)?"
    r"(?:(\d+) passed,\s*)?(\d+) total",
    re.MULTILINE,
)

# Go: one ok/FAIL line per package, so this counts PASS lines instead.
_GO = re.compile(r"^(--- (PASS|FAIL|SKIP):)", re.MULTILINE)

# .NET: "Passed! - Failed: 0, Passed: 12, Skipped: 0, Total: 12"
_DOTNET = re.compile(
    r"Failed:\s*(\d+),\s*Passed:\s*(\d+),\s*Skipped:\s*(\d+),\s*Total:\s*(\d+)"
)


def read_test_counts(output: str) -> tuple[int, int, int]:
    # Named read_* rather than test_*: pytest collects anything whose name
    # starts with test_, including a function imported into a test module,
    # and then reports it as an error with a missing fixture.
    """Return (run, failed, skipped). Zeros when nothing can be read."""
    totals = _MAVEN.findall(output)
    if totals:
        # Surefire prints a line per class and then one grand total. The last
        # match is the total; summing the per-class lines double counts it.
        run, failures, errors, skipped = (int(n) for n in totals[-1])
        return run, failures + errors, skipped

    if match := _DOTNET.search(output):
        failed, _passed, skipped, total = (int(n) for n in match.groups())
        return total, failed, skipped

    # node:test before vitest: its summary also contains the word "pass",
    # which the pytest shape would otherwise half-match.
    if match := _NODE.search(output):
        total, _passed, failed = (int(n) for n in match.groups())
        skipped = int(m.group(1)) if (m := _NODE_SKIP.search(output)) else 0
        return total, failed, skipped

    if match := _VITEST.search(output):
        failed = int(match.group(1) or 0)
        skipped = int(match.group(3) or 0)
        total = int(match.group(4))
        return total, failed, skipped

    if match := _JEST.search(output):
        failed = int(match.group(1) or 0)
        skipped = int(match.group(2) or 0)
        total = int(match.group(4))
        return total, failed, skipped

    if match := _PYTEST.search(output):
        passed = int(match.group(1))
        failed = int(match.group(2) or 0)
        skipped = int(match.group(3) or 0)
        return passed + failed, failed, skipped

    outcomes = _GO.findall(output)
    if outcomes:
        kinds = [kind for _, kind in outcomes]
        return len(kinds), kinds.count("FAIL"), kinds.count("SKIP")

    return 0, 0, 0
