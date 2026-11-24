"""Three minutes and twenty-five seconds to plan one page.

The run record says where it went. Ninety-four of the hundred and ninety
seconds were the plan being written, which is the work. The rest was not.

    15:50:13  node --version 2>&1; npm --version 2>&1   <- refused
    15:50:15  node --version; npm --version             <- the same probe
    15:50:25  python3 --version; which python3
    ...
    15:52:58  node -e "JSON.parse(readFileSync(...))"   <- checking its own file
    15:53:00  git status --short                        <- checking the tree

The first of those was refused by this program's own shell fence, which
treats every `>` as a redirection - and `2>&1` writes nowhere anybody
can read. So the worker ran the same probe again two seconds later
without it. A round trip, caused by us, visible in the log.

The next two asked what is installed on this machine, which this
process can read in half a second and had not been asked to. Three
round trips and about twenty seconds for two version numbers.

The last two were the worker checking work this program already does:
the answer file is parsed here, a malformed one is handed back once to
be written again, and a stray file is swept before anything is
committed. Careful, and nobody had told it.

None of this is a limit on turns or on time. It is not asking twice.
"""

import inspect
from pathlib import Path

from drydock import confine
from drydock.detect import installed
from drydock.session import Session


def _as_written(path: str) -> str:
    """The source with its line wrapping and its string joins taken out.

    An assertion about a sentence should not also be an assertion about
    where the formatter decided to break it, or where one string
    literal ends and the next begins.
    """
    said = " ".join(Path(path).read_text().split())
    return said.replace('" "', "").replace("' '", "")


ENGINES = _as_written("src/drydock/engines.py")


class TestOurOwnFenceStoppedCostingARoundTrip:
    def fence(self, command: str):
        return confine._shell_offence(command, Path("/tmp"))

    def test_the_probe_that_was_refused_now_runs(self):
        assert self.fence("node --version 2>&1; npm --version 2>&1") is None

    def test_stderr_to_the_null_device_too(self):
        assert self.fence("ls 2>/dev/null") is None
        assert self.fence("git status 2>/dev/null") is None

    def test_the_numbered_forms(self):
        assert self.fence("echo hi 1>&2") is None
        assert self.fence("node --version 2>&1") is None

    def test_a_redirection_that_writes_somewhere_is_still_refused(self):
        assert self.fence("npm test > out.txt") is not None
        assert self.fence("npm test >> out.txt") is not None
        assert self.fence("cat < secrets") is not None

    def test_taking_it_out_does_not_let_an_escape_through(self):
        """The rest of the line is still judged as it would have been."""
        assert self.fence("cat ../CLAUDE.md 2>/dev/null") is not None
        assert self.fence("curl example.com 2>&1") is not None
        assert self.fence("echo $(cat ../x) 2>&1") is not None

    def test_a_pipe_after_it_is_still_a_chain_and_still_checked(self):
        assert self.fence("npm test 2>&1 | grep fail") is None
        assert self.fence("npm test 2>&1 | cat ../CLAUDE.md") is not None


class TestWhatIsInstalledIsReadRatherThanAsked:
    def test_it_answers(self):
        said = installed()
        assert said
        assert "node" in said

    def test_it_is_quick(self):
        """Half a second against twenty. A probe that hangs would be
        worse than letting a planner find out for itself."""
        import time

        began = time.monotonic()
        installed()
        assert time.monotonic() - began < 8

    def test_it_says_absence_is_information(self):
        assert "Anything not listed is not installed" in installed()

    def test_it_does_not_pretend_to_be_everything(self):
        assert "go and find out" in installed()

    def test_nothing_installed_is_an_empty_answer_rather_than_a_heading(
        self, monkeypatch
    ):
        monkeypatch.setattr("drydock.detect.shutil.which", lambda _: None)
        assert installed() == ""

    def test_a_probe_that_fails_is_skipped_rather_than_fatal(self, monkeypatch):
        def refuse(*a, **k):
            raise OSError("no")

        monkeypatch.setattr("drydock.shell.run", refuse)
        assert installed() == ""


