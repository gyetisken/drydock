"""The loop that runs the plan.

One item at a time: work, verify, and then either keep it or throw it away.
Throwing it away is the default response to a red verification, not a last
resort, which is only affordable because each item is its own commit and the
repository was clean before it started.

The retry is deliberately limited to one. An agent given unlimited attempts at
a failing test does not converge on a fix; it converges on whatever makes the
test stop complaining, and the second attempt is where that starts.
"""

import contextlib
import os
import re
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from . import blame, probe
from .agent import BudgetExceeded
from .critic import Verdict as Seen
from .critic import look as look_at_it
from .detect import detect
from .engineer import work
from .fits import why_it_does_not_fit
from .inspect import look
from .models import ItemResult, Outcome
from .planner import answer, split
from .policy import AT_THE_END, NEVER, Policy, of
from .repo import OUR_LOOK, GitError, Repo
from .reviewer import review
from .run import Run
from .verify import verify, verify_build
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


def _stopping(should_stop) -> bool:
    """Whether this run has been told to stop, asked wherever work starts.

    This used to be consulted in exactly one place - the top of the wave
    loop - which meant a stop request arrived and then waited for
    everything already in flight. With two attempts of eighteen minutes
    and two revivals of twelve, one item could run for the better part of
    an hour after somebody pressed stop, and a deadline built on it was
    not a deadline.
    """
    try:
        return bool(should_stop and should_stop())
    except Exception:  # noqa: BLE001 - a broken callback must not strand a run
        return False


def _the_same_refusal(now: str, before: str) -> bool:
    """Whether a refusal says what the last one said.

    Compared as words rather than as characters, because the same
    complaint about the same files can be wrapped differently and
    listed in a different order. Not a pattern and not a keyword: it
    knows nothing about what any particular refusal is about, which is
    the point - a rule that recognised `server.js` would recognise
    nothing else.
    """

    def words(said: str) -> frozenset:
        # Punctuation off the ends, because `server.js,` and `server.js`
        # are the same complaint and a comma is where the line wrapped.
        return frozenset(
            word
            for word in (w.strip(".,;:()[]`'\"") for w in (said or "").lower().split())
            if word
        )

    here, there = words(now), words(before)
    if not here or not there:
        return False
    return len(here & there) >= 0.9 * len(here | there)


def _stopped_here(item, attempt: int, why: str):
    """The result for work that was not done because the run was stopping."""
    return ItemResult(item=item, outcome=Outcome.BLOCKED, attempts=attempt, note=why)


def _worth_a_look(item) -> bool:
    """Whether this item renders something anybody will look at.

    The planner's own answer when it gave one. When it did not, the item's
    files decide: the diff cannot, because this is asked before the work
    exists. The same regex the gates use afterwards, so an item the
    engineer was allowed to look at is an item the critic will look at.
    """
    if item.worth_looking_at is not None:
        return bool(item.worth_looking_at)
    return any(SEEN.search(name) for name in item.files)


def _no_longer_serving(where: Path) -> None:
    """Stop whatever preview was started for this tree, if any.

    Never raises. A server that will not die is not a reason to leave a
    worktree behind, and the worktree is the thing that has to go.
    """
    from . import preview

    # OSError covers a process that has already gone and a roster file
    # that cannot be read; the rest of `stop` suppresses its own.
    with contextlib.suppress(OSError):
        preview.stop(where)


