"""Running a job in the background while a page watches it.

The crew is ordinary blocking code: it waits on Maven, it waits on the API. So
it runs on a thread and reports through the feed, rather than being rewritten
to be asynchronous for the benefit of one view. A thread also means the run
survives the browser being closed, which is the behaviour anyone would expect
of something that takes twenty minutes and costs money.
"""

import os
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from . import preview, probe, publish
from .analyst import baseline, survey
from .answer import ask
from .architect import as_briefing, design
from .claims import Report, check
from .commands import ALONE, STAGES
from .crew import GATE_STATION
from .critic import what_looks_wrong
from .designer import as_briefing as look_briefing
from .designer import decide, draw_mark, write_logo
from .detect import detect, installed
from .engines import stop_workers
from .events import Feed
from .inspect import look
from .intent import is_small_talk
from .memory import Memory
from .models import Inventory, Item, Plan
from .orchestrate import execute
from .pace import from_log
from .planner import plan
from .policy import AT_THE_END, Policy, of
from .repo import GitError, Repo
from .review import read_it
from .run import Run
from .settings import Settings
from .shot import take
from .skills import Skill, discover
from .skills import load as load_skill
from .stack import already_decided
from .start import begin, desk_for


def _skills_named(names: list[str]) -> list:
    """Load the installed skills with these names, as they are right now."""
    root = Path("skills")
    if not root.exists():
        return []
    installed = {s.name: s for s in discover(root)}
    return [load_skill(installed[n]) for n in names if n in installed]


# What each desk is doing when the single start call names its phase. The
# words are the station's own job, said in the present tense, because the
# room shows one worker moving through four of them rather than four
# workers queueing.
STEP = {
    "Analyst": "reading the repository",
    "Architect": "deciding what this is made of",
    "Designer": "deciding how it should look",
    "Planner": "turning it into items",
}


#: Who the loop names when it says something, and whose desk that is. The
#: loop talks in lowercase station names; the office is keyed by the desk.
#: Anything unrecognised is the engineer's, because the engineer is what
#: the loop mostly is.
DESKS = {
    "critic": "Critic",
    "reviewer": "Reviewer",
    "inspector": "Inspector",
    "verifier": "Verifier",
    "planner": "Planner",
    "engineer": "Engineer",
}


