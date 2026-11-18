"""One item, end to end, in about a minute.

Verifying a change to the harness by building a six-item website takes
thirty minutes and can only fail for one reason at a time. This builds a
tiny repository, runs a single item through every station, and prints what
happened - which is enough to catch a change that broke the loop.

    uv run python scenario.py              # the ordinary path
    uv run python scenario.py undecided    # an item that has to ask
    uv run python scenario.py visual       # an item the critic looks at
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from drydock.models import Baseline, Item, Plan
from drydock.orchestrate import execute
from drydock.run import Run

SHAPES = {
    "ordinary": dict(
        title="Add vat.js exporting withVat(price) returning price * 1.2",
        rationale="The till shows what the customer pays.",
        files=["vat.js", "vat.test.js"],
    ),
    "undecided": dict(
        title="Add till.js exporting display() returning each item and its price",
        rationale=(
            "prices.js holds the prices and vat.js holds the VAT rate; the "
            "item does not say which of the two the displayed price is."
        ),
        files=["till.js", "till.test.js"],
    ),
    "visual": dict(
        title="Add index.html: the shop name, the prices, and a dark band",
        rationale="Somebody on the corner wants to know what things cost.",
        files=["index.html"],
    ),
}


def a_shop() -> Path:
    where = Path(tempfile.mkdtemp()) / "shop"
    where.mkdir(parents=True)

    def sh(command: str) -> None:
        subprocess.run(command, cwd=where, shell=True, capture_output=True, check=True)

    sh("git init -q && git config user.email t@t && git config user.name t")
    (where / "package.json").write_text(
        '{"name":"shop","type":"module","scripts":{"test":"node --test"}}\n'
    )
    (where / "prices.js").write_text("export const prices = {coffee: 4, bun: 3};\n")
    (where / "vat.js").write_text("export const VAT = 0.2;\n")
    (where / "base.test.js").write_text(
        "import {test} from 'node:test';import a from 'node:assert/strict';\n"
        "import {prices} from './prices.js';\n"
        "test('prices exist', () => a.equal(prices.coffee, 4));\n"
    )
    sh("git add -A && git commit -q -m 'before drydock'")
    return where


def main() -> int:
    shape = SHAPES[sys.argv[1] if len(sys.argv) > 1 else "ordinary"]
    where = a_shop()

    run = Run.start(where, "run the shop's till")
    run.baseline = Baseline(builds=True, tests_run=1, tests_failed=0, tests_skipped=0)
    run.engine, run.model = "claude", "opus"
    run.plan = Plan(
        summary="One item.",
        items=[Item(id=1, verify_with="tests", plain="", needs=[], **shape)],
    )

    started = time.monotonic()
    execute(
        run,
        engine="claude",
        model="opus",
        reviewing=True,
        on_item=lambda item, phase: print(f"  item {item.id} {phase}", flush=True),
        on_gate=lambda item, who, ok, note: print(
            f"\n  {who.upper()} {'passed' if ok else 'refused'}\n  {note[:400]}\n",
            flush=True,
        ),
    )

    print("=" * 60)
    print(f"{time.monotonic() - started:.0f}s   {where}")
    for result in run.results:
        print(f"  {result.item.id} {result.outcome.value}: {result.note[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