def _show_it(repo_path: Path, run, item, on_event):
    """Start the project, photograph it, and have somebody look.

    Nothing here is allowed to take a run down. A project that will not
    start, a machine with no browser, a page that does not render - each is
    a check that did not happen, reported as such, rather than an item
    rolled back for a failure that belongs to this program.
    """

    from . import preview

    try:
        live = preview.running(repo_path) or preview.start(repo_path)
    except (LookupError, RuntimeError, TimeoutError) as exc:
        if on_event:
            on_event("critic", f"could not start the project to look at it: {exc}")
        return None, 0.0

    # Whether there is a page here at all, before anybody is asked what
    # they think of it. A project whose own start command serves something
    # other than a page - an API with a /health route and no root, say -
    # hands the critic a browser's raw-JSON view, and the critic correctly
    # reports that there is no page. The item is then rolled back for it.
    #
    # Watched happen: a static page written into a project whose
    # package.json starts a JSON API. Four attempts, two reverts, a split
    # and thirty-three minutes, and the thing being photographed was never
    # the thing that had just been written.
    #
    # This is the case the top of this function already names: a check that
    # did not happen, reported as such, rather than an item rolled back for
    # a failure that belongs to this program.
    served = preview.what_it_serves(live.url)
    if not served.is_a_page:
        if on_event:
            on_event(
                "critic",
                f"did not look: {live.url} answered {served.said}, which is "
                f"not a page. `{live.command}` is what this project says "
                "starts it.",
            )
        return None, 0.0

    # Arithmetic before judgement. A page wider than the screen it is on is
    # the one visual defect that does not need an opinion, and it is the one
    # that has cost this crew the most: seven items refused for it in an
    # afternoon, each time by somebody describing what they saw rather than
    # measuring it. Measured, it is a number and an element name.
    does_not_fit = why_it_does_not_fit(live.url, on_event=on_event)
    if does_not_fit:
        if on_event:
            on_event("critic", does_not_fit.splitlines()[0])
        return Seen(looked=True, approved=False, reason=does_not_fit, noticed=[]), 0.0

    # And everything else the browser already knows, for the same reason
    # and at the same price. A page that renders one line of text and two
    # thousand pixels of empty ground is not a matter of taste, and it was
    # being discovered by photographing it and asking somebody - which
    # costs a model call, arrives late, and tells the engineer "most of
    # what this item owns is not on the page" when it could have been told
    # "the body has three words in it and the stylesheet 404s".
    #
    # Only what means the page is not working sends an item back, because
    # sending one back spends an attempt. The rest is handed to whoever
    # looks next, so they do not have to find it.
    seen = probe.look(live.url, 390)
    if seen.ran:
        breaking = seen.breaking()
        if breaking:
            said = "; ".join(breaking[:4])
            if on_event:
                on_event("critic", breaking[0])
            return Seen(looked=True, approved=False, reason=said, noticed=[]), 0.0
        noticed = seen.worth_saying()
    else:
        noticed = []

    # Not a temporary directory any more. When the critic sends an item
    # back, the one thing the engineer has to work with is a sentence
    # describing a photograph it cannot see - and twice in one run it read
    # that sentence, made a different change, and was told the same thing
    # again. The pictures stay where it can open them.
    # Into the tree being worked on, so the engineer can open them - and
    # if that is not somewhere this can write, a temporary directory and
    # no offer of pictures, because a path that is not there is worse
    # than no path at all.
    scratch = repo_path / OUR_LOOK
    try:
        scratch.mkdir(parents=True, exist_ok=True)
    except OSError:
        scratch = Path(tempfile.mkdtemp(prefix="drydock-look-"))
    try:
        verdict, spend = look_at_it(
            live.url,
            run.direction,
            # Everything the item says about itself. The critic is being
            # asked whether this item did its part, and it cannot know
            # what that part was from a title alone.
            f"{item.plain or item.title}\n\nIn full: {item.as_asked()}",
            scratch,
            # What was actually asked for, and then what it was taken to
            # mean. Without the first, the critic had only the direction
            # to judge against, so a direction that had drifted from the
            # brief was ratified rather than caught. The second is below
            # it and says so: it is context, never the standard.
            brief=run.as_briefed,
            model=run.model,
            on_event=on_event,
        )
        # What was measured goes on the record beside what was seen,
        # so a contrast failure or a control with no name reaches
        # somebody without having cost the item an attempt.
        if verdict is not None and noticed:
            verdict.noticed = list(verdict.noticed) + noticed
        return verdict, spend
    except Exception as exc:  # noqa: BLE001 - the run must not die here
        # A verdict that could not be produced, said as one. Returning
        # None meant "nothing to report", which is what a clean page
        # looks like from here, so an item shipped with the only station
        # that can see never having been heard from. See critic.Verdict.
        #
        # And said with its kind and its line, because `{exc}` alone
        # cannot tell a browser that is not installed from an
        # `AttributeError` of ours - and only one of those is somebody's
        # to fix. See blame.
        said = blame.report("critic", exc, on_event, note="could not look at it")
        return Seen(
            looked=True,
            approved=False,
            reason=said,
            noticed=[],
            failed=said,
        ), 0.0


