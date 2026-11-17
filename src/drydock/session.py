"""Running a job in the background while a page watches it.

The crew is ordinary blocking code: it waits on Maven, it waits on the API. So
it runs on a thread and reports through the feed, rather than being rewritten
to be asynchronous for the benefit of one view. A thread also means the run
survives the browser being closed, which is the behaviour anyone would expect
of something that takes twenty minutes and costs money.
"""

import threading
from pathlib import Path
from typing import ClassVar

from . import preview
from .analyst import baseline, survey
from .architect import as_briefing, design
from .commands import STAGES
from .detect import detect
from .engines import stop_workers
from .events import Feed
from .memory import Memory
from .models import Inventory
from .orchestrate import execute
from .planner import plan
from .repo import Repo
from .run import Run
from .skills import Skill


class Session:
    def __init__(
        self,
        repo: Path,
        task: str,
        skills: list[Skill],
        budget: float = 0.0,
        engine: str = "api",
        model: str = "opus",
        stop_after: str = "planner",
        standing: str = "",
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
        # Whatever this person always wants true of work in this repository.
        # Appended to the task rather than mixed into the system prompt, so
        # it is visible in the run record as part of what was asked for.
        self.standing = standing.strip()
        self.stopping = False
        self.memory = Memory.about(repo)
        self.run: Run | None = None
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self, auto_run: bool = False) -> None:
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
                out.write(event.sse()[6:])
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

    def _work(self, auto_run: bool) -> None:
        try:
            chain = detect(self.repo)
            if self.standing:
                self.task = (
                    f"{self.task}\n\nStanding instructions for this repository, "
                    f"which hold for every job here:\n{self.standing}"
                )
            self.run = Run.start(self.repo, self.task, [s.name for s in self.skills])
            self.run.budget = self.budget
            self.run.engine = self.engine
            self.run.model = self.model
            self.feed.emit(
                "run.started",
                repo=self.repo.name,
                task=self.task,
                skills=[s.name for s in self.skills],
                toolchain=f"{chain.build_tool} / {chain.language}",
                stages=STAGES[: STAGES.index(self.stop_after) + 1],
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
            self.run.save()

            if self.stop_after == "baseline":
                self._finish_early()
                return

            # An empty repository has nothing to survey, and a survey run
            # against one produces twenty findings that all say the same
            # thing: there are no files. That costs real money and two
            # minutes to learn what one `iterdir` already knows. So the two
            # stations are alternatives, not a sequence - one reads what is
            # there, the other decides what should be.
            empty = not any(p.name != ".git" for p in self.repo.iterdir())
            commit = Repo(self.repo).head()

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
            else:
                self._survey(b, chain, commit)

            if self.stop_after == "analyst":
                self._finish_early()
                return

            shape = ""
            if empty:
                self.feed.emit(
                    "agent.state",
                    agent="Architect",
                    state="working",
                    note="deciding what this is made of",
                )
                found, usage = design(
                    self.repo,
                    self.task,
                    self.skills,
                    self._agent_event("Architect"),
                    budget=self.run.left if self.budget else 0.0,
                    engine=self.engine,
                    model=self.model,
                )
                self._spent(usage, "Architect")
                shape = as_briefing(found)
                self.feed.emit(
                    "agent.state",
                    agent="Architect",
                    state="done",
                    note=found.get("stack", "")[:90] or "shape decided",
                )
                self.feed.emit("design", **found)
            else:
                self.feed.emit(
                    "agent.state",
                    agent="Architect",
                    state="skipped",
                    note="the project already has a shape; the Analyst read it",
                )

            self.feed.emit(
                "agent.state",
                agent="Planner",
                state="working",
                note="turning the survey into items",
            )
            self.run.plan, usage = plan(
                self.repo,
                self.task,
                self.run.inventory,
                b,
                self.skills,
                self._agent_event("Planner"),
                budget=self.run.left if self.budget else 0.0,
                engine=self.engine,
                model=self.model,
                shape=shape,
            )
            self._spent(usage, "Planner")
            self._after_plan(auto_run)

        except Exception as exc:  # noqa: BLE001 - the page has to be told
            self.error = f"{type(exc).__name__}: {exc}"
            self.feed.emit("run.error", detail=self.error)

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
            self.task,
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
        )
        self.feed.emit(
            "agent.state",
            agent="Planner",
            state="done",
            note=f"{len(self.run.plan.items)} items, awaiting approval",
        )
        if auto_run:
            self.work_the_plan()
        else:
            self.feed.emit("awaiting.approval")

    # Which desk owns each stage. The verifier owns the baseline because the
    # baseline is a build and a test run, and that is the one judgement in the
    # room that is made by running something rather than by reading it.
    OWNERS: ClassVar[dict[str, list[str]]] = {
        "baseline": ["Verifier"],
        "analyst": ["Analyst"],
        "planner": ["Architect", "Planner"],
        "engineer": ["Engineer", "Inspector", "Reviewer"],
    }

    def _finish_early(self) -> None:
        """End a job that was never meant to reach the end of the line.

        `/check` and `/audit` are answers, not changes, so every desk after
        them is told it is not needed rather than left looking as though it
        had stalled. The run is still saved: the reading it did is worth
        keeping even though nothing was built on it.
        """
        self.run.save()
        after = STAGES[STAGES.index(self.stop_after) + 1 :]
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
            cost=round(self.run.cost, 2),
            engine=self.engine,
            remembered=len(self.memory.notes),
            read_only=True,
        )
        self.feed.close()

    def work_the_plan(self) -> None:
        """Approved. Do the items.

        Everything here runs on a thread of its own, which means an exception
        escaping it kills the thread and nothing else. The page keeps its
        spinner and waits for events that will never arrive, which is the
        worst failure this program can have: it looks exactly like working.
        """
        try:
            self._work_the_plan()
        except BaseException as exc:  # noqa: BLE001 - nothing may die in silence
            self.error = f"{type(exc).__name__}: {exc}"
            self.feed.emit("run.error", detail=self.error)
            self.feed.emit(
                "run.summary",
                done=sum(1 for r in self.run.results if r.outcome.value == "done"),
                total=len(self.run.plan.items) if self.run.plan else 0,
                cost=round(self.run.cost, 2),
                engine=self.engine,
                remembered=len(self.memory.notes),
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
                passed=passed,
                note=note or ("nothing to report" if passed else ""),
            )
            self.feed.emit(
                "agent.state",
                agent="Inspector" if who == "inspector" else "Reviewer",
                state="done" if passed else "failed",
                note=(note or "nothing to report")[:140],
            )

        execute(
            self.run,
            on_gate=on_gate,
            engine=self.engine,
            model=self.model,
            skills=self.skills,
            on_event=self._agent_event("Engineer"),
            on_item=on_item,
            should_stop=lambda: self.stopping,
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
        self.memory.record(
            self.run.task, landed, len(self.run.plan.items), self.run.cost
        )
        self.memory.save()
        self.feed.emit(
            "run.summary",
            done=landed,
            total=len(self.run.plan.items),
            cost=round(self.run.cost, 2),
            engine=self.engine,
            remembered=len(self.memory.notes),
            url=link,
        )
        self.feed.close()

    def stop(self) -> None:
        """Ask the run to stop at the next safe point.

        Not a kill. The crew is in the middle of an item, and killing it there
        leaves half an edit on disk with no commit to undo it. The flag is read
        between items, where the tree is clean.
        """
        self.stopping = True
        self.feed.emit(
            "stopping",
            note="will stop after the current item, so nothing is left half done",
        )

    @classmethod
    def resume(cls, run: Run, engine: str = "claude", model: str = "opus") -> "Session":
        """Pick a saved run back up where it stopped.

        A job takes twenty minutes and the thread it runs on does not survive
        the application closing, a crash, or somebody restarting the server
        mid-flight. The run on disk does survive all three, and each item is
        its own commit, so the work that landed is still landed and the only
        question is which item is next. `execute` already skips items that
        have results, so resuming is the same loop started again.
        """
        # A cap saved with the run was a cap in dollars, and a run on a Claude
        # plan does not spend dollars per run. Carrying it forward would stop
        # the same job at the same item every time it was resumed.
        if (engine or run.engine) == "claude":
            run.budget = 0.0

        session = cls(
            Path(run.repo),
            run.task,
            [],
            budget=run.budget,
            engine=engine or run.engine,
            model=model or run.model,
        )
        session.run = run

        # An item that was blocked or rolled back is the item to try again,
        # not one to step over. Everything after it was never attempted
        # anyway, because the loop stops at the first failure.
        while run.results and run.results[-1].outcome.value != "done":
            run.results.pop()
        run.save()

        # Whatever was being written when this stopped belongs to an item
        # that never landed, and an item that never landed is one whose
        # changes are thrown away. Leaving them would also mean the next
        # item's commit quietly contains someone else's half-finished work.
        # Anything still working in this repository is an orphan from the run
        # that was interrupted, and it will happily write files back in
        # behind the clean-up. Stop it first, then clean.
        orphans = stop_workers(Path(run.repo))
        repo = Repo(Path(run.repo))
        dirty = not repo.is_clean()
        if dirty:
            repo.discard()

        session.feed.emit(
            "run.started",
            repo=Path(run.repo).name,
            task=run.task,
            skills=run.skills,
            toolchain="",
            stages=STAGES,
            resumed=True,
        )
        if dirty or orphans:
            note = (
                "A half-finished item was left on disk when this stopped. It "
                "was thrown away, which is what happens to any item that does "
                "not land. Everything already committed is untouched."
            )
            if orphans:
                note += (
                    f" {orphans} worker(s) were still running in this "
                    "repository and were stopped first."
                )
            session.feed.emit("resumed", note=note)
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