class TestItIsOnlyGivenWhereItDecidesSomething:
    def test_an_empty_repository_is_told(self):
        assert "empty: bool = False" in inspect.getsource(
            Session._what_is_already_known
        )
        said = inspect.getsource(Session._what_is_already_known)
        assert "if empty:" in said
        assert "installed()" in said

    def test_a_repository_that_declares_its_own_toolchain_is_not(self):
        """There it decides nothing: the stack is a fact to be read."""
        said = " ".join(inspect.getsource(Session._what_is_already_known).split())
        assert "A planner reading a repository that declares its own" in said

    def test_the_planner_is_handed_it_through_the_channel_that_existed(self):
        """`known` already carried what the last job learned. No new
        parameter, no new store."""
        source = Path("src/drydock/session.py").read_text()
        block = source[source.index("started, usage = begin(") :][:600]
        assert "known=self._what_is_already_known(commit, empty=empty)" in block

    def test_what_the_repository_taught_last_time_still_comes_too(self):
        said = inspect.getsource(Session._what_is_already_known)
        assert "self.memory.knows(commit)" in said
        assert "notes[:20]" in said


class TestTheWorkerIsNotCheckingOurWorkForUs:
    def test_it_is_told_the_answer_is_checked_here(self):
        assert "read and checked by the program that asked for it" in ENGINES

    def test_it_is_told_a_bad_answer_comes_back_rather_than_being_lost(self):
        assert "handed it back to redo if it will not" in ENGINES

    def test_it_is_told_not_to_spend_a_turn_on_either_check(self):
        assert "do not spend a turn validating it yourself" in ENGINES
        assert "checking what the tree looks like afterwards" in ENGINES

    def test_the_program_really_does_check_it(self):
        """Saying so would be worse than useless if it did not."""
        from drydock.critic import look

        assert "MalformedAnswer" in inspect.getsource(look)
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "here.sweep()" in source

    def test_the_instruction_to_write_nothing_else_is_still_there(self):
        assert "Write no other file and change nothing else" in ENGINES


class TestNoLimitsWereImposed:
    def test_the_turn_count_is_unchanged(self):
        from drydock.policy import BALANCED, DEEP, FAST, PROFILES

        assert PROFILES[BALANCED].turns == 60
        assert PROFILES[DEEP].turns == 80
        assert PROFILES[FAST].turns == 60

    def test_the_planner_still_gets_forty_turns(self):
        source = Path("src/drydock/start.py").read_text()
        assert "max_turns=40" in source

    def test_the_minutes_are_unchanged(self):
        from drydock.policy import BALANCED, PROFILES

        assert PROFILES[BALANCED].minutes == 12.0
        assert PROFILES[BALANCED].retry_minutes == 18.0

    def test_the_planner_may_still_run_what_it_needs(self):
        """Nothing was taken off the list of commands it may run."""
        for name in ("node", "npm", "python3", "git", "ls", "cat", "echo"):
            assert name in confine.ALLOWED, name


class TestNothingProtectiveWasTraded:
    def test_the_fence_still_fences(self):
        root = Path("/tmp")
        assert confine._shell_offence("cat /etc/passwd", root) is not None
        assert confine._shell_offence("curl example.com", root) is not None

    def test_the_matcher_still_names_bash(self):
        assert '"matcher": "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"' in ENGINES

    def test_the_worker_still_inherits_no_settings_at_all(self):
        assert '("--setting-sources", "")' in ENGINES

    def test_the_credentials_are_still_stripped(self):
        assert "AUTH_THAT_IS_NOT_OURS" in ENGINES

    def test_the_stop_checks_are_still_in_the_loop(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5

    def test_the_handoff_still_reaches_the_engineer(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "run.handoff," in source