def _judge(
    repo,
    repo_path: Path,
    run,
    item,
    diff: str,
    report: dict,
    policy: Policy,
    engine: str,
    model: str,
    on_event,
    on_gate,
) -> tuple[str, list[str]]:
    """Run the two opinions at once and report any refusal, and whose.

    They are independent: one reads the change, the other looks at the page.
    Sequencing them was pure waiting. Both still report, and a refusal from
    either sends the item back - running them together changes when the
    answers arrive, not what they are allowed to decide.
    """
    jobs: dict[str, Future] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        if policy.read_the_diff:
            jobs["reviewer"] = pool.submit(
                review,
                repo_path,
                item,
                repo.pending_for_review(),
                report.get("summary", ""),
                engine=engine,
                model=model,
                on_event=on_event,
                # The only station that never knew what the job was. It
                # read an item and a diff and nothing else, which is how
                # a criterion that is plain in context gets measured as
                # an arbitrary line.
                brief=run.as_briefed,
            )
        # The planner says whether this item is worth looking at; the diff
        # decides only when it did not say. A critic sent to judge a
        # placeholder page refuses it for being a placeholder, which is
        # true and useless, and three attempts went on an item that had
        # been finished the first time.
        by_eye = item.worth_looking_at
        if by_eye is None:
            by_eye = _changes_the_view(diff)
        # A profile that looks once, at the end, does not look here. The
        # looking still happens - it is the last thing a run does - but an
        # item on the way to a finished page is not judged as though it
        # were one.
        if policy.look_at_it == NEVER or policy.look_at_it == AT_THE_END:
            by_eye = False
        if run.direction and by_eye:
            jobs["critic"] = pool.submit(_show_it, repo_path, run, item, on_event)

    refusals = []
    # Checks that were required and could not be completed. Kept apart
    # from refusals because they are not the item's fault and retrying
    # the engineer would not change them.
    unverified: list[str] = []
    # Everything true that a gate said and did not refuse over. Kept
    # because it was being discarded: the reviewer's `noticed` reached
    # nothing at all, and the critic's was merged into a verdict that
    # nobody read it from.
    noticed: list[str] = []
    # Which gates refused, not only what they said. The two are not worth
    # the same: one read the diff against the item, the other looked at a
    # picture - and only one of them can be the sole reason an item that
    # builds, tests, and reviews clean is thrown away.
    refused_by = []
    for name, job in jobs.items():
        try:
            answer, spend = job.result()
        except Exception as exc:  # noqa: BLE001 - one gate failing is not the item failing
            # Said, and then counted. This used to say it and `continue`,
            # which meant a gate that died left no trace in the result:
            # the item was judged on whatever gates survived and could be
            # approved with a required check missing. A check that was
            # asked for and did not happen is `unverified` - the same
            # thing a lost verdict is - and that stops the delivery.
            unverified.append(
                f"{name}: " + blame.report(name, exc, on_event, note="could not finish")
            )
            continue

        if name == "reviewer":
            run.spend(spend)
            if on_gate:
                on_gate(item, name, answer["approved"], answer["reason"])
            noticed += [f"reviewer: {w}" for w in (answer.get("noticed") or [])]
            if not answer["approved"]:
                refusals.append(answer["reason"])
                refused_by.append(name)
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
            noticed += [
                f"critic: {w}" for w in (getattr(answer, "noticed", None) or [])
            ]
            if not answer.verified:
                # The check was required, was attempted, and did not
                # finish. Not a refusal - there is nothing for the
                # engineer to fix - and not an approval either.
                unverified.append(f"{name}: {answer.failed}")
            elif not answer.approved:
                refusals.append(answer.reason)
                refused_by.append(name)

    return _with_the_usual_cause("\n\n".join(refusals)), refused_by, unverified, noticed


# Complaints that have cost this crew more than one attempt because the
# engineer could read the complaint and still not know what to change. Each
# of these is a defect somebody has to look at the page to see, so the
# engineer never sees it - it is told, and told again, and the telling is
# the only thing it has. Where there is one usual cause, it goes with the
# complaint rather than being left to be rediscovered.
USUAL_CAUSE = (
    (
        (
            "clipped",
            "cut off",
            "runs off",
            "overflow",
            "off the edge",
            "off the screen",
            "wider than the viewport",
        ),
        (
            "The page is wider than the screen it is on. There are three "
            "usual causes and it is nearly always the first: a full-bleed "
            "band built with `width: 100vw` and `left: 50%; transform: "
            "translateX(-50%)`, where 100vw includes the scrollbar and the "
            "50% resolves against the padded content column rather than the "
            "viewport - use a grid with a full-width track instead and take "
            "`grid-column: full`. Then display type at a fixed `rem` size, "
            "which does not fit a 390px phone - use `clamp()`. Then a grid "
            "whose columns never collapse. Find which one it is by width, "
            "not by reading: the element whose box is wider than the "
            "viewport is the one at fault, and everything inside it "
            "inherits the problem."
        ),
    ),
    (
        ("contrast", "unreadable", "invisible", "same colour as", "on black"),
        (
            "Text with no colour of its own takes the page's, and the page's "
            "is for the other ground. A section that inverts has to set "
            "`color` on itself, not on the few elements somebody remembered."
        ),
    ),
)


