"""Command line.

drydock survey --repo PATH --task "..."
drydock plan                  uses the most recent run
drydock show
"""

import argparse
import textwrap
from pathlib import Path

from dotenv import load_dotenv

from .analyst import baseline, survey
from .detect import detect
from .orchestrate import execute
from .planner import plan
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


def _cmd_survey(args) -> int:
    repo = Path(args.repo).expanduser().resolve()
    chain = detect(repo)
    skills = _chosen_skills(args.skill, chain)
    run = Run.start(repo, args.task, [s.name for s in skills])
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
    run.inventory, usage = survey(repo, args.task, b, skills, event_printer())
    run.spend(usage)
    run.save()

    print(f"\n{len(run.inventory.findings)} findings, {len(run.inventory.risks)} risks")
    print(f"run {run.id}  ${run.cost:.2f}")
    return 0


def _cmd_plan(args) -> int:
    run = Run.load(args.run) if args.run else Run.latest()
    if not run.inventory:
        raise SystemExit("that run has no survey yet")
    repo = Path(run.repo)

    print(f"planning: {run.task}\n")
    run.plan, usage = plan(
        repo,
        run.task,
        run.inventory,
        run.baseline,
        _chosen_skills(run.skills),
        event_printer(),
    )
    run.spend(usage)
    run.save()

    print(f"\n{run.plan.summary}\n")
    for item in run.plan.items:
        print(f"  {item.id:>2}. {item.title}   [{item.verify_with}]")
        print(_wrap(item.rationale))
        print(f"      files: {', '.join(item.files[:4])}")
        print()
    print(f"{len(run.plan.items)} items   run {run.id}   ${run.cost:.2f}")
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

    run = execute(
        run, stop_after=args.items, on_event=event_printer("      "), on_item=on_item
    )

    print()
    for result in run.results:
        print(
            f"  {result.item.id:>2}. {MARK[result.outcome.value]:<9} {result.note[:70]}"
        )
    print(f"\n{len(run.results)}/{len(run.plan.items)} items   ${run.cost:.2f}")
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
    s.set_defaults(func=_cmd_survey)

    p = sub.add_parser("plan", help="turn the survey into an ordered list of changes")
    p.add_argument("--run")
    p.set_defaults(func=_cmd_plan)

    r = sub.add_parser("run", help="work the plan, one item at a time")
    r.add_argument("--run")
    r.add_argument("--items", type=int, help="stop after this many items")
    r.set_defaults(func=_cmd_run)

    k = sub.add_parser("skills", help="list installed skills")
    k.set_defaults(func=_cmd_skills)

    w = sub.add_parser("show", help="print a run")
    w.add_argument("--run")
    w.set_defaults(func=_cmd_show)

    args = parser.parse_args()
    raise SystemExit(args.func(args))
