"""Pull numbers out of build output.

Surefire and pytest both announce their totals in a line with a recognisable
shape. Reading that line is better than asking a model to summarise the log:
it is free, instant, and it cannot round 838 down to "most of them".
"""

import re

_MAVEN = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)\s*$",
    re.MULTILINE,
)
_PYTEST = re.compile(r"(\d+) passed(?:,\s*(\d+) failed)?(?:,\s*(\d+) skipped)?")


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

    if match := _PYTEST.search(output):
        passed = int(match.group(1))
        failed = int(match.group(2) or 0)
        skipped = int(match.group(3) or 0)
        return passed + failed, failed, skipped

    return 0, 0, 0
