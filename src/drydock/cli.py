"""Command line.

drydock survey --repo PATH --task "..."
drydock plan                  uses the most recent run
drydock show
"""

import argparse
import textwrap
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from .analyst import baseline, survey
from .detect import detect
from .engines import stop_workers
from .orchestrate import execute
from .planner import plan
from .policy import Policy
from .run import Run, event_printer
from .skills import discover, load


def _wrap(text: str, indent: str = "      ") -> str:
    return textwrap.fill(
        text, width=96, initial_indent=indent, subsequent_indent=indent
    )


SKILLS = Path("skills")


def _chosen_skills(names: list[str] | None, chain=None) -> list:
    """Load the bodies of the skills that were asked for, and only those."""
    available = discover(SKILLS) if SKILLS.exists() else []
    if not names:
        return []
    by_name = {s.name: s for s in available}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise SystemExit(
            f"no skill named {', '.join(missing)}. "
            f"Installed: {', '.join(by_name) or 'none'}"
        )
    picked = [load(by_name[n]) for n in names]
    if chain:
        for skill in picked:
            if not skill.fits(chain.language, chain.build_tool):
                print(
                    f"  note: skill '{skill.name}' is written for "
                    f"{', '.join(skill.applies_to)}, this repo is "
                    f"{chain.language}/{chain.build_tool}"
                )
    return picked


def _cmd_skills(args) -> int:
    available = discover(SKILLS) if SKILLS.exists() else []
    if not available:
        print("no skills installed")
        return 0
    for skill in available:
        applies = f"  [{', '.join(skill.applies_to)}]" if skill.applies_to else ""
        print(f"{skill.name}{applies}")
        print(_wrap(skill.description, "    "))
    print(
        f"\n{len(available)} skills, frontmatter only. A body is read when it is chosen."
    )
    return 0


def _decide_profile(run, asked: str) -> Policy:
    """The policy for this run, resolved the way the application resolves it.

    One place, so the CLI and the application cannot drift. What was
    asked for, what the task's own risk floor raised it to, and the
    result are all written onto the record: a run that says only
    "balanced" cannot answer whether somebody chose that or the floor
    did.

    Raised, never lowered. A task that names a migration, an
    authorization change, money or data removal is not allowed to take
    the cheap road however it was requested.
    """
    from .policy import at_least, floor_for, of
    from .settings import Settings

    wanted = (asked or Settings.load().profile or "").strip().lower()
    raised = floor_for(run.task)
    policy = at_least(of(wanted), raised.floor)
    run.profile_asked = wanted
    run.profile_used = policy.profile
    run.profile_floor = raised.why if policy.profile != wanted else ""
    return policy


def _policy_of(run) -> Policy:
    """The policy a later stage of the same run must use.

    Read off the record rather than resolved again, so `plan` and `run`
    cannot disagree with the `survey` that decided it - and so a change
    to the person's settings halfway through a run does not change the
    run.
    """
    from .policy import of

    if run.profile_used:
        return of(run.profile_used)
    # A record written before this was kept. Resolve it the same way
    # rather than silently falling back to the default.
    return _decide_profile(run, "")


def _say_profile(run, policy) -> None:
    if run.profile_floor:
        print(
            f"profile: {policy.profile} (asked for {run.profile_asked or 'default'}; "
            f"raised because {run.profile_floor})"
        )
    else:
        print(f"profile: {policy.profile}")


def _cmd_survey(args) -> int:
    repo = Path(args.repo).expanduser().resolve()
    chain = detect(repo)
    skills = _chosen_skills(args.skill, chain)
    run = Run.start(repo, args.task, [s.name for s in skills])
    run.budget = args.budget
    policy = _decide_profile(run, getattr(args, "profile", "") or "")
    _say_profile(run, policy)
    print(f"{chain.build_tool} / {chain.language}")
    if skills:
        print(f"skills: {', '.join(s.name for s in skills)}")

    print("\nmeasuring the repository as it stands")
    run.baseline = baseline(repo, chain)
    b = run.baseline
    print(
        f"  build {'ok' if b.builds else 'FAILED'}, "
        f"{b.tests_run} tests, {b.tests_failed} failing, {b.tests_skipped} skipped"
    )
    if not b.green:
        print("  the suite is not green; nothing after this can be called a regression")
    run.save()

    print("\nsurveying")
    began = time.monotonic()
    run.inventory, usage = survey(
        repo,
        args.task,
        b,
        skills,
        event_printer(),
        model=args.model,
        budget=run.left if run.budget else 0.0,
    )
    run.spend(usage, station="analyst", seconds=time.monotonic() - began)
    run.save()

    print(f"\n{len(run.inventory.findings)} findings, {len(run.inventory.risks)} risks")
    print(_spend(run))
    return 0


def _by_station(run) -> str:
    """What each station cost and took, for the end of a stage."""
    held = run.by_station()
    if not held:
        return ""
    widest = max(len(name) for name in held)
    lines = [
        f"  {name:<{widest}}  {v['calls']:>2} call(s)  "
        f"{v['seconds']:>7.1f}s  ${v['dollars']:.2f}"
        for name, v in held.items()
    ]
    return "\n".join(lines)


