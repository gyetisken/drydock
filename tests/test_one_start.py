"""One worker that reads, decides and plans, instead of four that queue.

Measured on an empty folder, for a one-page site: architect 71s, designer
5m41s, planner 2m54s - eight minutes and thirty-six seconds before a line
of the thing anybody asked for existed.

Almost none of that is the model being slow. Each station is its own
process with its own cold start, reads the task again from nothing, writes
its answer as prose for the next one, and dies. And every decision is made
ahead of the work, by somebody who will never see the result.

What is NOT folded in is everything after code exists. The verifier, the
inspector, the reviewer and the critic stay separate for the one reason
that matters: the thing that writes the code must not be the thing that
says it may stay. Every failure this project has had was the harness
believing its own report, and these tests pin that the back half is
untouched.
"""

import ast
from pathlib import Path

import pytest

from drydock import start
from drydock.planner import PLAN_SCHEMA

SESSION = (
    Path(__file__).resolve().parents[1] / "src" / "drydock" / "session.py"
).read_text()


class TestTheContractIsNotCopied:
    def test_the_plan_shape_comes_from_the_planner(self):
        """It lived in two places once. One copy was missing
        `worth_looking_at`, so the planner answered a shape that could not
        carry the field the orchestrator then went looking for."""
        fields = start._tool().schema["properties"]
        for name, shape in PLAN_SCHEMA["properties"].items():
            assert fields[name] is shape

    def test_an_item_still_carries_everything_the_loop_reads(self):
        item = start._tool().schema["properties"]["items"]["items"]["properties"]
        assert {"id", "needs", "verify_with", "worth_looking_at"} <= set(item)

    def test_strict_means_every_field_is_required(self):
        schema = start._tool().schema
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False


class TestWhatComesBack:
    def a_result(self, **over):
        found = {
            "findings": ["nothing here"],
            "risks": ["it could be generic"],
            "toolchain": "Node 20, no framework",
            "run_command": "node server.js",
            "test_command": "node --test",
            "direction": "sand ground, one accent",
            "summary": "four items",
            "items": [],
        }
        return start._said(found | over)

    def test_the_decisions_are_separated_from_the_plan(self):
        said = self.a_result()
        assert said.toolchain == "Node 20, no framework"
        assert said.direction == "sand ground, one accent"
        assert said.plan.summary == "four items"

    def test_the_shape_an_engineer_is_given_names_both_commands(self):
        said = self.a_result()
        assert "Node 20" in said.shape
        assert "`node server.js`" in said.shape
        assert "`node --test`" in said.shape

    def test_nothing_decided_is_nothing_said(self):
        """A repository that already has a toolchain has nothing for this
        to announce, and a paragraph saying so is a paragraph the engineer
        reads for no reason."""
        assert self.a_result(toolchain="").shape == ""

    def test_an_undirected_job_carries_no_direction(self):
        assert self.a_result(direction="  ").direction == ""

    def test_the_findings_become_the_inventory(self):
        from drydock.detect import Toolchain

        chain = Toolchain(
            language="unknown",
            build_tool="unknown",
            build_command="",
            test_command="",
            source_glob="**/*",
            test_glob="**/*test*",
        )
        said = self.a_result().inventory(chain)

        assert said.findings == ["nothing here"]
        assert said.risks == ["it could be generic"]
        assert said.build_tool == "Node 20, no framework"
        assert said.test_command == "node --test"

    def test_a_repository_that_states_its_own_toolchain_keeps_it(self):
        """It was read, not decided, so the detector is the authority."""
        from drydock.detect import Toolchain

        chain = Toolchain(
            language="TypeScript",
            build_tool="npm",
            build_command="npm run build",
            test_command="npm test",
            source_glob="src/**/*.ts",
            test_glob="**/*.test.ts",
        )
        said = self.a_result(toolchain="", test_command="").inventory(chain)

        assert said.build_tool == "npm"
        assert said.test_command == "npm test"


class TestSayingWhichDeskIsWorking:
    """The room shows four desks and one worker moving through them. Which
    desk is lit has to be something the worker reported, not something this
    program inferred from prose - inference is the thing being fixed
    everywhere else."""

    @pytest.mark.parametrize(
        "phase,desk",
        [
            ("reading", "Analyst"),
            ("stack", "Architect"),
            ("direction", "Designer"),
            ("plan", "Planner"),
        ],
    )
    def test_a_named_phase_lights_its_desk(self, phase, desk):
        said = f'Bash command=echo "{start.PHASE_MARK} {phase}"'
        assert start.desk_for(said) == desk

    def test_anything_else_lights_nothing(self):
        assert start.desk_for("Read file_path=/src/app.js") == ""
        assert start.desk_for("") == ""
        assert start.desk_for("I am now reading the repository") == ""

    def test_a_phase_nobody_defined_lights_nothing(self):
        assert start.desk_for(f"{start.PHASE_MARK} refactoring") == ""

    def test_every_phase_has_a_desk(self):
        assert set(start.PHASES) == set(start.PHASE_DESK)
        assert len(set(start.PHASE_DESK.values())) == 4

    def test_the_worker_is_told_the_exact_lines_to_run(self):
        system = start.SYSTEM.format(mark=start.PHASE_MARK, guide="")
        for phase in start.PHASES:
            assert f'echo "{start.PHASE_MARK} {phase}"' in system


class TestWhatItIsAndIsNotAllowedToDo:
    def test_it_reads_and_does_not_write(self):
        """It produces a plan. An engineer produces the code, and a start
        call that writes files has made changes nobody approved."""
        import inspect

        source = inspect.getsource(start.begin)
        assert 'tools="Read Glob Grep Bash"' in source
        assert "Edit Write NotebookEdit" in source

    def test_the_gates_are_not_folded_in(self):
        """The whole point of what is kept. Four stations merge; the four
        that judge the result do not."""
        for station in ("Verifier", "Inspector", "Reviewer", "Critic"):
            assert station not in start.SYSTEM
            assert station not in start.PHASE_DESK.values()