#: The desks a line of `unverified` or `noticed` can be attributed to.
#: Anything else is not a station and must not be shown as one.
GATES = ("verifier", "inspector", "reviewer", "critic")


def _station_of(line: str, fallback: str = "critic") -> str:
    """Which station a `station: what it said` line came from.

    The fallback is the critic because it is the only gate that was ever
    reported here, and a line written before the tagging existed is its.
    """
    who = line.split(":", 1)[0].strip().lower()
    return who if who in GATES else fallback


def _with_the_usual_cause(refusal: str) -> str:
    """A refusal, plus what it usually turns out to be."""
    if not refusal:
        return refusal
    low = refusal.lower()
    for words, cause in USUAL_CAUSE:
        if any(word in low for word in words):
            refusal += f"\n\nWhat that usually is: {cause}"
    return refusal


def _verification_commands(where: Path) -> dict:
    chain = detect(where)
    return {
        "build": chain.build_command,
        "tests": chain.test_command,
        "has_tests": chain.has_tests,
    }


def _one_item(
    where: Path,
    main: Repo,
    run,
    item,
    engine: str,
    model: str,
    policy: Policy,
    per_item: float,
    on_event,
    on_gate,
    should_stop=None,
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
    # And the pictures, if the complaint was about what the page looked
    # like. Being told was the only thing the engineer had: twice in one
    # run it read a sentence about a photograph, changed something else,
    # and was told the same thing again. Both times the pictures existed
    # and were deleted before it could have opened them.
    looked = here.path / OUR_LOOK
    pictures = (
        "\n\nTwo pictures of the page as that attempt left it are in "
        f"`{OUR_LOOK}/`: desktop.png and phone.png. Open them before "
        "you change anything. The complaint is about what is in those "
        "images, and reading them is the difference between fixing it and "
        "guessing at it."
        if earlier and any(looked.glob("*.png"))
        else ""
    )
    failure = (
        f"This item was attempted before and sent back. What was said:\n\n"
        f"{earlier}\n\nNothing from that attempt is on disk - it was thrown "
        "away - so you are starting from a clean tree. Start by working out "
        "what the complaint is about, because it is the same item and the "
        f"same complaint is waiting.{pictures}"
        if earlier
        else ""
    )
    attempt, result = 1, None
    # Restarts for a worker that was taken away rather than one that
    # failed. Bounded, because a worker that cannot stay up twice running is
    # a machine problem and looping on it burns the run instead of
    # reporting it - but not one, because this has happened three times on
    # one item in an afternoon and each time the item itself was fine.
    revived, REVIVALS = 0, policy.revivals
    # One question per item. A loop in which the engineer and the planner
    # talk until they agree has no bound on it, and the thing being settled
    # is usually one sentence.
    settled = ""

    while attempt <= policy.attempts:
        # Before a worker is started, not after it has finished. Starting
        # one costs the whole of its clock whatever happens to the result.
        if _stopping(should_stop):
            here.discard()
            return _stopped_here(
                item,
                attempt - 1,
                "the run was stopped before this attempt started",
            ), None
        try:
            report, usage = work(
                where,
                # The brief, not this run's instruction. An item is worked
                # on three jobs after the one that said what the thing is,
                # and "carry on" told the engineer nothing about it.
                run.as_briefed,
                item,
                detect(where).build_command,
                run.handoff,
                failure,
                run.skills_loaded,
                on_event,
                budget=min(run.left, per_item) if run.budget else per_item,
                engine=engine,
                model=model,
                direction=run.direction,
                policy=policy,
                # Only an item that renders something, and bounded per
                # item rather than per tree: items run one after another
                # in the same directory, so a tally kept by directory
                # would let the first item spend the last one's looks.
                can_look=_worth_a_look(item),
                look_key=f"{run.id}-item{item.id}",
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
        # A worker that was taken away while the run is stopping was taken
        # away on purpose. Restarting it is how an external kill became a
        # way of extending the run rather than ending it: the signal was
        # read as "this attempt does not count", and another twelve
        # minutes began.
        if report.get("died") and _stopping(should_stop):
            here.discard()
            return _stopped_here(
                item, attempt, "the run was stopped while this was running"
            ), None

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

        commands = _verification_commands(where)
        build = commands["build"]
        if item.verify_with == "build" and (build or commands["tests"]):
            if commands["has_tests"] and build == commands["tests"]:
                build = ""
            verdict = verify_build(where, build)
        else:
            verdict = verify(
                where, item.verify_with, run.verification_baseline, commands
            )

        refusal = ""
        unverified: list[str] = []
        # The engineer's own, first: what it saw outside its scope and
        # left alone, which is the thing the scope rule asks it to report
        # rather than fix.
        noticed = [f"engineer: {w}" for w in (report.get("noticed") or [])]
        if verdict.passed:
            diff = here.pending()
            report_card = look(
                diff,
                allow_removals=item.removes_tests,
                repo=where,
                # Scope, as a fact about which files were touched. The
                # reviewer used to be asked this and could not answer it:
                # it is handed a diff and no repository.
                files=item.files,
            )
            if on_gate:
                on_gate(item, "inspector", report_card.clean, report_card.reason)
            if not report_card.clean:
                refusal = report_card.reason
                refused_by = ["inspector"]
            elif _stopping(should_stop):
                # The build ran and the inspector read the diff - both are
                # code and both are free. The two opinions are model calls,
                # and spending them on work that is about to be thrown
                # away is the cost this check exists to avoid.
                here.discard()
                return _stopped_here(
                    item, attempt, "the run was stopped before this was reviewed"
                ), None
            else:
                refusal, refused_by, unverified, from_gates = _judge(
                    here,
                    where,
                    run,
                    item,
                    diff,
                    report,
                    policy,
                    engine,
                    model,
                    on_event,
                    on_gate,
                )
                noticed += from_gates

        # The one place a judgement may be overruled by arithmetic.
        #
        # An item that builds, holds its test count, comes through the
        # inspector clean and does what the item said - and is refused on
        # the last attempt only by somebody looking at a picture - used to
        # be thrown away, and everything waiting on it with it. One run
        # ended at five of twelve that way: a missing footer took six
        # items nobody ever attempted.
        #
        # The gates are not worth the same and this program says so
        # everywhere else: measured, then checked, then seen. So on the
        # last attempt the weakest claim stops being a veto and becomes
        # what it always was - something true that somebody should know.
        # It is kept with the item, reported, and reaches `/qa` as well.
        #
        # Only the critic, only alone, and only on the last attempt. The
        # verifier and the inspector are arithmetic and keep their veto
        # outright; the reviewer read the item against the diff, which is
        # a stronger claim than a picture.
        outstanding = ""
        if (
            refusal
            and verdict.passed
            and refused_by == ["critic"]
            and attempt >= policy.attempts
        ):
            outstanding, refusal = refusal, ""
            if on_event:
                on_event(
                    "critic",
                    "kept, with what I said against it: this was the last "
                    "attempt and nothing but the look was wrong",
                )

        # A check that was required and could not be completed stops the
        # delivery. Not a refusal: there is nothing for the engineer to
        # fix and another attempt would render the same page and lose the
        # same verdict, so this does not spend one. The work is thrown
        # away because nothing may be committed that the gates could not
        # agree on, and the item is reported as unverified with the real
        # error under the station that hit it.
        if verdict.passed and unverified:
            # Under whoever hit it. Hardcoded "critic" here was right
            # while the critic was the only gate that could report one,
            # and became a lie the moment a gate that died anywhere else
            # started arriving as unverified too.
            said = "; ".join(unverified)
            if on_gate:
                on_gate(item, _station_of(unverified[0]), False, said)
            here.discard()
            return ItemResult(
                item=item,
                outcome=Outcome.BLOCKED,
                attempts=attempt,
                note=(
                    "a required check could not be completed, so this was "
                    "not delivered: " + said
                ),
                noticed=noticed,
            ), None

        if verdict.passed and not refusal:
            # Before the commit, not after: `commit` runs `add -A`, and the
            # pictures left for the engineer are untracked files sitting in
            # the tree. Swept here they never reach one.
            here.sweep()
            commit = here.commit(f"{item.id}. {item.title}\n\n{report['summary']}")
            return ItemResult(
                item=item,
                outcome=Outcome.DONE if commit else Outcome.BLOCKED,
                attempts=attempt,
                files_changed=report.get("files_changed", []),
                checks=[verdict.check],
                note=(
                    f"{verdict.reason}\n\nKept with this against it, from the "
                    f"last look: {outstanding}"
                    if commit and outstanding
                    else verdict.reason
                    if commit
                    else "the worker made no changes"
                ),
                outstanding=outstanding,
                # Said by somebody and true, whether or not it stopped
                # anything. The run record is where it has to live: a
                # finding kept in a worker's transcript is a finding
                # nobody will ever read.
                noticed=noticed,
                commit=commit,
            ), commit

        why = refusal or verdict.reason

        # The same refusal twice is not an engineer that failed twice.
        #
        # An item can be written so that it cannot be done: criteria
        # that need a file the item did not authorise. The engineer
        # meets the criteria, the inspector refuses the file - rightly,
        # it is not guessing - and the second attempt walks into the
        # same wall, because nothing about the item changed between
        # them. Watched: both attempts of one run refused for the same
        # unauthorised file, eighteen minutes of engineering for a
        # verdict that was decided when the item was written.
        #
        # Measured rather than matched. Two refusals, by the station
        # that reads files rather than opinions, saying the same thing:
        # that is a defect in the plan and another attempt cannot fix
        # it. It stops here and says so, instead of spending one.
        if (
            attempt < policy.attempts
            and refused_by == ["inspector"]
            and _the_same_refusal(why, failure)
        ):
            kept = here.checkpoint(f"item {item.id}: {item.title}")
            here.discard()
            return ItemResult(
                item=item,
                outcome=Outcome.BLOCKED,
                attempts=attempt,
                checks=[verdict.check],
                note=(
                    "this item cannot be done as written, so a second "
                    "attempt was not spent on it. The same check refused "
                    "the same thing twice and nothing about the item "
                    "changed in between, which makes it the plan's fault "
                    "rather than the engineer's. What it said:\n\n"
                    f"{why}\n\n"
                    "The item's criteria ask for something its file list "
                    "does not allow. Change one of them and run it again."
                ),
                noticed=noticed,
                checkpoint=kept,
            ), None

        if attempt == 2:
            # Before it goes, so it can be looked at afterwards. The work
            # is still thrown away; a refused item has to cost nothing.
            kept = here.checkpoint(f"item {item.id}: {item.title}")
            here.discard()
            return ItemResult(
                item=item,
                outcome=Outcome.REVERTED,
                attempts=2,
                checks=[verdict.check],
                note=why,
                noticed=noticed,
                checkpoint=kept,
            ), None

        failure = why if refusal else f"{verdict.reason}\n\n{verdict.check.detail}"
        attempt += 1

    return result, None


def _accept_candidate(repo, run, result, previous, base, *, cherry_pick=False):
    """Verify one provisional commit on the run branch before accepting it."""
    candidate = result.commit
    verdict = None
    try:
        if not candidate:
            repo.require_checkout(run.branch, previous)
            return result

        if cherry_pick:
            repo.require_checkout(run.branch, previous)
            ok, picked = repo.take(candidate)
            if not ok:
                repo.require_checkout(run.branch, previous)
                result.outcome = Outcome.REVERTED
                result.commit = None
                result.note = f"the change could not be integrated:\n{picked}"
                return result
            candidate = picked

        repo.require_checkout(run.branch, candidate)
        repo.require_parent(candidate, previous)
        verdict = verify(
            repo.path, result.item.verify_with, base, _verification_commands(repo.path)
        )
        repo.require_checkout(run.branch, candidate)
        if verdict.passed:
            result.commit = result.verified_commit = candidate
            result.tests_run = verdict.tests_run
            result.note = verdict.reason
        else:
            repo.restore_tip(run.branch, candidate, previous)
            result.outcome = Outcome.REVERTED
            result.commit = None
            result.note = (
                f"integrated verification of {candidate} failed: {verdict.reason}"
            )
    except (GitError, OSError) as exc:
        run.integration_error = (
            f"integration stopped: expected {run.branch} restored to {previous}, "
            f"observed candidate {candidate or '(unavailable)'}; {exc}"
        )
        result.outcome = Outcome.BLOCKED
        result.commit = None
        result.note = run.integration_error
    if verdict is not None:
        result.checks = verdict.checks
    return result


def _work_a_wave(
    repo: Repo,
    repo_path: Path,
    run,
    items: list,
    engine: str,
    model: str,
    policy: Policy,
    per_item: float,
    on_event,
    on_gate,
    should_stop=None,
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
    at = repo.require_checkout(run.branch)
    base = run.verification_baseline
    if len(items) == 1:
        result, _commit = _one_item(
            repo_path,
            repo,
            run,
            items[0],
            engine,
            model,
            policy,
            per_item,
            on_event,
            on_gate,
            should_stop,
        )
        return {items[0].id: _accept_candidate(repo, run, result, at, base)}

    trees: dict[int, Path] = {}
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
                    policy,
                    per_item,
                    on_event,
                    on_gate,
                    should_stop,
                )
                for item in items
            }
        for item in items:
            try:
                done[item.id] = jobs[item.id].result()
            except Exception as exc:  # noqa: BLE001 - one item failing is not the wave failing
                # "the worker stopped: ..." reads as the worker's doing,
                # and for a killed process it is. For a `TypeError` of
                # ours it is not, and that one is nobody's to find unless
                # the traceback is printed and the line is named.
                done[item.id] = (
                    ItemResult(
                        item=item,
                        outcome=Outcome.BLOCKED,
                        note="the worker stopped: "
                        + blame.report("engineer", exc, on_event),
                    ),
                    None,
                )

        out: dict[int, ItemResult] = {}
        for item in items:
            result, _ = done[item.id]
            result = _accept_candidate(repo, run, result, at, base, cherry_pick=True)
            out[item.id] = result
            if run.integration_error:
                break
            if result.verified_commit:
                at = result.verified_commit
                base.tests_run = max(base.tests_run, result.tests_run)
        return out
    finally:
        for where in trees.values():
            # The server first, then the directory it was serving. A
            # preview started in a worktree outlived it: the tree was
            # removed and the dev server carried on, holding a deleted
            # directory, still on its port, still written down in the
            # roster - so the next look at that project found a preview
            # that answers and serves whatever it last built.
            _no_longer_serving(where)
            repo.drop_worktree(where)


def execute(
    run: Run,
    stop_after: int | None = None,
    per_item: float = 2.5,
    engine: str = "claude",
    model: str = "opus",
    skills=None,
    on_event=None,
    on_item=None,
    should_stop=None,
    on_gate=None,
    policy: Policy | None = None,
) -> Run:
    # No policy named means the one this program has always used. A
    # default that changes under somebody is not a default.
    policy = policy or of(None)
    repo_path = Path(run.repo)
    repo = Repo(repo_path)

    if run.integration_error:
        raise GitError(run.integration_error)

    expected = run.expected_tip
    if expected:
        # Resuming: the branch has to be exactly where it was left, not
        # wherever a checkout -B would happily put it. Sweeping and
        # re-branching are for a run that has never touched this repository;
        # a run picking up pending work must not run either.
        repo.require_checkout(run.branch, expected)
    else:
        # No anchor recorded, but a run with results or a branch that
        # already exists is not new - it is an older record missing the
        # anchor this check relies on. Treating it as new would sweep and
        # re-branch over an accepted branch, moving it off the commit it
        # was last accepted at. Refused before any mutation, not just the
        # checkout -B that used to make the move.
        if run.results or repo.branch_exists(run.branch):
            raise GitError(
                f"{run.branch} already exists or {run.repo} has recorded "
                "results for this run, but no anchor commit was found to "
                "resume from. This looks like a run saved before resuming "
                "kept an anchor commit - it cannot be resumed safely."
            )
        repo.sweep()
        # After the sweep, so drydock's own leftovers are not what gets
        # committed, and before the cleanliness check, because a repository
        # with no commits has every file in it showing as untracked - which
        # read as a dirty tree and refused the run for the wrong reason.
        repo.start_history()
        if not repo.is_clean():
            raise DirtyTree(
                f"{repo_path} has uncommitted changes. The crew needs a clean tree so "
                "that reverting an item removes exactly what the item did."
            )
        repo.branch(run.branch)
        # Before any worker can write to this branch, so a run resumed later
        # has something real to compare the branch against.
        run.anchor = repo.require_checkout(run.branch)
        run.save()
    run.skills_loaded = skills
    landed = {r.item.id for r in run.results if r.outcome.value == "done"}

    failed: set[int] = set()
    # Worked out again each time round, because the plan can change under
    # this loop: an item that did not land is replaced by the pieces it
    # was split into, and a list of waves computed before that happened
    # sends the next item off to work on a foundation that no longer
    # exists. Watched happen once - item two started while the three
    # pieces standing in for item one had not been written.
    while True:
        landed = {r.item.id for r in run.results if r.outcome.value == "done"}
        waves = [
            w
            for w in plan_waves(run.plan.items, landed)
            if any(i.id not in judged(run) for i in w.items)
        ]
        if not waves:
            break
        wave = waves[0]
        # Everything in this wave that is already written off, skipped
        # rather than attempted against a foundation that is not there.
        wave = Wave(
            items=[i for i in wave.items if i.id not in judged(run)], why=wave.why
        )
        if not wave.items:
            continue
        if _stopping(should_stop):
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

        try:
            results = _work_a_wave(
                repo,
                repo_path,
                run,
                wave.items,
                engine,
                model,
                policy,
                per_item,
                on_event,
                on_gate,
                should_stop,
            )
        except GitError as exc:
            run.integration_error = str(exc)
            run.save()
            raise

        for item in wave.items:
            result = results.get(item.id)
            if result is None:
                continue
            run.results.append(result)
            run.save()
            if on_item:
                on_item(item, result.outcome.value)
            if not run.integration_error and result.outcome in (
                Outcome.REVERTED,
                Outcome.BLOCKED,
            ):
                # One chance to be two items instead of one. An item that
                # used all its attempts is usually an item that was two or
                # three pieces of work wearing one title, and the only
                # intervention this program has evidence for is exactly
                # this one: the same site went from one item of five
                # landing to six of seven when its largest was split.
                pieces = not _stopping(should_stop) and _split_it(
                    run, item, result, engine, model, on_event, on_gate
                )
                if pieces:
                    continue
                failed.add(item.id)

        if run.integration_error:
            raise GitError(run.integration_error)

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


def _split_it(run, item, result, engine, model, on_event, on_gate) -> bool:
    """Ask the planner to break a failed item in two, and put the pieces in.

    Returns whether it was split. One level only: a piece carries a note
    saying it is one, and is never split again, so an item that genuinely
    cannot be done does not become six that cannot.
    """
    # A way to say "if this item fails, stop - do not make more work".
    # For a run somebody is watching to a fixed budget, an item that
    # quietly becomes three is the opposite of what they asked for.
    if os.environ.get("DRYDOCK_NO_SPLIT"):
        if on_event:
            on_event("planner", "splitting is off for this run")
        return False
    if any("piece of a larger one" in said for said in item.settled):
        return False

    try:
        pieces, spend = split(
            Path(run.repo),
            run.plan,
            item,
            result.note or "it did not land",
            direction=run.direction,
            next_id=max(i.id for i in run.plan.items) + 1,
            engine=engine,
            model=model,
            on_event=on_event,
        )
    except Exception as exc:  # noqa: BLE001 - a failed split is not a failed run
        if on_event:
            on_event("planner", f"could not split item {item.id}: {exc}")
        return False

    run.spend(spend)
    if not pieces:
        return False

    # Whatever was waiting for this item was waiting for the whole of it,
    # which is now the last piece.
    where = run.plan.items.index(item)
    run.plan.items[where : where + 1] = pieces
    for other in run.plan.items:
        if other in pieces:
            continue
        if item.id in other.needs:
            other.needs = sorted({*other.needs, pieces[-1].id} - {item.id})

    # The attempt that failed stays in the record - it happened, and the
    # pull request says what did not land - but the item it belonged to no
    # longer exists, so it must not be counted as a result against one of
    # the pieces.
    run.results = [r for r in run.results if r.item.id != item.id]
    run.save()

    if on_gate:
        on_gate(
            item,
            "split",
            True,
            f"tried {result.attempts} times and did not land, so it is now "
            + ", ".join(f"{p.id}. {p.plain or p.title}" for p in pieces),
        )
    return True


def judged(run) -> set[int]:
    """Every item that already has a result, however it ended."""
    return {r.item.id for r in run.results}
