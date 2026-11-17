"""The loop that runs the plan.

One item at a time: work, verify, and then either keep it or throw it away.
Throwing it away is the default response to a red verification, not a last
resort, which is only affordable because each item is its own commit and the
repository was clean before it started.

The retry is deliberately limited to one. An agent given unlimited attempts at
a failing test does not converge on a fix; it converges on whatever makes the
test stop complaining, and the second attempt is where that starts.
"""

import re
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .agent import BudgetExceeded
from .critic import look as look_at_it
from .detect import detect
from .engineer import work
from .inspect import look
from .models import ItemResult, Outcome
from .repo import Repo
from .reviewer import review
from .run import Run
from .verify import verify


class DirtyTree(Exception):
    """The tree was not clean when the loop was asked to start.

    An ordinary exception on purpose. This used to be SystemExit, which is
    not an Exception and so slips past every `except Exception` in the
    program - including the one guarding the thread a job runs on. The result
    was a thread that died in silence while the page kept its spinner.
    """


# Files whose change is visible to somebody. A change to a parser is not.
SEEN = re.compile(
    r"\.(css|scss|sass|less|html|htm|ejs|astro|vue|svelte|hbs|pug|njk)$"
    r"|\.(jsx|tsx)$"
    r"|(^|/)(views|templates|pages|components|layouts|styles|public|static)/"
)


def _changes_the_view(diff: str) -> bool:
    return any(
        SEEN.search(path) for path in re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)
    )


def _show_it(repo_path: Path, run, item, on_event):
    """Start the project, photograph it, and have somebody look.

    Nothing here is allowed to take a run down. A project that will not
    start, a machine with no browser, a page that does not render - each is
    a check that did not happen, reported as such, rather than an item
    rolled back for a failure that belongs to this program.
    """
    import tempfile

    from . import preview

    try:
        live = preview.running(repo_path) or preview.start(repo_path)
    except (LookupError, RuntimeError, TimeoutError) as exc:
        if on_event:
            on_event("critic", f"could not start the project to look at it: {exc}")
        return None, 0.0

    with tempfile.TemporaryDirectory(prefix="drydock-look-") as scratch:
        try:
            return look_at_it(
                live.url,
                run.direction,
                item.plain or item.title,
                Path(scratch),
                model=run.model,
                on_event=on_event,
            )
        except Exception as exc:  # noqa: BLE001 - a failed look is not a failed item
            if on_event:
                on_event("critic", f"could not look at it: {exc}")
            return None, 0.0


def _judge(
    repo,
    repo_path: Path,
    run,
    item,
    diff: str,
    report: dict,
    reviewing: bool,
    engine: str,
    model: str,
    on_event,
    on_gate,
) -> str:
    """Run the two opinions at once and return the first refusal, if any.

    They are independent: one reads the change, the other looks at the page.
    Sequencing them was pure waiting. Both still report, and a refusal from
    either sends the item back - running them together changes when the
    answers arrive, not what they are allowed to decide.
    """
    jobs: dict[str, Future] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        if reviewing:
            jobs["reviewer"] = pool.submit(
                review,
                repo_path,
                item,
                repo.pending_for_review(),
                report.get("summary", ""),
                engine=engine,
                model=model,
                on_event=on_event,
            )
        if run.direction and _changes_the_view(diff):
            jobs["critic"] = pool.submit(_show_it, repo_path, run, item, on_event)

    refusals = []
    for name, job in jobs.items():
        try:
            answer, spend = job.result()
        except Exception as exc:  # noqa: BLE001 - one gate failing is not the item failing
            if on_event:
                on_event(name, f"could not finish: {exc}")
            continue

        if name == "reviewer":
            run.spend(spend)
            if on_gate:
                on_gate(item, name, answer["approved"], answer["reason"])
            if not answer["approved"]:
                refusals.append(answer["reason"])
        elif answer is not None:
            run.dollars += spend
            if on_gate:
                on_gate(
                    item,
                    name,
                    answer.approved,
                    answer.reason
                    if answer.looked
                    else "not looked at: " + answer.reason,
                )
            if not answer.approved:
                refusals.append(answer.reason)

    return "\n\n".join(refusals)


def execute(
    run: Run,
    stop_after: int | None = None,
    per_item: float = 2.5,
    engine: str = "api",
    model: str = "opus",
    skills=None,
    on_event=None,
    on_item=None,
    should_stop=None,
    on_gate=None,
    reviewing: bool = True,
) -> Run:
    repo_path = Path(run.repo)
    repo = Repo(repo_path)

    def commands_now() -> dict:
        """Read the toolchain again, because an item may have created it."""
        chain = detect(repo_path)
        return {"build": chain.build_command, "tests": chain.test_command}

    repo.sweep()
    if not repo.is_clean():
        raise DirtyTree(
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

        if should_stop and should_stop():
            if on_item:
                on_item(item, "stopped")
            break

        if run.budget and run.left <= 0:
            # A run that has spent its budget stops between items, where the
            # tree is clean and the next item can be resumed later, rather
            # than halfway through an edit.
            if on_item:
                on_item(item, "out_of_budget")
            break

        if on_item:
            on_item(item, "start")

        attempt, failure, result = 1, "", None
        while attempt <= 2:
            try:
                report, usage = work(
                    repo_path,
                    run.task,
                    item,
                    commands_now()["build"],
                    failure,
                    skills,
                    on_event,
                    budget=min(run.left, per_item) if run.budget else per_item,
                    engine=engine,
                    model=model,
                    direction=run.direction,
                )
            except BudgetExceeded as stop:
                repo.discard()
                result = ItemResult(
                    item=item, outcome=Outcome.BLOCKED, attempts=attempt, note=str(stop)
                )
                break
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

            verdict = verify(repo_path, item.verify_with, run.baseline, commands_now())

            # Three gates, cheapest first, and each one may send the item back.
            # The suite says the change did not break what was watched. The
            # inspector says it did not reach green by watching less. The
            # reviewer says it did the item and not something else. A change
            # has to pass all three to be allowed to stay.
            refusal = ""
            if verdict.passed:
                diff = repo.pending()
                report_card = look(diff, allow_removals=item.removes_tests)
                if on_gate:
                    on_gate(item, "inspector", report_card.clean, report_card.reason)
                if not report_card.clean:
                    refusal = report_card.reason
                else:
                    # The reviewer reads the diff; the critic looks at the
                    # rendered page. Neither needs the other's answer, and
                    # waiting for one before starting the other was adding
                    # about a hundred seconds to every visual item for no
                    # reason at all.
                    refusal = _judge(
                        repo,
                        repo_path,
                        run,
                        item,
                        diff,
                        report,
                        reviewing,
                        engine,
                        model,
                        on_event,
                        on_gate,
                    )

            if verdict.passed and not refusal:
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

            why = refusal or verdict.reason

            if attempt == 2:
                repo.discard()
                result = ItemResult(
                    item=item,
                    outcome=Outcome.REVERTED,
                    attempts=2,
                    checks=[verdict.check],
                    note=why,
                )
                break

            # A refusal is handed back as what it is. Telling the engineer the
            # suite failed when the reviewer objected would send it looking in
            # the wrong place for the whole of the second attempt.
            failure = why if refusal else f"{verdict.reason}\n\n{verdict.check.detail}"
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
