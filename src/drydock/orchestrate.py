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
from .planner import answer
from .repo import Repo
from .reviewer import review
from .run import Run
from .verify import verify
from .waves import Wave, plan_waves, stranded


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
                # Everything the item says about itself. The critic is being
                # asked whether this item did its part, and it cannot know
                # what that part was from a title alone.
                f"{item.plain or item.title}\n\n"
                f"In full: {item.as_asked()}",
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


def _one_item(
    where: Path,
    main: Repo,
    run,
    item,
    engine: str,
    model: str,
    reviewing: bool,
    per_item: float,
    on_event,
    on_gate,
):
    """Work one item to a verdict, in `where`, and return what happened.

    `where` is a working copy - the repository itself when items run one at
    a time, or a worktree of it when several run together. Everything in
    here is the same either way, which is the point: concurrency changed
    where the work happens and nothing about how it is judged.
    """
    here = Repo(where)
    # What this item was refused for before, if it has been tried before. A
    # resumed run used to start the item from nothing, and the engineer made
    # the same mistake it had already been corrected on.
    earlier = run.refused.pop(item.id, "")
    failure = (
        f"This item was attempted before and sent back. What was said:\n\n"
        f"{earlier}\n\nNothing from that attempt is on disk - it was thrown "
        "away - so you are starting from a clean tree. Start by working out "
        "what the complaint is about, because it is the same item and the "
        "same complaint is waiting."
        if earlier
        else ""
    )
    attempt, result = 1, None
    # Restarts for a worker that was taken away rather than one that
    # failed. Bounded, because a worker that cannot stay up twice running is
    # a machine problem and looping on it burns the run instead of
    # reporting it - but not one, because this has happened three times on
    # one item in an afternoon and each time the item itself was fine.
    revived, REVIVALS = 0, 2
    # One question per item. A loop in which the engineer and the planner
    # talk until they agree has no bound on it, and the thing being settled
    # is usually one sentence.
    settled = ""

    def commands_now() -> dict:
        chain = detect(where)
        return {"build": chain.build_command, "tests": chain.test_command}

    while attempt <= 2:
        try:
            report, usage = work(
                where,
                run.task,
                item,
                commands_now()["build"],
                failure,
                run.skills_loaded,
                on_event,
                budget=min(run.left, per_item) if run.budget else per_item,
                engine=engine,
                model=model,
                direction=run.direction,
            )
        except BudgetExceeded as stop:
            here.discard()
            return ItemResult(
                item=item, outcome=Outcome.BLOCKED, attempts=attempt, note=str(stop)
            ), None

        run.spend(usage)

        # It was killed rather than finishing. Nothing it wrote is trusted,
        # but nothing about the item has been learned either, so this is not
        # an attempt and the right response is to try the same item again.
        if report.get("died") and revived < REVIVALS:
            revived += 1
            here.discard()
            if on_gate:
                on_gate(
                    item,
                    "restarted",
                    True,
                    f"{report.get('summary', '')} (restart {revived} of {REVIVALS})",
                )
            failure = ""
            continue

        # It stopped to ask rather than to guess. Nothing was written, so
        # this does not count as an attempt - the item has not been tried
        # yet, it has been read and found unanswerable.
        asked = str(report.get("question") or "").strip()
        if asked and not settled:
            if on_gate:
                on_gate(item, "asked", True, asked)
            said, spend = answer(
                where,
                run.plan,
                item,
                asked,
                direction=run.direction,
                engine=engine,
                model=model,
                on_event=on_event,
            )
            run.spend(spend)
            settled = said
            if on_gate:
                on_gate(item, "answered", True, said)

            # Onto the item, not just into this attempt. The answer used to
            # live for the length of one worker: the attempt after it read
            # the original item, made the same discovery, and the reviewer
            # refused it for not doing what the item still said. Everyone
            # downstream now judges the item as settled.
            if not said.startswith("[this belongs in another item]"):
                item.settled.append(f"Asked: {asked}\n  Settled: {said}")
                run.save()

            if said.startswith("[this belongs in another item]"):
                return ItemResult(
                    item=item,
                    outcome=Outcome.BLOCKED,
                    attempts=attempt,
                    note=(
                        "stopped before writing anything. The engineer asked "
                        f"whether this item covers it:\n\n{asked}\n\n"
                        f"and the planner said it does not:\n\n{said}"
                    ),
                ), None

            failure = (
                f"You asked:\n\n{asked}\n\n"
                f"The answer, from whoever wrote the item:\n\n{said}\n\n"
                "Carry on with that settled."
            )
            continue

        if not report.get("done"):
            here.discard()
            return ItemResult(
                item=item,
                outcome=Outcome.BLOCKED,
                attempts=attempt,
                note=report.get("summary", "the engineer could not do this item"),
            ), None

        verdict = verify(where, item.verify_with, run.baseline, commands_now())

        refusal = ""
        if verdict.passed:
            diff = here.pending()
            report_card = look(diff, allow_removals=item.removes_tests, repo=where)
            if on_gate:
                on_gate(item, "inspector", report_card.clean, report_card.reason)
            if not report_card.clean:
                refusal = report_card.reason
            else:
                refusal = _judge(
                    here,
                    where,
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
            # The bar moves up with the work. It was the count from before
            # the run started and never shifted, so an item could delete
            # every test an earlier item had added and still clear it as
            # long as it stayed at the number the repository began with -
            # while the pull request said every item left the suite at
            # least as large as it found it. It does now.
            run.baseline.tests_run = max(run.baseline.tests_run, verdict.tests_run)
            commit = here.commit(f"{item.id}. {item.title}\n\n{report['summary']}")
            return ItemResult(
                item=item,
                outcome=Outcome.DONE,
                attempts=attempt,
                files_changed=report.get("files_changed", []),
                checks=[verdict.check],
                note=verdict.reason,
                commit=commit,
            ), commit

        why = refusal or verdict.reason
        if attempt == 2:
            here.discard()
            return ItemResult(
                item=item,
                outcome=Outcome.REVERTED,
                attempts=2,
                checks=[verdict.check],
                note=why,
            ), None

        failure = why if refusal else f"{verdict.reason}\n\n{verdict.check.detail}"
        attempt += 1

    return result, None


def _work_a_wave(
    repo: Repo,
    repo_path: Path,
    run,
    items: list,
    engine: str,
    model: str,
    reviewing: bool,
    per_item: float,
    on_event,
    on_gate,
) -> dict:
    """Work every item in a wave, then bring the ones that landed home.

    One item runs where it is. Several run in worktrees - separate files,
    the same git - because two workers in one checkout would see each
    other's half-finished edits and each diff would contain the other's
    work.

    They are brought back in the order they were planned, by cherry-pick, so
    each item stays one commit. A cherry-pick that will not apply means two
    items touched the same lines after the planner said they would not; that
    item is reported as reverted rather than resolved blind, because
    resolving a conflict nobody saw is how an agent silently loses work.
    """
    if len(items) == 1:
        result, _commit = _one_item(
            repo_path,
            repo,
            run,
            items[0],
            engine,
            model,
            reviewing,
            per_item,
            on_event,
            on_gate,
        )
        return {items[0].id: result}

    trees: dict[int, Path] = {}
    at = repo.head()
    try:
        for item in items:
            trees[item.id] = repo.worktree(f"item{item.id}", at)

        done: dict[int, tuple] = {}
        with ThreadPoolExecutor(max_workers=len(items)) as pool:
            jobs = {
                item.id: pool.submit(
                    _one_item,
                    trees[item.id],
                    repo,
                    run,
                    item,
                    engine,
                    model,
                    reviewing,
                    per_item,
                    on_event,
                    on_gate,
                )
                for item in items
            }
        for item in items:
            try:
                done[item.id] = jobs[item.id].result()
            except Exception as exc:  # noqa: BLE001 - one item failing is not the wave failing
                done[item.id] = (
                    ItemResult(
                        item=item,
                        outcome=Outcome.BLOCKED,
                        note=f"the worker stopped: {exc}",
                    ),
                    None,
                )

        out: dict[int, ItemResult] = {}
        for item in items:
            result, commit = done[item.id]
            if result.outcome is not Outcome.DONE or not commit:
                out[item.id] = result
                continue
            ok, said = repo.take(commit)
            if not ok:
                out[item.id] = ItemResult(
                    item=item,
                    outcome=Outcome.REVERTED,
                    attempts=result.attempts,
                    note=(
                        "this landed on its own but will not sit beside the "
                        "other work in this round; two items touched the same "
                        f"lines.\n\n{said}"
                    ),
                )
                continue
            result.commit = said
            out[item.id] = result
        return out
    finally:
        for where in trees.values():
            repo.drop_worktree(where)


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
    run.skills_loaded = skills
    landed = {r.item.id for r in run.results if r.outcome.value == "done"}

    failed: set[int] = set()
    for wave in plan_waves(run.plan.items, landed):
        # Everything in this wave that is already written off, skipped
        # rather than attempted against a foundation that is not there.
        wave = Wave(
            items=[i for i in wave.items if i.id not in judged(run)], why=wave.why
        )
        if not wave.items:
            continue
        if should_stop and should_stop():
            if on_item:
                on_item(wave.items[0], "stopped")
            break
        if run.budget and run.left <= 0:
            if on_item:
                on_item(wave.items[0], "out_of_budget")
            break
        if stop_after is not None and len(run.results) >= stop_after:
            break

        if on_event and len(wave.items) > 1:
            on_event(
                "wave",
                f"{len(wave.items)} items at once: {wave.why}",
            )
        for item in wave.items:
            if on_item:
                on_item(item, "start")

        results = _work_a_wave(
            repo,
            repo_path,
            run,
            wave.items,
            engine,
            model,
            reviewing,
            per_item,
            on_event,
            on_gate,
        )

        for item in wave.items:
            result = results.get(item.id)
            if result is None:
                continue
            run.results.append(result)
            run.save()
            if on_item:
                on_item(item, result.outcome.value)
            if result.outcome in (Outcome.REVERTED, Outcome.BLOCKED):
                failed.add(item.id)

        # A failed item used to stop the run, on the reasoning that a later
        # item usually assumes an earlier one landed. Usually is not always,
        # and the plan says which: every item names what it needs. So the
        # ones that are genuinely waiting on it are written off here, and
        # anything independent is still attempted.
        if failed:
            cannot = stranded(run.plan.items, failed)
            for item in run.plan.items:
                if item.id not in cannot or item.id in judged(run):
                    continue
                waiting = ", ".join(str(n) for n in cannot[item.id])
                result = ItemResult(
                    item=item,
                    outcome=Outcome.BLOCKED,
                    attempts=0,
                    note=(
                        f"not attempted: it needs item {waiting}, which did "
                        "not land. Nothing was written for it, so it is "
                        "still there to do once that one is."
                    ),
                )
                run.results.append(result)
                failed.add(item.id)
                if on_item:
                    on_item(item, result.outcome.value)
            run.save()
            if all(i.id in judged(run) for i in run.plan.items):
                break

    return run


def judged(run) -> set[int]:
    """Every item that already has a result, however it ended."""
    return {r.item.id for r in run.results}