class TestBothRoadsStillExist:
    """The old path stays until the two have been compared on the same
    task. A claim about plan quality is a thing to measure with two runs,
    not a thing to assert."""

    def test_the_switch_chooses_between_them(self):
        assert 'os.environ.get("DRYDOCK_ONE_START") == "1"' in SESSION
        assert "self._begin_it(" in SESSION
        assert "self._plan_it" in SESSION

    def test_the_new_path_returns_rather_than_falling_through(self):
        """Falling through would run the four stations after the one call
        had already planned - and bill for both."""
        tree = ast.parse(SESSION)
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and "DRYDOCK_ONE_START" in ast.unparse(node.test)
        ]
        assert len(found) == 1
        assert isinstance(found[0].body[-1], ast.Return)


class TestTheWholeNewPath:
    """`_begin_it` from end to end, with the worker stubbed. No model, no
    network: what is being checked is that one answer is unpacked into the
    four things the rest of the run reads, and that the room is told."""

    @pytest.fixture
    def run_it(self, tmp_path, monkeypatch):
        import subprocess

        from drydock import session as session_module
        from drydock.detect import detect
        from drydock.run import Run

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = tmp_path / "cafe"
        repo.mkdir()
        for args in (
            ["init", "-q"],
            [
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "x",
            ],
        ):
            subprocess.run(["git", "-C", str(repo), *args], check=True)

        def go(**over):
            found = {
                "findings": ["the folder is empty"],
                "risks": [],
                "toolchain": "Node 20, no framework",
                "run_command": "node .",
                "test_command": "node --test",
                "direction": "sand ground, one accent",
                "summary": "one item",
                "items": [
                    {
                        "id": 1,
                        "title": "t",
                        "plain": "p",
                        "rationale": "r",
                        "files": [],
                        "verify_with": "tests",
                        "needs": [],
                        "worth_looking_at": True,
                        "removes_tests": False,
                    }
                ],
            } | over

            def fake_begin(repo_, task, empty, looked_at, known="", **kw):
                kw["on_event"]("tool", "Read file_path=README.md")
                for phase in start.PHASES:
                    kw["on_event"](
                        "tool", f'Bash command=echo "{start.PHASE_MARK} {phase}"'
                    )
                spend = type(
                    "U",
                    (),
                    {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cached_tokens": 0,
                        "dollars": 0.0,
                        "turns": 1,
                    },
                )()
                return start._said(found), spend

            monkeypatch.setattr(session_module, "begin", fake_begin)
            sess = session_module.Session(repo, "a page for a cafe", [])
            sess.run = Run.start(repo, "a page for a cafe")
            said = []
            sess.feed.emit = lambda kind, **f: said.append((kind, f))
            sess._begin_it(True, None, detect(repo), auto_run=False, commit="abc")
            return sess, said

        return go

    def desks(self, said):
        return [
            (f["agent"], f["state"])
            for kind, f in said
            if kind == "agent.state" and f["agent"] in start.PHASE_DESK.values()
        ]

    def test_one_answer_becomes_the_plan_the_direction_and_the_toolchain(self, run_it):
        sess, _ = run_it()

        assert len(sess.run.plan.items) == 1
        assert sess.run.direction == "sand ground, one accent"
        assert sess.run.inventory.build_tool == "Node 20, no framework"
        assert sess.run.inventory.test_command == "node --test"
        assert sess.run.inventory.findings == ["the folder is empty"]

    def test_each_desk_is_lit_and_then_closed(self, run_it):
        _, said = run_it()
        desks = self.desks(said)

        assert [d for d, state in desks if state == "working"] == [
            "Analyst",
            "Architect",
            "Designer",
            "Planner",
        ]
        for desk in ("Analyst", "Architect", "Designer", "Planner"):
            assert (desk, "done") in desks, f"{desk} was left running"

    def test_a_desk_is_not_lit_twice_running(self, run_it):
        """One worker is at one desk. Two lit at once would say two
        workers, which is the thing this change removes."""
        _, said = run_it()
        lit = 0
        for desk, state in self.desks(said):
            lit += 1 if state == "working" else -1
            assert lit <= 1, f"{desk} lit while another desk was"

    def test_an_undirected_job_does_not_claim_a_direction(self, run_it):
        sess, said = run_it(direction="")

        assert sess.run.direction == ""
        assert not any(kind == "look" for kind, _ in said)

    def test_the_worker_is_handed_what_the_last_job_learned(
        self, tmp_path, monkeypatch
    ):
        from drydock.memory import Memory, Note
        from drydock.run import Run
        from drydock.session import Session

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = tmp_path / "shop"
        repo.mkdir()
        sess = Session(repo, "add a thing", [])
        sess.run = Run.start(repo, "add a thing")
        sess.memory = Memory(repo=str(repo))
        sess.memory.notes = [
            Note(text="the suite lives in src/", commit="abc", learned="2026-11-19"),
            Note(text="from an older tree", commit="old", learned="2026-11-01"),
        ]

        said = sess._what_is_already_known("abc")

        assert "the suite lives in src/" in said
        assert "from an older tree" not in said, (
            "a fact about a tree that has changed is not a fact"
        )

    def test_a_repository_nobody_has_seen_is_handed_nothing(
        self, tmp_path, monkeypatch
    ):
        from drydock.run import Run
        from drydock.session import Session

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = tmp_path / "new"
        repo.mkdir()
        sess = Session(repo, "build it", [])
        sess.run = Run.start(repo, "build it")

        assert sess._what_is_already_known("abc") == ""