def _spend(run) -> str:
    cached = run.tokens_cached
    saved = cached / 1e6 * 5 * 0.9 if cached else 0.0
    note = (
        f" ({cached:,} tokens came from cache, saving about ${saved:.2f})"
        if cached
        else ""
    )
    return f"run {run.id}  ${run.cost:.2f}{note}"


def _cmd_plan(args) -> int:
    run = Run.load(args.run) if args.run else Run.latest()
    if not run.inventory:
        raise SystemExit("that run has no survey yet")
    repo = Path(run.repo)
    policy = _policy_of(run)
    # Planning twice costs what planning costs. I did it by accident on
    # run 20261124-153354 - two planner calls, $0.38 and $0.15, and the
    # second one's plan is the one that ran. Nothing stopped it and
    # nothing would have said so afterwards if the station lines had not
    # just started being written down.
    if run.plan and not getattr(args, "again", False):
        print(
            f"run {run.id} already has a plan of {len(run.plan.items)} item(s). "
            "Pass --again to plan it over, which costs another planner call, "
            "or `drydock run` to work the plan it has."
        )
        return 0

    _say_profile(run, policy)
    print(f"planning: {run.task}\n")
    began = time.monotonic()
    run.plan, usage = plan(
        repo,
        run.task,
        run.inventory,
        run.baseline,
        _chosen_skills(run.skills),
        event_printer(),
        # The policy the survey settled. Without this the planner is
        # told the default's item range whatever the person chose, which
        # is how a `fast` run was planned as `balanced`.
        policy=policy,
    )
    run.spend(usage, station="planner", seconds=time.monotonic() - began)
    run.save()

    print(f"\n{run.plan.summary}\n")
    for item in run.plan.items:
        print(f"  {item.id:>2}. {item.title}   [{item.verify_with}]")
        print(_wrap(item.rationale))
        print(f"      files: {', '.join(item.files[:4])}")
        print()
    print(f"{len(run.plan.items)} items   {_spend(run)}")
    return 0


MARK = {"done": "ok", "reverted": "REVERTED", "blocked": "BLOCKED", "skipped": "--"}


def _cmd_run(args) -> int:
    run = Run.load(args.run) if args.run else Run.latest()
    if not run.plan:
        raise SystemExit("that run has no plan yet")

    def on_item(item, phase):
        if phase == "start":
            print(f"\n{item.id:>2}. {item.title}")
        else:
            print(f"    -> {MARK.get(phase, phase)}")

    # A deadline, when one was asked for. The same two halves the
    # application uses: the workers of this run are ended, and the flag
    # stops anything else being started - a retry, a restart of a worker
    # that was just terminated, a split, the next wave.
    _say_profile(run, _policy_of(run))

    out_of_time = {"yes": False}
    clock = None
    if getattr(args, "minutes", 0):

        def times_up() -> None:
            out_of_time["yes"] = True
            stopped = stop_workers(Path(run.repo))
            print(f"\n  the {args.minutes:g} minutes are up; {stopped} worker(s) ended")

        clock = threading.Timer(args.minutes * 60, times_up)
        clock.daemon = True
        clock.start()

    try:
        run = execute(
            run,
            stop_after=args.items,
            on_event=event_printer("      "),
            on_item=on_item,
            should_stop=lambda: out_of_time["yes"],
            # The same policy the application passes. Without it
            # `execute` fell back to `of(None)`, which is `balanced`, so
            # every CLI run ignored the chosen profile: measured on run
            # 20261124-142030, which was asked for `fast` and reviewed
            # the diff because `balanced` does.
            policy=_policy_of(run),
        )
    finally:
        if clock is not None:
            clock.cancel()

    print()
    for result in run.results:
        print(
            f"  {result.item.id:>2}. {MARK[result.outcome.value]:<9} {result.note[:70]}"
        )
    print(f"\n{len(run.results)}/{len(run.plan.items)} items   {_spend(run)}")
    said = _by_station(run)
    if said:
        print(said)
        split = run.phases()
        print(
            f"  {'before any code':<16}  {split['preparation']['calls']:>2} call(s)  "
            f"{split['preparation']['seconds']:>7.1f}s  "
            f"${split['preparation']['dollars']:.2f}"
        )
        print(
            f"  {'working':<16}  {split['execution']['calls']:>2} call(s)  "
            f"{split['execution']['seconds']:>7.1f}s  "
            f"${split['execution']['dollars']:.2f}"
        )
    return 0


def _cmd_app(args) -> int:
    """Open the application."""
    import uvicorn

    print(f"drydock at http://127.0.0.1:{args.port}")
    uvicorn.run(
        "drydock.web:app", host="127.0.0.1", port=args.port, log_level="warning"
    )
    return 0


