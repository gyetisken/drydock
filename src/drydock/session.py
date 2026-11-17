"""Running a job in the background while a page watches it.

The crew is ordinary blocking code: it waits on Maven, it waits on the API. So
it runs on a thread and reports through the feed, rather than being rewritten
to be asynchronous for the benefit of one view. A thread also means the run
survives the browser being closed, which is the behaviour anyone would expect
of something that takes twenty minutes and costs money.
"""

import threading
from pathlib import Path

from .analyst import baseline, survey
from .detect import detect
from .events import Feed
from .orchestrate import execute
from .planner import plan
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
    ) -> None:
        self.feed = Feed()
        self.repo = repo
        self.task = task
        self.skills = skills
        self.budget = budget
        self.engine = engine
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
            self.run = Run.start(self.repo, self.task, [s.name for s in self.skills])
            self.run.budget = self.budget
            self.run.engine = self.engine
            self.feed.emit(
                "run.started",
                repo=self.repo.name,
                task=self.task,
                skills=[s.name for s in self.skills],
                toolchain=f"{chain.build_tool} / {chain.language}",
            )

            self.feed.emit(
                "agent.state",
                agent="Analyst",
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
            )
            self.run.spend(usage)
            self.run.save()
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
            )
            self.run.spend(usage)
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
        except Exception as exc:  # noqa: BLE001 - the page has to be told
            self.error = f"{type(exc).__name__}: {exc}"
            self.feed.emit("run.error", detail=self.error)
        finally:
            if not self.running:
                pass

    def work_the_plan(self) -> None:
        """Approved. Do the items."""

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

        execute(
            self.run,
            engine=self.engine,
            skills=self.skills,
            on_event=self._agent_event("Engineer"),
            on_item=on_item,
        )
        self.feed.emit(
            "agent.state", agent="Engineer", state="done", note="plan finished"
        )
        self.feed.emit(
            "run.summary",
            done=sum(1 for r in self.run.results if r.outcome.value == "done"),
            total=len(self.run.plan.items),
            cost=round(self.run.cost, 2),
        )
        self.feed.close()

    def approve(self) -> None:
        self._thread = threading.Thread(target=self.work_the_plan, daemon=True)
        self._thread.start()