class Session:
    def __init__(
        self,
        repo: Path,
        task: str,
        skills: list[Skill],
        budget: float = 0.0,
        engine: str = "claude",
        model: str = "opus",
        stop_after: str = "planner",
        standing: str = "",
        # Why this job was not allowed to be done cheaply, when it was not.
        # Carried rather than re-derived: the sentence that raised it is
        # the only thing that makes the raise arguable.
        floor: str = "",
        policy: Policy | None = None,
        # How long this run is allowed, in minutes. Zero is no deadline,
        # which is the default and what every run had until now.
        within_minutes: float = 0.0,
    ) -> None:
        self.feed = Feed()
        self.feed.also(self._write_log)
        self.repo = repo
        self.task = task
        self.skills = skills
        self.budget = budget
        self.engine = engine
        self.model = model
        # How far down the line this job goes. The stations before it always
        # run, so nothing downstream is ever asked to speak about a repository
        # nobody has read.
        self.stop_after = stop_after
        self.floor = floor
        # Whether a person has actually been asked for something. It used
        # to be worked out from "there is a plan and the run has not
        # stopped", which is true of every run that got as far as
        # planning - so a job that was never going to ask reported itself
        # as waiting for an answer for the whole of its life, and the one
        # that went straight to the work reported it loudest.
        self.waiting = False
        # How much ceremony this job gets. Decided once, here, and carried
        # rather than re-derived anywhere downstream.
        self.policy = policy or of(None)
        # Whatever this person always wants true of work in this repository.
        # Appended to the task rather than mixed into the system prompt, so
        # it is visible in the run record as part of what was asked for.
        self.standing = standing.strip()
        self.stopping = False
        # Set by `ends_in`, cancelled when the run finishes. None when
        # nobody gave this run a deadline, which is the default.
        self._clock: threading.Timer | None = None
        self.within_minutes = max(0.0, float(within_minutes or 0.0))
        self.memory = Memory.about(repo)
        # Some knowledge belongs to the kind of thing being built rather than
        # to the command somebody typed. Nobody types /new and then remembers
        # to ask for the design skill, and a page built without it is the
        # page this program kept producing.
        self._bring_in("web-design", when=self._has_a_face)
        self.run: Run | None = None
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self, auto_run: bool = False) -> None:
        # The clock before the thread. Everything that can start a worker
        # happens inside `_work`, so arming it here is the only ordering
        # where a deadline cannot be beaten by the first station.
        self.ends_in(self.within_minutes)
        self._thread = threading.Thread(
            target=self._work, args=(auto_run,), daemon=True
        )
        self._thread.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _write_log(self, event) -> None:
        """Keep the feed on disk as well as in memory.

        The feed is a browser's view of a run and it lives as long as the
        process does. When something goes wrong at three in the morning the
        question is what happened, and the honest answer has to come from a
        file rather than from whichever tab happened to be open.
        """
        try:
            path = Path("runs") / f"{self.run.id}.log" if self.run else None
            if path is None:
                return
            path.parent.mkdir(exist_ok=True)
            with path.open("a") as out:
                # One event per line. The sse() form ends in a blank line
                # because that is what the wire format needs, and half the
                # lines in a run log were that blank line.
                out.write(event.sse()[6:].rstrip("\n") + "\n")
        except OSError:
            # A run must not fail because its log could not be written.
            pass

    def _agent_event(self, who: str):
        def report(what: str, text: str) -> None:
            # Named `what` rather than `kind`: emit() takes the event kind as
            # its first argument, so a field called kind collides with it.
            first = text.strip().splitlines()[0] if text.strip() else ""
            self.feed.emit("agent.tool", agent=who, what=what, detail=first[:200])

        return report

    def _station_event(self):
        """Route what the loop says to the desk that said it.

        `execute` was given one closure bound to the Engineer, so every
        line it emitted was the Engineer's: the critic failing to start a
        browser, a reviewer dying mid-diff, a bug of ours in the gate
        loop. All of it landed on the Engineer's desk, in the tool log,
        under a station name only the drawer ever showed - so the Critic
        could be the station that failed and its desk sat idle and clean.

        The loop already names who is talking in its first argument. It
        is only ever used as the tool name. Used as the desk as well, the
        failure appears where somebody would go looking for it.
        """

        def report(what: str, text: str) -> None:
            self._agent_event(DESKS.get(what.strip().lower(), "Engineer"))(what, text)

        return report

    def _work(self, auto_run: bool) -> None:
        try:
            # A question is not a job. No branch, no plan, no approval, no
            # commit - and no baseline either, because nothing is going to
            # be compared against it.
            if self.stop_after == "ask":
                self._answer()
                return

            if self.stop_after == "review":
                self._review()
                return

            if self.stop_after == "qa":
                self._qa()
                return

            chain = detect(self.repo)
            # Taken before the standing instructions are appended. They hold
            # for every job here, so they are not part of what this one is
            # for, and an objective that carried them would repeat them in
            # every brief for the life of the repository.
            objective = self.memory.aim(self.task)
            self.memory.save()
            if self.standing:
                self.task = (
                    f"{self.task}\n\nStanding instructions for this repository, "
                    f"which hold for every job here:\n{self.standing}"
                )
            self.run = Run.start(self.repo, self.task, [s.name for s in self.skills])
            self.run.objective = objective
            self.run.budget = self.budget
            self.run.engine = self.engine
            self.run.model = self.model
            self.feed.emit(
                "run.started",
                repo=self.repo.name,
                task=self.task,
                # Said out loud when this job is carrying one it did not
                # type, which is the case somebody needs to be able to see.
                objective=objective if objective.strip() != self.task.strip() else "",
                objective_at=self.memory.objective_at,
                skills=[s.name for s in self.skills],
                toolchain=f"{chain.build_tool} / {chain.language}",
                stages=self._stages(),
                floor=self.floor,
            )
            if self.floor:
                self.feed.emit(
                    "policy.raised",
                    profile=self.policy.profile,
                    why=self.floor,
                    say=self.policy.say,
                )

            self.feed.emit(
                "agent.state",
                agent="Verifier",
                state="working",
                note="running the build and the suite, untouched",
            )
            self.run.baseline = baseline(self.repo, chain)
            b = self.run.baseline
            self.feed.emit(
                "baseline",
                builds=b.builds,
                tests=b.tests_run,
                failed=b.tests_failed,
                skipped=b.tests_skipped,
                green=b.green,
            )
            # The station closing its own state. The browser was doing this
            # for it, off the baseline figures, which meant the log said the
            # Verifier started and never finished - and a finished run read
            # back off that log showed it still at work.
            self.feed.emit(
                "agent.state",
                agent="Verifier",
                state="done",
                note=(
                    f"{b.tests_run} tests pass before anything is touched"
                    if b.green
                    else f"{b.tests_failed} failing before anything is touched"
                ),
            )
            self.run.save()

            if self.stop_after == "baseline":
                self._finish_early()
                return

            # One small change, straight to the work. The gates still run -
            # it is the planning and the approval that are skipped, not the
            # checking, because the checking is the point and a plan for a
            # typo is a plan nobody reads.
            #
            # Unless something raised the floor. The router reads a
            # sentence, and a short sentence about a dangerous thing looks
            # exactly like a short sentence: "fix the login password
            # hash", "change the api key handling", "drop the users table
            # and rebuild it" and "remove the old payment retry" were all
            # routed here, and all four are work the floor calls deep. The
            # floor raised the attempts and the turns for them and nothing
            # consulted it here, so each one still skipped planning,
            # acceptance criteria and the approval. The floor is the
            # conservative answer to an unclear sentence and this is where
            # it has to be read.
            if self.stop_after == "straight" and self.floor:
                self.feed.emit(
                    "plan.required",
                    why=self.floor,
                    note=(
                        "this was read as one small change, and what it "
                        "names is not work that is done without a plan"
                    ),
                )
                self.stop_after = "planner"

            if self.stop_after == "straight":
                self.run.plan = Plan(
                    summary="One change, done directly.",
                    items=[
                        Item(
                            id=1,
                            title=self.task,
                            plain=self.task,
                            rationale="Asked for directly, with no plan.",
                            files=[],
                            verify_with="tests" if b.tests_run else "build",
                        )
                    ],
                )
                self.run.save()
                for who in ("Analyst", "Architect", "Designer", "Planner"):
                    self.feed.emit(
                        "agent.state",
                        agent=who,
                        state="skipped",
                        note="not needed for one small change",
                    )
                self.feed.emit(
                    "plan.ready",
                    summary=self.run.plan.summary,
                    items=[
                        {
                            "id": 1,
                            "title": self.task,
                            "plain": self.task,
                            "verify_with": self.run.plan.items[0].verify_with,
                            "rationale": "",
                        }
                    ],
                    cost=0.0,
                    approved=True,
                )
                self.work_the_plan()
                return

            # An empty repository has nothing to survey, and a survey run
            # against one produces twenty findings that all say the same
            # thing: there are no files. That costs real money and two
            # minutes to learn what one `iterdir` already knows. So the two
            # stations are alternatives, not a sequence - one reads what is
            # there, the other decides what should be.
            empty = not any(p.name != ".git" for p in self.repo.iterdir())
            commit = Repo(self.repo).head()

            # One worker reads, decides and plans. The four stations it
            # replaced are still here behind DRYDOCK_FOUR_STATIONS, as a way
            # back if this turns out to be wrong somewhere the measurement
            # did not look.
            #
            # Measured once, same prompt, same empty folder, the only
            # difference being which of these ran:
            #
            #   one worker     8 of 8 items landed, 0 reverted
            #   four stations  0 of 8 items landed, 2 reverted
            #
            # Not faster to plan - 6.3 minutes against 5.5. What it bought
            # was a plan that could be built. Both of the four stations'
            # attempts were reverted with "there is still no way to run
            # anything in this repository": their first item was written by
            # a Planner reading the Analyst's and the Architect's prose,
            # and their own Engineer could not satisfy it twice. The one
            # worker had read the folder itself, and its first item landed
            # first time in eighty-four seconds.
            #
            # One run each. The way back is kept because of that, and
            # should be taken out once there is a second.
            if os.environ.get("DRYDOCK_FOUR_STATIONS") != "1":
                self._begin_it(empty, b, chain, auto_run, commit)
                return

            surveyed = False
            if empty:
                self.feed.emit(
                    "agent.state",
                    agent="Analyst",
                    state="skipped",
                    note="there is nothing in this repository to read",
                )
                self.run.inventory = Inventory(
                    build_tool=chain.build_tool,
                    language=chain.language,
                    test_command=chain.test_command,
                    build_command=chain.build_command,
                    source_files=0,
                    test_files=0,
                    findings=["The repository is empty. Nothing here was built on."],
                    risks=[],
                )
                self.run.save()
            elif self._already_read(commit):
                surveyed = False
            else:
                self._survey(b, chain, commit)
                surveyed = True

            if self.stop_after == "analyst":
                self._finish_early()
                return

            # The architect decides what it is built with; the designer
            # decides what it looks like. Neither answer depends on the
            # other, and the designer is the single slowest station in the
            # line - five minutes of the planner sitting idle, for nothing.
            # An empty repository needs somebody to decide what it is made
            # of - unless the person asking already did. A task that names
            # a toolchain and says it is settled has decided it, and the
            # Architect then spends a station restating it: forty-one
            # seconds on one measured run, a third of everything that run
            # spent working.
            settled = already_decided(self.task)
            wants_shape = empty and not settled
            # Already decided for this project. Deciding it again costs five
            # minutes and produces a different answer, and a project whose
            # palette changes between jobs does not have a palette.
            remembered = self.memory.direction
            wants_look = self._has_a_face() and not remembered
            shape = ""
            look = remembered

            if wants_shape:
                self.feed.emit(
                    "agent.state",
                    agent="Architect",
                    state="working",
                    note="deciding what this is made of",
                )
            elif settled:
                # What the task said, handed on in the Architect's place so
                # the planner is not left to work it out mid-plan.
                shape = (
                    "\n\nThe stack was decided by whoever asked for this, "
                    f"not here: {settled.why}. Take it as given and do not "
                    "reopen it.\n"
                )
                self.feed.emit(
                    "agent.state",
                    agent="Architect",
                    state="skipped",
                    note=f"the task already decided this - {settled.why}",
                )
            else:
                self.feed.emit(
                    "agent.state",
                    agent="Architect",
                    state="skipped",
                    note="the project already has a shape; the Analyst read it",
                )
            if wants_look:
                self.feed.emit(
                    "agent.state",
                    agent="Designer",
                    state="working",
                    note="deciding how it should look",
                )
            elif remembered:
                self.run.direction = remembered
                self.feed.emit(
                    "agent.state",
                    agent="Designer",
                    state="skipped",
                    note=f"already directed on {self.memory.directed_on}; "
                    "using what was decided then",
                )
            else:
                self.feed.emit(
                    "agent.state",
                    agent="Designer",
                    state="skipped",
                    note="nothing here is looked at by anybody",
                )

            # Three at once, and the planner started the moment the one it
            # actually depends on is done.
            #
            # Measured, before this: architect 71s and designer 5m41s ran
            # together, and the planner waited for both - 2m54s of it
            # serialised behind a station it does not need. Eight minutes
            # and thirty-six seconds before the first line of the thing
            # anybody asked for.
            #
            # The planner needs the stack: items name files and a test
            # command. It does not need the palette - the direction reaches
            # the engineer at item time through `run.direction`, which is
            # where it was always read.
            with ThreadPoolExecutor(max_workers=3) as pool:
                shaping = (
                    pool.submit(
                        design,
                        self.repo,
                        self.run.brief,
                        self.skills,
                        self._agent_event("Architect"),
                        budget=self.run.left if self.budget else 0.0,
                        engine=self.engine,
                        model=self.model,
                    )
                    if wants_shape
                    else None
                )
                looking = (
                    pool.submit(
                        decide,
                        self.repo,
                        self.run.brief,
                        "",
                        self.skills,
                        self._agent_event("Designer"),
                        budget=self.run.left if self.budget else 0.0,
                        engine=self.engine,
                        model=self.model,
                    )
                    if wants_look
                    else None
                )
                # Drawn beside the direction rather than inside it, and
                # knowing nothing about the palette: it is one colour and
                # the page decides which.
                drawing = (
                    pool.submit(
                        draw_mark,
                        self.repo,
                        self.run.brief,
                        self.skills,
                        self._agent_event("Designer"),
                        budget=self.run.left if self.budget else 0.0,
                        engine=self.engine,
                        model=self.model,
                    )
                    if wants_look
                    else None
                )

                if shaping:
                    found, usage = shaping.result()
                    self._spent(usage, "Architect")
                    shape = as_briefing(found)
                    self.feed.emit(
                        "agent.state",
                        agent="Architect",
                        state="done",
                        note=found.get("stack", "")[:90] or "shape decided",
                    )
                    self.feed.emit("design", **found)

                # Here, inside the pool, while the designer is still
                # drawing. This is the whole point of the change.
                self.feed.emit(
                    "agent.state",
                    agent="Planner",
                    state="working",
                    note="turning the survey into items",
                )
                planning = pool.submit(self._plan_it, shape, surveyed, b)

                if looking:
                    found, usage = looking.result()
                    self._spent(usage, "Designer")
                    look = look_briefing(found)
                    self.run.direction = look
                    self.memory.direct(look)
                    self.memory.save()
                    self.feed.emit(
                        "agent.state",
                        agent="Designer",
                        state="done",
                        note=found.get("idea", "")[:110] or "the look is decided",
                    )
                    self.feed.emit("look", **found)

                if drawing:
                    drawn, usage = drawing.result()
                    self._spent(usage, "Designer")
                    # Committed before the item loop can start: the loop
                    # refuses a dirty tree, so a file written here and left
                    # uncommitted would stop the job before its first item.
                    write_logo(self.repo, drawn)
                    if (drawn.get("logo_svg") or "").strip():
                        self.run.direction += look_briefing(
                            {
                                "logo_svg": drawn.get("logo_svg"),
                                "logo_reasoning": drawn.get("logo_reasoning"),
                            }
                        )

                self.run.plan, usage = planning.result()
            self._spent(usage, "Planner")
            self._after_plan(auto_run)

        except Exception as exc:  # noqa: BLE001 - the page has to be told
            self.error = f"{type(exc).__name__}: {exc}"
            self.feed.emit("run.error", detail=self.error)
        finally:
            self._stop_the_clock()

    def _what_is_already_known(self, commit: str, empty: bool = False) -> str:
        """What is already known, so nobody goes and asks for it again.

        What this repository taught the last job, and - only when there
        is nothing here to read it from - what is installed on this
        machine. A planner choosing a stack for an empty folder spent
        three round trips and about twenty seconds learning two version
        numbers; this process reads them in half a second. A planner
        reading a repository that declares its own toolchain is not told,
        because there it decides nothing.

        Only notes against the commit it is looking at: a fact about a
        tree that has since changed is not a fact.
        """
        said = []
        notes = self.memory.knows(commit)
        if notes:
            said.append(
                "What this repository taught the last job here:\n"
                + "\n".join(f"- {n}" for n in notes[:20])
            )
        if empty:
            here = installed()
            if here:
                said.append(here)
        return "\n\n".join(said)

    def _begin_it(
        self, empty: bool, b, chain, auto_run: bool, commit: str = ""
    ) -> None:
        """Read, decide and plan in one call, and tell the office which
        desk is doing which part as it goes.

        The desks are not inferred. The worker names the phase it is
        starting by running a command, so what the room shows is something
        that was reported rather than something that was guessed - which is
        the distinction this program keeps getting wrong in the other
        direction.
        """
        looked_at = self._has_a_face()
        remembered = self.memory.direction

        def report(what: str, text: str) -> None:
            desk = desk_for(text) or desk_for(what)
            if desk:
                # The old desk goes dark before the new one lights. One
                # worker is at one desk; two lit at once says two workers,
                # which is the thing this change exists to stop saying.
                for other in list(self._lit):
                    if other != desk:
                        self.feed.emit(
                            "agent.state",
                            agent=other,
                            state="done",
                            note="done, in the same sitting",
                        )
                        self._lit.discard(other)
                self.feed.emit(
                    "agent.state", agent=desk, state="working", note=STEP[desk]
                )
                self._lit.add(desk)
            first = text.strip().splitlines()[0] if text.strip() else ""
            self.feed.emit(
                "agent.tool", agent=desk or "Planner", what=what, detail=first[:200]
            )

        self._lit = set()
        if remembered:
            self.feed.emit(
                "agent.state",
                agent="Designer",
                state="skipped",
                note=f"already directed on {self.memory.directed_on}; "
                "using what was decided then",
            )
        elif not looked_at:
            self.feed.emit(
                "agent.state",
                agent="Designer",
                state="skipped",
                note="nothing here is looked at by anybody",
            )

        # Asked for once and used twice: to tell the worker whether to
        # direct a look, and to decide afterwards whether what came back
        # in that field is one.
        wanted_a_look = looked_at and not remembered

        # And a mark, drawn beside the reading rather than after it. This
        # was written when the four stations were still the default and
        # was never called from here - so every job that went down this
        # path built a site with no mark at all, and the capability sat in
        # the module being dead code.
        #
        # It is drawn whenever anybody is going to look at the result, not
        # only when a look is being directed: a project that already has a
        # direction and no mark still has no mark.
        drawing = None
        if looked_at and not (self.repo / "brand" / "logo.svg").exists():
            drawing = ThreadPoolExecutor(max_workers=1).submit(
                draw_mark,
                self.repo,
                self.run.brief,
                self.skills,
                self._agent_event("Designer"),
                budget=self.run.left if self.budget else 0.0,
                engine=self.engine,
                model=self.model,
            )

        started, usage = begin(
            self.repo,
            # The brief, not this instruction. A plan written against
            # "carry on" is twelve items about nothing.
            self.run.brief,
            empty=empty,
            looked_at=wanted_a_look,
            known=self._what_is_already_known(commit, empty=empty),
            skills=self.skills,
            on_event=report,
            budget=self.run.left if self.budget else 0.0,
            engine=self.engine,
            model=self.model,
        )
        self._spent(usage, "Planner")

        for desk in self._lit:
            self.feed.emit(
                "agent.state",
                agent=desk,
                state="done",
                note="done, in the same sitting",
            )
        self._lit = set()

        self.run.inventory = started.inventory(chain)

        # The request written out, and what was read into it that nobody
        # said. Stored beside the request rather than folded into it: the
        # request is what the work is judged against, and a reading is
        # enforced as hard as a requirement the moment the two are one
        # piece of text. Both are shown before anything is approved.
        self.run.expanded = started.brief
        self.run.assumptions = list(started.assumptions)

        # Only when a look was asked for. `direction` is a required field,
        # so a worker told not to direct one still has to put something in
        # it - and what it puts there is a paragraph explaining why it is
        # not directing. That paragraph was being used as the direction
        # for the whole run and then written over the real one in memory.
        #
        # Watched happen: a restaurant had seven and a half thousand
        # characters of art direction from its first job - who walks in,
        # the plaster walls, the linen, the 5:30 seating that is the
        # market in that town - and its second job replaced all of it with
        # "No look is being directed", permanently. The pages built after
        # that are correct, tested, and visually dead, because nothing
        # told the engineers what the thing was supposed to look like.
        directed = started.direction if wanted_a_look else ""
        self.run.direction = directed or remembered
        if directed:
            self.memory.direct(directed)
            self.memory.save()
            self.feed.emit("look", idea=directed[:400])
        # The mark, before anything is planned against it: the briefing
        # tells the engineers it is there, and the item loop refuses a
        # dirty tree, so it has to be committed by now or not written.
        if drawing is not None:
            try:
                drawn, spent = drawing.result()
                self._spent(spent, "Designer")
                if write_logo(self.repo, drawn):
                    self.run.direction += look_briefing(
                        {
                            "logo_svg": drawn.get("logo_svg"),
                            "logo_reasoning": drawn.get("logo_reasoning"),
                        }
                    )
                    self.feed.emit(
                        "agent.state",
                        agent="Designer",
                        state="done",
                        note="the mark is drawn and committed",
                    )
            except Exception as exc:  # noqa: BLE001 - a mark is not the job
                self.feed.emit(
                    "agent.state",
                    agent="Designer",
                    state="done",
                    note=f"no mark was drawn: {exc}",
                )

        self.run.plan = started.plan
        self.run.save()

        # Whether anybody is stopped to look at this. Asked of the one that
        # read the repository, because it is the only thing here that knows
        # what the change actually touches - the router only ever saw the
        # sentence.
        #
        # Three things can insist on being shown, and none of them can be
        # argued out of it: a floor raised under risky work, a plan of more
        # than one item, and the worker saying so itself. What is left -
        # one change, read and judged small by something that looked - goes
        # straight to the work, which is what happens when you ask anybody
        # else to change a word on a page.
        straight = (
            not self.floor and not started.needs_a_plan and len(started.plan.items) <= 1
        )
        if straight:
            self.feed.emit(
                "plan.skipped",
                why=started.why_that or "one change, and nothing it depends on",
            )
        self._after_plan(auto_run or straight)

    def _plan_it(self, shape: str, surveyed: bool, b):
        """The planner, as a thing that can be handed to a pool.

        Given the shape and not the direction. It needs to know what this
        is built with, because its items name files and a test command;
        what the thing looks like reaches the engineer at item time, which
        is where it was always read from.
        """
        return plan(
            self.repo,
            self.run.brief,
            self.run.inventory,
            b,
            self.skills,
            self._agent_event("Planner"),
            budget=self.run.left if self.budget else 0.0,
            engine=self.engine,
            model=self.model,
            shape=shape,
            policy=self.policy,
            surveyed=surveyed,
        )

    def _bring_in(self, name: str, when) -> None:
        """Add a skill nobody asked for, when the work calls for it."""
        if any(s.name == name for s in self.skills):
            return
        try:
            if not when():
                return
        except OSError:
            return
        root = Path("skills")
        here = (
            next((s for s in discover(root) if s.name == name), None)
            if root.exists()
            else None
        )
        if here:
            self.skills = [*self.skills, load_skill(here)]

    def _spent(self, usage, who: str) -> None:
        """Record what a station cost and say so immediately.

        The page used to show $0.00 for the whole of the first two minutes,
        because the figure was only sent with the plan. Money was being spent
        the entire time, and a number that is wrong while looking precise is
        worse than no number.
        """
        self.run.spend(usage)
        self.run.save()
        self.feed.emit("spend", cost=round(self.run.cost, 2), who=who)

    # Words that mean somebody is going to look at this. Matched on word
    # boundaries, because "ui" sits inside "suite" and a JUnit migration was
    # being sent to a designer.
    FACES: ClassVar[re.Pattern] = re.compile(
        r"\b(web ?site|site|web ?page|page|landing|web ?app|app|ui|ux|"
        r"frontend|front-end|dashboard|portal|blog|shop|storefront|"
        r"interface|home ?page|marketing)\b"
    )

    def _has_a_face(self) -> bool:
        """Whether this job produces something a person looks at.

        A parser, a migration or a CLI does not need a palette, and asking
        for one costs a minute and produces an answer nobody reads.
        """
        if self.FACES.search(self.task.lower()):
            return True
        # An existing repository that already serves pages has a face whether
        # or not the request mentions one.
        return any(
            (self.repo / name).exists()
            for name in ("public", "static", "views", "templates", "src/pages")
        )

    def _stages(self) -> list[str]:
        """Which stations this job reaches.

        Not every job walks the line. `/ask` answers and leaves; `/fix` does
        one change with no planning. Indexing STAGES by the stopping point
        assumed it always did, and raised on anything that does not appear
        there - which took the whole run down on the first /fix.
        """
        if self.stop_after in ALONE:
            return [self.stop_after]
        if self.stop_after == "straight":
            return ["baseline", "engineer"]
        return STAGES[: STAGES.index(self.stop_after) + 1]

    def _qa(self) -> None:
        """Run it, look at it, report. Nothing is touched.

        The order is from cheapest and most certain to least: the suite is
        arithmetic, what the server serves is one request, what the browser
        can see is a measurement, and only the claims need a model - and
        the model's answer is checked against the page afterwards.
        """
        self.run = Run.start(self.repo, self.task, [])
        self.run.budget = self.budget
        self.run.engine = self.engine
        self.run.model = self.model
        chain = detect(self.repo)

        self.feed.emit(
            "run.started",
            repo=self.repo.name,
            task=self.task,
            skills=[],
            toolchain=f"{chain.build_tool} / {chain.language}",
            stages=["qa"],
        )

        # 1. The suite, untouched. Zero passing tests is green and proves
        # nothing, which is why the number is always said.
        self.feed.emit(
            "agent.state",
            agent="Verifier",
            state="working",
            note="building it and running the suite",
        )
        b = baseline(self.repo, chain)
        self.run.baseline = b
        self.feed.emit(
            "agent.state",
            agent="Verifier",
            state="done" if b.builds and not b.tests_failed else "failed",
            note=f"{b.tests_run} tests, {b.tests_failed} failing"
            if b.tests_run or b.tests_failed
            else "no suite to run",
        )

        # 2. Start it, and ask what it actually serves. Answering on a port
        # and serving a page are two different facts.
        self.feed.emit(
            "agent.state",
            agent="Critic",
            state="working",
            note="starting it and looking at it",
        )
        seen, served, widths, pressed = None, None, {}, []
        try:
            live = preview.running(self.repo) or preview.start(self.repo)
        except (LookupError, RuntimeError, TimeoutError) as exc:
            live = None
            serving = str(exc)
        else:
            served = preview.what_it_serves(live.url)
            serving = f"{live.url} answered {served.said}"
            # 3. What the browser knows, at both widths.
            if served.is_a_page:
                for width in (390, 1440):
                    widths[width] = probe.look(live.url, width)
                seen = widths.get(1440) or widths.get(390)
                # And press what is safe to press. It establishes that a
                # control does something, never that it did the right
                # thing - that needs somebody to have said what the right
                # thing was, which is what the claims are for.
                self.feed.emit(
                    "agent.state",
                    agent="Critic",
                    state="working",
                    note="pressing what is safe to press",
                )
                pressed = probe.press(live.url, 1440)

        # 4. Only now a model, and only on what was claimed.
        wanted = [c for c in self._claims() if c.strip()]
        report = Report()
        if wanted and seen is not None and seen.ran:
            report, usage = check(
                self.repo,
                wanted,
                seen,
                pressed,
                on_event=self._agent_event("Critic"),
                budget=self.run.left if self.budget else 0.0,
                engine=self.engine,
                model=self.model,
            )
            self._spent(usage, "Critic")

        broken = sorted(
            {f for one in widths.values() for f in one.findings()}
            # A control that throws, or does nothing, or cannot be reached
            # is a finding about the page like any other. Left out of here
            # it showed only in the list of what was pressed, which is a
            # place somebody has to open.
            | {one.wrong for one in pressed if one.wrong}
        )

        # Last, and least certain: somebody looking. It is given what was
        # already measured and told to leave all of it alone, because an
        # eye asked about contrast will guess, and a guess dressed as a
        # second opinion is worse than silence.
        noticed: list[str] = []
        if served and served.is_a_page and live is not None:
            self.feed.emit(
                "agent.state", agent="Critic", state="working", note="looking at it"
            )
            with tempfile.TemporaryDirectory(prefix="drydock-qa-") as scratch:
                if take(live.url, Path(scratch)):
                    try:
                        noticed, dollars = what_looks_wrong(
                            Path(scratch),
                            broken,
                            model=self.model,
                            on_event=self._agent_event("Critic"),
                        )
                        self.run.dollars += dollars
                    except Exception as exc:  # noqa: BLE001 - a look is not a run
                        self.feed.emit(
                            "agent.state",
                            agent="Critic",
                            state="done",
                            note=f"could not look: {exc}",
                        )
        self.feed.emit(
            "agent.state",
            agent="Critic",
            state="failed" if broken else "done",
            note=f"{len(broken)} found" if broken else "nothing to report",
        )
        self.feed.emit(
            "qa",
            serving=serving,
            page=bool(served and served.is_a_page),
            builds=b.builds,
            tests=b.tests_run,
            failing=b.tests_failed,
            broken=broken,
            noticed=noticed,
            pressed=[
                {"said": one.said, "did": one.why or one.did, "tried": one.tried}
                for one in pressed
            ],
            unchecked=[one.error for one in widths.values() if one.error],
            checks=[
                {
                    "claim": c.claim,
                    "verdict": c.verdict,
                    "evidence": c.evidence,
                    "why": c.why,
                }
                for c in report.checks
            ],
            said=report.say,
        )
        self.run.save()
        self.feed.close()

    def _claims(self) -> list[str]:
        """What this was supposed to do, if anybody said.

        Whatever was typed after the command, a line at a time. Failing
        that, the plain sentences of the last plan run here - which is
        what somebody already approved and is the nearest thing to a
        specification this program has.
        """
        typed = [
            line.strip(" -\t")
            for line in (self.task or "").splitlines()
            if line.strip(" -\t")
        ]
        # The task template for /qa is whatever was typed, so anything
        # here that is not the command's own words is a claim.
        if typed and not typed[0].lower().startswith(
            ("run it", "report the health", "review what")
        ):
            return typed[:12]

        try:
            for past in sorted(Path("runs").glob("*.json"), reverse=True)[:20]:
                run = Run.model_validate_json(past.read_text())
                if Path(run.repo) != self.repo or not run.plan:
                    continue
                said = [
                    i.plain or i.title for i in run.plan.items if i.plain or i.title
                ]
                if said:
                    return said[:12]
        except (OSError, ValueError):
            pass
        return []

    def _review(self) -> None:
        """Read what has changed and report. Nothing is touched.

        No branch, no plan, no approval, no commit - the same shape as a
        question, because that is what this is: a question about a diff
        somebody already wrote.
        """
        self.run = Run.start(self.repo, self.task, [])
        self.run.budget = self.budget
        self.run.engine = self.engine
        self.run.model = self.model
        repo = Repo(self.repo)
        diff, about = repo.what_changed()

        self.feed.emit(
            "run.started",
            repo=self.repo.name,
            task=self.task,
            skills=[],
            toolchain="",
            stages=["review"],
        )

        if not diff.strip():
            self.feed.emit(
                "agent.state", agent="Inspector", state="skipped", note=about
            )
            self.feed.emit(
                "review", verdict=about, findings=[], good=[], counted=[], about=about
            )
            self.feed.close()
            return

        # Arithmetic first, because it costs nothing and does not hedge.
        self.feed.emit(
            "agent.state",
            agent="Inspector",
            state="working",
            note="counting what the diff removed",
        )
        card = look(diff, repo=self.repo)
        counted = [f.detail for f in card.findings]
        self.feed.emit(
            "agent.state",
            agent="Inspector",
            state="done" if card.clean else "failed",
            note="nothing to report" if card.clean else f"{len(counted)} found",
        )

        self.feed.emit(
            "agent.state", agent="Reviewer", state="working", note="reading the change"
        )
        reading, usage = read_it(
            self.repo,
            diff,
            # What they typed, with what is being read. "review my changes,
            # the error handling especially" became "review what has
            # changed" and the second half went nowhere.
            f"{about}\n\n{self.task}".strip() if self.task.strip() else about,
            counted,
            on_event=self._agent_event("Reviewer"),
            budget=self.run.left if self.budget else 0.0,
            engine=self.engine,
            model=self.model,
        )
        self._spent(usage, "Reviewer")
        self.feed.emit(
            "agent.state",
            agent="Reviewer",
            state="done",
            note=f"{len(reading.findings)} found"
            if reading.findings
            else "nothing to report",
        )
        self.run.answer = reading.verdict
        self.run.save()
        self.feed.emit(
            "review",
            about=about,
            verdict=reading.verdict,
            findings=[
                {"where": f.where, "what": f.what, "sure": f.sure}
                for f in reading.findings
            ],
            good=reading.good,
            counted=counted,
        )
        self.feed.close()

    def _answer(self) -> None:
        """Read the repository and say what it says."""
        self.run = Run.start(self.repo, self.task, [])
        self.run.engine = self.engine
        self.run.model = self.model
        chatting = is_small_talk(self.task)
        self.feed.emit(
            "run.started",
            repo=self.repo.name,
            task=self.task,
            skills=[],
            toolchain="",
            stages=["ask"],
            # Somebody said hello. The window has a line about which
            # repository is being looked at and a drawer of the steps
            # taken, and both are worth having when a question is being
            # answered out of a codebase. Neither is worth having here,
            # and three internal steps under a hello is the machinery
            # showing through the thing it is supposed to be doing.
            chatting=chatting,
        )
        self.feed.emit(
            "agent.state",
            agent="Analyst",
            state="working",
            # Said truthfully. It is not reading anything when somebody
            # has said hello, and a desk that claims to be reading a
            # repository nobody asked about is the office lying again.
            note="answering" if chatting else "reading the repository",
        )

        commit = Repo(self.repo).head()

        # Asked before, at this commit, and nothing has changed since.
        already = self.memory.recall(self.task, commit)
        if already:
            self.feed.emit(
                "agent.state",
                agent="Analyst",
                state="done",
                note="this was asked before and nothing has changed since",
            )
            self.run.answer = already
            self.run.save()
            self.feed.emit("answer", text=already, remembered=True)
            self.feed.close()
            return

        said, usage = ask(
            self.repo,
            self.task,
            engine=self.engine,
            model=self.model,
            on_event=self._agent_event("Analyst"),
            memory=self.memory,
            commit=commit,
        )
        self._spent(usage, "Analyst")
        self.run.answer = said
        self.run.save()
        self.memory.answered(self.task, said, commit)
        self.memory.save()
        self.feed.emit("agent.state", agent="Analyst", state="done", note="answered")
        self.feed.emit("answer", text=said)
        self.feed.close()

    def _already_read(self, commit: str) -> bool:
        """Use what was read before, when reading again would buy nothing.

        The Analyst took two minutes and thirty tool calls on a repository
        this program had worked thirteen times, to establish a toolchain,
        a build command and a test command that were already written down.
        Three quarters of that run went by before any code was written.

        Two cases, both decided without asking anybody:

        The same commit was surveyed before. Nothing has changed since, so
        the reading still holds - this one is free and applies to every
        profile.

        The repository is known but the commit has moved. The toolchain
        and the commands do not go stale the way a reading of the code
        does, so a fast job starts from them; a balanced or deep one still
        reads, because that is what those profiles are for.
        """
        read_before = self.memory.knows(commit)
        same_commit = bool(read_before)
        known_project = self.memory.recognises() and self.policy.profile == "fast"
        if not (same_commit or known_project):
            return False

        chain = detect(self.repo)
        findings = read_before or [
            (
                f"This repository has been worked on here before. It is "
                f"{self.memory.toolchain}; the build is "
                f"`{self.memory.build_command}` and the suite is "
                f"`{self.memory.test_command}`."
            ),
            (
                "It was not read again for this job, so nothing here is "
                "newer than the last time it was."
            ),
        ]
        self.run.inventory = Inventory(
            build_tool=chain.build_tool,
            language=chain.language,
            test_command=chain.test_command,
            build_command=chain.build_command,
            source_files=0,
            test_files=0,
            findings=findings,
            risks=[],
        )
        self.run.save()
        self.feed.emit(
            "agent.state",
            agent="Analyst",
            state="skipped",
            note=(
                "this commit has been read before"
                if same_commit
                else "this repository is known; reading it again was skipped"
            ),
        )
        self.feed.emit("survey", findings=findings, risks=[])
        return True

    def _survey(self, b, chain, commit: str) -> None:
        """Read the repository, and keep what was read."""
        self.feed.emit(
            "agent.state",
            agent="Analyst",
            state="working",
            note="reading the repository",
        )
        self.run.inventory, usage = survey(
            self.repo,
            self.run.brief,
            b,
            self.skills,
            self._agent_event("Analyst"),
            budget=self.run.left if self.budget else 0.0,
            engine=self.engine,
            model=self.model,
            memory=self.memory,
            commit=commit,
        )
        self._spent(usage, "Analyst")

        # The next job in this repository starts from these facts instead of
        # paying a second time to find them.
        self.memory.toolchain = f"{chain.build_tool} / {chain.language}"
        self.memory.build_command = chain.build_command
        self.memory.test_command = chain.test_command
        self.memory.last_test_count = b.tests_run
        self.memory.learn(self.run.inventory.findings, commit)
        self.memory.save()

        self.feed.emit(
            "agent.state",
            agent="Analyst",
            state="done",
            note=f"{len(self.run.inventory.findings)} findings, "
            f"{len(self.run.inventory.risks)} risks",
        )
        self.feed.emit(
            "survey",
            findings=self.run.inventory.findings,
            risks=self.run.inventory.risks,
        )

    def _after_plan(self, auto_run: bool) -> None:
        self.run.save()
        self.feed.emit(
            "plan.ready",
            summary=self.run.plan.summary,
            # What the request was taken to mean, and what was assumed to
            # get there. This is the one moment somebody can catch a
            # reading before it is built against, and until now the screen
            # showed the items and not the understanding behind them.
            expanded=self.run.expanded,
            assumptions=list(self.run.assumptions),
            items=[
                {
                    "id": i.id,
                    "title": i.title,
                    "verify_with": i.verify_with,
                    "rationale": i.rationale,
                }
                for i in self.run.plan.items
            ],
            cost=round(self.run.cost, 2),
            # A plan that is already being worked must not offer a button
            # that starts it. The straight path and every auto-run profile
            # reach here with nobody left to ask.
            approved=auto_run,
        )
        self.feed.emit(
            "agent.state",
            agent="Planner",
            state="done",
            note=f"{len(self.run.plan.items)} items, "
            + ("starting" if auto_run else "awaiting approval"),
        )
        if auto_run:
            self.work_the_plan()
        else:
            self.waiting = True
            self.feed.emit("awaiting.approval")

    # Which desk owns each stage. The verifier owns the baseline because the
    # baseline is a build and a test run, and that is the one judgement in the
    # room that is made by running something rather than by reading it.
    OWNERS: ClassVar[dict[str, list[str]]] = {
        "baseline": ["Verifier"],
        "analyst": ["Analyst"],
        "planner": ["Architect", "Designer", "Planner"],
        "engineer": ["Engineer", "Inspector", "Reviewer", "Critic"],
    }

    def _finish_early(self) -> None:
        """End a job that was never meant to reach the end of the line.

        `/check` and `/audit` are answers, not changes, so every desk after
        them is told it is not needed rather than left looking as though it
        had stalled. The run is still saved: the reading it did is worth
        keeping even though nothing was built on it.
        """
        self.run.save()
        reached = self._stages()
        after = [stage for stage in STAGES if stage not in reached]
        for stage in after:
            for who in self.OWNERS[stage]:
                self.feed.emit(
                    "agent.state",
                    agent=who,
                    state="skipped",
                    note="this job stops before this desk",
                )
        self.feed.emit(
            "run.summary",
            done=0,
            total=0,
            engine=self.engine,
            remembered=len(self.memory.notes),
            read_only=True,
            **self.run.what_happened(),
        )
        self.feed.close()

    def work_the_plan(self) -> None:
        """Approved. Do the items.

        Everything here runs on a thread of its own, which means an exception
        escaping it kills the thread and nothing else. The page keeps its
        spinner and waits for events that will never arrive, which is the
        worst failure this program can have: it looks exactly like working.
        """
        # Nothing is being waited for from here on, whether this was
        # approved, never needed approving, or went straight to the work.
        self.waiting = False
        try:
            self._work_the_plan()
        except BaseException as exc:  # noqa: BLE001 - nothing may die in silence
            self.error = f"{type(exc).__name__}: {exc}"
            self.feed.emit("run.error", detail=self.error)
            self.feed.emit(
                "run.summary",
                done=sum(1 for r in self.run.results if r.outcome.value == "done"),
                total=len(self.run.plan.items) if self.run.plan else 0,
                engine=self.engine,
                remembered=len(self.memory.notes),
                **self.run.what_happened(),
            )
            self.feed.close()

    def _work_the_plan(self) -> None:

        def on_item(item, phase):
            if phase == "start":
                self.feed.emit(
                    "agent.state", agent="Engineer", state="working", note=item.title
                )
                self.feed.emit("item.start", id=item.id, title=item.title)
            else:
                result = self.run.results[-1]
                tests = next((c for c in result.checks if c.name == "tests"), None)
                self.feed.emit(
                    "item.done",
                    id=item.id,
                    outcome=phase,
                    note=result.note,
                    attempts=result.attempts,
                    cost=round(self.run.cost, 2),
                    tests_detail=tests.detail[-400:] if tests else "",
                )

        def on_gate(item, who, passed, note):
            self.feed.emit(
                "gate",
                id=item.id,
                who=who,
                # Which desk this belongs to, decided here rather than in
                # the browser. The same three-name map in two languages is
                # two places for it to drift.
                station=GATE_STATION.get(who, ""),
                passed=passed,
                note=note or ("nothing to report" if passed else ""),
            )
            # Only the three gates are verdicts. `on_gate` is also called
            # for an engineer's question, a planner's answer, a restart and
            # a split, and every unrecognised one used to be mapped onto
            # the Reviewer with `passed` true - so the Reviewer was shown
            # as done, with a note about a restart, for items it had not
            # read. A station's state has to come from that station.
            station = GATE_STATION.get(who)
            if station:
                self.feed.emit(
                    "agent.state",
                    agent=station,
                    state="done" if passed else "failed",
                    note=(note or "nothing to report")[:140],
                )
            elif who == "answered":
                # This one is a station working: the planner settled a
                # question the engineer stopped to ask.
                self.feed.emit(
                    "agent.state",
                    agent="Planner",
                    state="done",
                    note=note[:140] or "answered the question",
                )

        execute(
            self.run,
            on_gate=on_gate,
            engine=self.engine,
            model=self.model,
            skills=self.skills,
            on_event=self._station_event(),
            on_item=on_item,
            should_stop=lambda: self.stopping,
            policy=self.policy,
        )
        self.feed.emit(
            "agent.state", agent="Engineer", state="done", note="plan finished"
        )
        landed = sum(1 for r in self.run.results if r.outcome.value == "done")

        # A job that finished everything it set out to do should end with the
        # thing running, not with instructions for running it. Nobody wants a
        # button; they want the link.
        link = ""
        if landed and landed == len(self.run.plan.items):
            try:
                link = preview.start(self.repo).url
            except (LookupError, RuntimeError, TimeoutError) as exc:
                self.feed.emit("preview.failed", detail=str(exc)[:600])
        # A profile that looks once looks here. The per-item critic was
        # skipped on purpose - judging a half-built page refuses it for
        # being half built - but skipping it everywhere would mean nobody
        # ever looked, which is how this program produced a page with no
        # times in its hours table and called it done.
        if link and self.policy.look_at_it == AT_THE_END:
            self._look_at_the_finished_thing(link)

        self.memory.record(
            self.run.task, landed, len(self.run.plan.items), self.run.cost
        )
        self.memory.save()
        self.feed.emit(
            "run.summary",
            done=landed,
            total=len(self.run.plan.items),
            engine=self.engine,
            remembered=len(self.memory.notes),
            url=link,
            # The record, so the window does not have to infer any of it.
            # The branch name in particular was being rebuilt in the
            # browser out of the session key, with the `-resumed` suffix
            # trimmed by hand - a guess at something that is written down.
            **self.run.what_happened(),
        )
        self._say_where_the_time_went()
        self._publish(landed, link)
        self.feed.close()

    def _look_at_the_finished_thing(self, url: str) -> None:
        """Have somebody look at the whole page, once, at the end.

        Not a gate: nothing is reverted on the strength of it, because
        there is no single item to revert and the work has already been
        verified piece by piece. It is a verdict on the finished thing,
        said out loud and put in the record, so that "it builds and the
        tests pass" is never the last word on something somebody has to
        look at.
        """
        import tempfile

        from .critic import look as look_at_it
        from .fits import why_it_does_not_fit

        if not self.run:
            return
        does_not_fit = why_it_does_not_fit(url, on_event=self._agent_event("Critic"))
        if does_not_fit:
            self.feed.emit("looked", approved=False, reason=does_not_fit)
            return

        try:
            with tempfile.TemporaryDirectory(prefix="drydock-done-") as scratch:
                seen, spend = look_at_it(
                    url,
                    self.run.direction,
                    f"The whole of it: {self.run.task.splitlines()[0]}",
                    Path(scratch),
                    brief=self.run.as_briefed,
                    model=self.model,
                    on_event=self._agent_event("Critic"),
                )
        except Exception as exc:  # noqa: BLE001 - a failed look is not a failed run
            self.feed.emit("looked", approved=False, reason=f"could not look: {exc}")
            return

        if seen is None:
            return
        self.run.dollars += spend
        # Nothing is reverted on the strength of this one - the work has
        # already been verified piece by piece - so a check that could not
        # finish is said rather than hidden, under its own station.
        if not seen.verified:
            self.feed.emit(
                "looked",
                approved=False,
                reason=f"not verified: {seen.failed}",
                noticed=[],
            )
            return
        self.feed.emit(
            "looked",
            approved=seen.approved,
            reason=seen.reason,
            noticed=getattr(seen, "noticed", []),
        )

    def _say_where_the_time_went(self) -> None:
        """How long that took, and which part of it was the work.

        Asked after every run so far, and answered with a guess every time.
        The events carry the times, so this is arithmetic over a file that
        was being written anyway.
        """
        if not self.run:
            return
        try:
            measured = from_log(Path("runs") / f"{self.run.id}.log")
        except OSError:
            return
        lines = measured.lines()
        if not lines:
            return
        self.feed.emit(
            "pace",
            lines=lines,
            seconds=round(measured.seconds),
            working=round(measured.working),
            checking=round(measured.checking),
        )

    def _publish(self, landed: int, url: str) -> None:
        """Open a draft pull request, if that is wanted and possible.

        The one thing this program does that leaves the machine, so it is
        narrow: only when something landed, only onto the run's own branch,
        always as a draft, and never without saying what happened. Anything
        missing - no gh, no remote, not signed in - is reported and nothing
        else changes; the work is on its branch either way.
        """
        if not landed or not Settings.load().publish_when_done:
            return

        ready, who = publish.signed_in()
        if not ready:
            self.feed.emit("published", ok=False, reason=who)
            return
        if not publish.has_remote(self.repo):
            self.feed.emit(
                "published", ok=False, reason="this repository has no remote"
            )
            return

        ok, said = publish.open_pull_request(
            self.repo,
            self.run,
            publish.evidence_from(self.run, Path("runs") / f"{self.run.id}.log"),
            url=url,
            draft=True,
        )
        self.feed.emit(
            "published",
            ok=ok,
            url=said if ok else "",
            reason="" if ok else said,
            author=who,
        )

    def stop(self, now: bool = False) -> None:
        """Ask the run to stop, or end it.

        Asked, by default: the flag is read wherever work is about to
        start - before an attempt, before a restart, before the two
        opinions, before an item is split, before a wave - so nothing new
        begins and the worker in flight finishes into a clean tree.

        Told, when `now`: the workers of this run are terminated as well,
        in the repository and in every worktree it made. Whatever they
        were writing is uncommitted and is thrown away by the attempt
        loop, which is the same path a refused item takes. This is what a
        deadline needs, and it is only honest because of the other half -
        a terminated worker used to be read as "taken away, try again",
        so killing one extended the run instead of ending it.
        """
        self.stopping = True
        killed = stop_workers(self.repo) if now else 0
        self.feed.emit(
            "stopping",
            note=(
                f"stopped: {killed} worker(s) ended"
                if now
                else "will stop after the current item, so nothing is left half done"
            ),
        )

    def ends_in(self, minutes: float) -> None:
        """End this run after `minutes`, whatever it is doing.

        A timer rather than a clock read at the checkpoints, because the
        checkpoints are only reached between pieces of work: a worker with
        twelve minutes on its own clock would carry the run past the
        deadline and nothing would be asked until it finished. The timer
        fires on time and ends the workers, and the checkpoints then stop
        anything else from starting.
        """
        if minutes <= 0:
            return
        if self._clock is not None:
            self._clock.cancel()
        self._clock = threading.Timer(minutes * 60, self._out_of_time)
        self._clock.daemon = True
        self._clock.start()

    def _out_of_time(self) -> None:
        if self.stopping:
            return
        self.feed.emit("deadline", note="the time this run was given is up")
        self.stop(now=True)

    def _stop_the_clock(self) -> None:
        """Nothing is owed to a timer once the run is over."""
        if self._clock is not None:
            self._clock.cancel()
            self._clock = None

    @classmethod
    def resume(
        cls,
        run: Run,
        engine: str = "claude",
        model: str = "opus",
        within_minutes: float = 0.0,
    ) -> "Session":
        """Pick a saved run back up where it stopped.

        A job takes twenty minutes and the thread it runs on does not survive
        the application closing, a crash, or somebody restarting the server
        mid-flight. The run on disk does survive all three, and each item is
        its own commit, so the work that landed is still landed and the only
        question is which item is next. `execute` already skips items that
        have results, so resuming is the same loop started again.
        """
        if run.integration_error:
            raise GitError(run.integration_error)

        # Checked before anything else touches disk. A dirty tree here is
        # not necessarily the interrupted worker's own leftovers - it might
        # be work somebody else is doing in the same checkout - and the old
        # code hard-reset and cleaned it on that assumption. Nothing is
        # saved, reset, cleaned, stashed, swept or checked out before this
        # passes.
        expected = run.expected_tip
        if not expected:
            raise GitError(
                f"{run.repo} has no recorded commit on {run.branch} to resume "
                "from. This looks like a run saved before resuming kept an "
                "anchor commit, so there is nothing safe to compare the "
                "branch against - it cannot be resumed."
            )
        repo = Repo(Path(run.repo))
        repo.require_checkout(run.branch, expected)

        # A cap saved with the run was a cap in dollars, and a run on a Claude
        # plan does not spend dollars per run. Carrying it forward would stop
        # the same job at the same item every time it was resumed.
        if (engine or run.engine) == "claude":
            run.budget = 0.0

        # Read back the skills the run was working under. This used to pass
        # an empty list, which made a resumed job a materially worse job
        # than the one it was continuing: the engineer carried on without
        # the packaged knowledge the first half of the plan had. Re-read
        # from disk rather than kept in the record on purpose - a skill
        # fixed after a run stopped is the usual reason to resume it.
        session = cls(
            Path(run.repo),
            run.task,
            _skills_named(run.skills),
            budget=run.budget,
            engine=engine or run.engine,
            model=model or run.model,
            # A resumed run gets its own deadline rather than the one the
            # interrupted run was given: the time it already spent is gone
            # and cannot be refunded, and carrying the old number forward
            # would stop it at the same place every time it was resumed.
            within_minutes=within_minutes,
        )
        session.run = run

        # An item that was blocked or rolled back is the item to try again,
        # not one to step over. Everything after it was never attempted
        # anyway, because the loop stops at the first failure.
        while run.results and run.results[-1].outcome.value != "done":
            dropped = run.results.pop()
            # The result goes; the reason it failed does not. It is the one
            # thing that makes the next attempt different from the last.
            if dropped.note:
                run.refused[dropped.item.id] = dropped.note
        run.save()

        # The tree was already clean and on the expected commit, by the
        # check above - there is nothing of the interrupted item's left to
        # throw away. A worker from that run could still be alive, though,
        # and it would happily write files back in once this one starts, so
        # it is stopped before anything else runs.
        orphans = stop_workers(Path(run.repo))

        session.feed.emit(
            "run.started",
            repo=Path(run.repo).name,
            task=run.task,
            skills=run.skills,
            toolchain="",
            stages=STAGES,
            resumed=True,
        )
        if orphans:
            session.feed.emit(
                "resumed",
                note=(
                    f"{orphans} worker(s) were still running in this "
                    "repository and were stopped before this resumed."
                ),
            )
        if run.baseline:
            b = run.baseline
            session.feed.emit(
                "baseline",
                builds=b.builds,
                tests=b.tests_run,
                failed=b.tests_failed,
                skipped=b.tests_skipped,
                green=b.green,
            )
        if run.plan:
            session.feed.emit(
                "plan.ready",
                summary=run.plan.summary,
                # Replayed too. A run reopened a day later showed its
                # items and not the reading they were planned against,
                # which is the half somebody goes back to check.
                expanded=run.expanded,
                assumptions=list(run.assumptions),
                items=[
                    {
                        "id": i.id,
                        "title": i.title,
                        "plain": i.plain,
                        "verify_with": i.verify_with,
                        "rationale": i.rationale,
                    }
                    for i in run.plan.items
                ],
                cost=round(run.cost, 2),
            )
            for r in run.results:
                session.feed.emit(
                    "item.done",
                    id=r.item.id,
                    outcome=r.outcome.value,
                    note=r.note,
                    attempts=r.attempts,
                    cost=round(run.cost, 2),
                    tests_detail="",
                )
        session.approve()
        return session

    def approve(self) -> None:
        """Start working the plan. Approving twice does not start it twice.

        A double click, a retried request, or two tabs on the same run used to
        start two threads on one repository, both committing into it. The
        second one is not a second worker; it is a corrupted run.
        """
        if self.running:
            return
        self._thread = threading.Thread(target=self.work_the_plan, daemon=True)
        self._thread.start()