def _cmd_show(args) -> int:
    run = Run.load(args.run) if args.run else Run.latest()
    print(f"{run.id}  {run.task}")
    print(f"repo {run.repo}")
    if run.baseline:
        print(
            f"baseline: {run.baseline.tests_run} tests, {run.baseline.tests_failed} failing"
        )
    if run.inventory:
        print(f"\nFINDINGS ({len(run.inventory.findings)})")
        for f in run.inventory.findings:
            print(_wrap(f, "  - ")[:400])
        print(f"\nRISKS ({len(run.inventory.risks)})")
        for r in run.inventory.risks:
            print(_wrap(r, "  ! ")[:400])
    if run.plan:
        print(f"\nPLAN ({len(run.plan.items)} items)")
        for item in run.plan.items:
            print(f"  {item.id:>2}. {item.title}")
    print(f"\n${run.cost:.2f}")
    return 0


def refresh_skills(which: str | None, about: str, write: bool, model: str) -> None:
    """Check packaged knowledge against what is current, and say what moved.

    Skills do not fail when they go out of date. They produce confidently
    dated work, which is worse, because nothing reports it. So the check is
    deliberate and periodic rather than something anyone is expected to
    notice.
    """
    import tempfile
    from datetime import datetime

    from .scout import as_note, check

    installed = discover(SKILLS) if SKILLS.exists() else []
    if which:
        installed = [s for s in installed if s.name == which]
        if not installed:
            raise SystemExit(f"no skill named {which}")

    today = datetime.now().strftime("%Y-%m-%d")
    spent = 0.0

    with tempfile.TemporaryDirectory(prefix="drydock-scout-") as scratch:
        for skill in installed:
            subject = about or skill.description
            print(f"\n{skill.name}  —  checking against: {subject}")
            body = (skill.path / "SKILL.md").read_text()
            changes, summary, dollars = check(
                body,
                subject,
                today,
                Path(scratch),
                model=model,
                on_event=lambda kind, text: print(f"    {kind}: {text[:90]}"),
            )
            spent += dollars

            worth = [c for c in changes if c.kind in ("wrong", "missing")]
            print(f"  {summary[:300]}")
            for change in changes:
                mark = {"wrong": "✗", "missing": "+", "confirmed": "✓"}.get(
                    change.kind, "·"
                )
                print(f"  {mark} {change.what[:140]}")
                print(f"      {change.source}")

            if write and worth:
                note = as_note(changes, subject, today)
                with (skill.path / "SKILL.md").open("a") as out:
                    out.write(note)
                print(f"  written into {skill.path / 'SKILL.md'}")
            elif worth:
                print("  not written. Pass --write to put these in the skill.")

    print(f"\nchecked {len(installed)} skill(s), ${spent:.2f} of work")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="drydock")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("survey", help="measure the repository and look around")
    s.add_argument("--repo", required=True)
    s.add_argument("--task", required=True)
    s.add_argument(
        "--skill",
        action="append",
        help="a skill to bring to this job; repeat for several",
    )
    s.add_argument(
        "--budget",
        type=float,
        default=0.0,
        help="dollars this run may spend; it stops rather than exceeding it",
    )
    s.add_argument("--model", help="override the model for the survey")
    s.add_argument(
        "--profile",
        choices=["fast", "balanced", "deep"],
        help="how much ceremony this run gets; the stored setting otherwise. "
        "Raised, never lowered: a task that names a migration, an "
        "authorization change, money or data removal is not allowed to run "
        "as fast",
    )
    s.set_defaults(func=_cmd_survey)

    p = sub.add_parser("plan", help="turn the survey into an ordered list of changes")
    p.add_argument("--run")
    p.add_argument(
        "--again",
        action="store_true",
        help="plan a run that already has a plan, which costs another planner call",
    )
    p.set_defaults(func=_cmd_plan)

    r = sub.add_parser("run", help="work the plan, one item at a time")
    r.add_argument("--run")
    r.add_argument("--items", type=int, help="stop after this many items")
    r.add_argument(
        "--minutes",
        type=float,
        default=0.0,
        help="end the run after this many minutes, whatever it is doing",
    )
    r.set_defaults(func=_cmd_run)

    t = sub.add_parser("app", help="open the application")
    t.add_argument("--port", type=int, default=8400)
    t.set_defaults(func=_cmd_app)

    c = sub.add_parser(
        "refresh", help="check a skill against what is current and update it"
    )
    c.add_argument("skill", nargs="?", help="which skill; all of them if omitted")
    c.add_argument("--about", default="", help="what to check it against")
    c.add_argument("--write", action="store_true", help="write the findings in")
    c.add_argument("--model", default="opus")
    c.set_defaults(func=lambda a: refresh_skills(a.skill, a.about, a.write, a.model))

    k = sub.add_parser("skills", help="list installed skills")
    k.set_defaults(func=_cmd_skills)

    w = sub.add_parser("show", help="print a run")
    w.add_argument("--run")
    w.set_defaults(func=_cmd_show)

    args = parser.parse_args()
    raise SystemExit(args.func(args))
