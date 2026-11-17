"""The loop that runs the plan.

One item at a time: work, verify, and then either keep it or throw it away.
Throwing it away is the default response to a red verification, not a last
resort, which is only affordable because each item is its own commit and the
repository was clean before it started.

The retry is deliberately limited to one. An agent given unlimited attempts at
a failing test does not converge on a fix; it converges on whatever makes the
test stop complaining, and the second attempt is where that starts.
"""

from pathlib import Path

from .engineer import work
from .models import ItemResult, Outcome
from .repo import Repo
from .run import Run
from .verify import verify


def execute(
    run: Run,
    stop_after: int | None = None,
    skills=None,
    on_event=None,
    on_item=None,
) -> Run:
    repo_path = Path(run.repo)
    repo = Repo(repo_path)
    commands = {
        "build": run.inventory.build_command,
        "tests": run.inventory.test_command,
    }

    if not repo.is_clean():
        raise SystemExit(
            f"{repo_path} has uncommitted changes. The crew needs a clean tree so "
            "that reverting an item removes exactly what the item did."
        )

    branch = f"drydock/{run.id}"
    repo.branch(branch)
    done = {r.item.id for r in run.results}

    for item in run.plan.items:
        if item.id in done:
            continue
        if stop_after is not None and len(run.results) >= stop_after:
            break

        if on_item:
            on_item(item, "start")

        attempt, failure, result = 1, "", None
        while attempt <= 2:
            report, usage = work(
                repo_path,
                run.task,
                item,
                commands["build"],
                failure,
                skills,
                on_event,
            )
            run.spend(usage)

            if not report.get("done"):
                result = ItemResult(
                    item=item,
                    outcome=Outcome.BLOCKED,
                    attempts=attempt,
                    note=report.get("summary", "the engineer could not do this item"),
                )
                repo.discard()
                break

            verdict = verify(repo_path, item.verify_with, run.baseline, commands)
            if verdict.passed:
                commit = repo.commit(f"{item.id}. {item.title}\n\n{report['summary']}")
                result = ItemResult(
                    item=item,
                    outcome=Outcome.DONE,
                    attempts=attempt,
                    files_changed=report.get("files_changed", []),
                    checks=[verdict.check],
                    note=verdict.reason,
                    commit=commit,
                )
                break

            if attempt == 2:
                repo.discard()
                result = ItemResult(
                    item=item,
                    outcome=Outcome.REVERTED,
                    attempts=2,
                    checks=[verdict.check],
                    note=verdict.reason,
                )
                break

            failure = f"{verdict.reason}\n\n{verdict.check.detail}"
            attempt += 1

        run.results.append(result)
        run.save()
        if on_item:
            on_item(item, result.outcome.value)

        if result.outcome in (Outcome.REVERTED, Outcome.BLOCKED):
            # Items are ordered, so a later one usually assumes this one landed.
            # Carrying on would pile changes onto a foundation that was removed.
            break

    return run
