"""A project made in the window was made inside drydock's own source.

Typing `gkhntest` into the sidebar created
`/Users/.../GitHub/drydock/gkhntest`. Nothing chose that: `Path("gkhntest")
.resolve()` is relative to the process's working directory, and the
working directory of a checkout is the harness's own repository. So the
project was born one directory below drydock, and from there three things
followed.

Claude Code walks up from the working directory and loads every
`CLAUDE.md` it passes. A nested `.git` does not stop the walk - measured,
not assumed - so a job about an Italian restaurant was handed drydock's
instructions to drydock's own implementation agent, including the line
telling it not to narrow the harness around the LUMI test project.

The confinement hook fenced the file tools and did not fence `Bash`; it
was not even in the matcher. The planning call grants bare `Bash` with no
prefix rule at all, so `cat ../CLAUDE.md` and `grep -r LUMI ..` were free.
The run's own findings name both: it read the parent's CLAUDE.md and took
"house pattern" from two sibling checkouts.

And the projects were untracked folders with their own `.git` inside this
one, which `git add -A` has already committed as gitlinks once.

Nothing here moves or deletes a folder anybody already has.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from drydock import confine
from drydock.commands import Command
from drydock.workspace import resolve_project, where_projects_go

ENGINES = Path("src/drydock/engines.py").read_text()
START = Path("src/drydock/start.py").read_text()
JS = Path("src/drydock/static/chat.js").read_text()


def flat(text: str) -> str:
    return " ".join(text.split())


class TestWhereANewProjectGoes:
    def test_a_bare_name_does_not_land_in_the_working_directory(self):
        """The whole of the bug. `resolve()` on a bare name is relative
        to wherever this process happens to be running."""
        where = resolve_project("gkhntest")
        assert where == where_projects_go() / "gkhntest"
        assert where != Path.cwd() / "gkhntest"

    def test_it_is_outside_this_repository(self, monkeypatch):
        monkeypatch.delenv("DRYDOCK_PROJECTS", raising=False)
        here = Path(__file__).resolve().parent.parent
        assert not where_projects_go().is_relative_to(here)

    def test_it_is_somewhere_a_person_can_find(self, monkeypatch):
        """Not under a dotfile. These are somebody's repositories and
        they have to be openable in a file manager. Asked without the
        suite's own override, which points it at a temporary directory."""
        monkeypatch.delenv("DRYDOCK_PROJECTS", raising=False)
        home = where_projects_go()
        assert not home.name.startswith(".")
        assert home.parent == Path.home()

    def test_an_absolute_path_is_still_exactly_itself(self, tmp_path):
        assert resolve_project(str(tmp_path / "some/repo")) == tmp_path / "some/repo"

    def test_a_home_path_is_still_opened_where_it_is(self):
        assert resolve_project("~/Documents/thing") == (Path.home() / "Documents/thing")

    def test_a_relative_path_is_a_path_and_not_a_name(self):
        """Somebody who types a separator meant a place."""
        assert resolve_project("./sibling") == (Path.cwd() / "sibling").resolve()
        assert resolve_project("a/b") == (Path.cwd() / "a/b").resolve()

    def test_nothing_is_typed_is_an_error_rather_than_the_home_itself(self):
        with pytest.raises(ValueError):
            resolve_project("   ")

    def test_it_can_be_pointed_somewhere_else(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DRYDOCK_PROJECTS", str(tmp_path / "mine"))
        assert where_projects_go() == tmp_path / "mine"
        assert resolve_project("thing") == tmp_path / "mine" / "thing"

    def test_add_project_uses_it(self):
        source = Path("src/drydock/workspace.py").read_text()
        block = source[source.index("def add_project") :][:1400]
        assert "resolve_project(path)" in block
        assert "path.expanduser().resolve()" not in block


class TestTheWindowSaysWhereItWillGo:
    def test_the_server_reports_the_projects_directory(self):
        from fastapi.testclient import TestClient

        from drydock.web import app

        said = TestClient(app).get("/api/state").json()
        assert said["projects_home"] == str(where_projects_go())

    def test_the_window_shows_it_before_anything_is_created(self):
        assert "function whereTo()" in JS
        said = JS[JS.index("function whereTo()") :][:700]
        assert "Creates ${S.projectsHome" in said
        assert "Opens ${said}" in said

    def test_the_box_asks_for_either(self):
        page = Path("src/drydock/web.py").read_text()
        assert "a name, or /path/to/an/existing/repository" in page

    def test_adding_one_returns_where_it_actually_went(self):
        page = Path("src/drydock/web.py").read_text()
        assert '"path": str(project.path)' in page


class TestAddingAProjectRedrawsTheWindow:
    def test_the_handler_is_whole_again(self):
        """An unfinished edit left `await` with nothing after it and no
        closing brace, so this function swallowed the next one and the
        sidebar never redrew. It parsed, which is why nothing caught it."""
        block = JS[JS.index('$("add").onclick') :][:900]
        assert "await refresh();" in block
        assert "openProject(body.path);" in block
        assert "await //" not in block

    def test_the_function_it_swallowed_exists_once(self):
        assert JS.count("async function reattach()") == 1
        assert JS.count("Palette.wire();") == 1

    def test_the_file_parses(self):
        done = subprocess.run(
            ["node", "--check", "src/drydock/static/chat.js"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr


class TestTheParentsInstructionsStayWithTheParent:
    def test_the_worker_is_told_which_settings_to_load(self):
        assert "SETTING_SOURCES = (" in ENGINES
        assert '"--setting-sources",' in ENGINES

    def test_both_ways_of_running_a_worker_use_it(self):
        """Structured answers and ordinary runs are two separate command
        builders, and a fix in one of them is a fix in half the program."""
        assert ENGINES.count("*SETTING_SOURCES,") == 2
        assert ENGINES.count('"--permission-mode",') == 2

    def test_it_is_not_done_by_turning_the_hooks_off(self):
        """`--bare` and `--safe-mode` both stop CLAUDE.md discovery and
        both stop hooks, which would take the confinement with them."""
        assert '"--bare"' not in ENGINES
        assert '"--safe-mode"' not in ENGINES

    def test_why_is_written_down(self):
        said = flat(ENGINES)
        assert "a nested `.git` does not stop the walk" in said


class TestTheShellIsFencedAtAll:
    def test_bash_is_in_the_matcher(self):
        """It was not. Everything below was unreachable."""
        assert '"matcher": "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"' in ENGINES

    def test_the_hook_routes_bash_to_the_shell_check(self):
        source = Path("src/drydock/confine.py").read_text()
        assert 'payload.get("tool_name") == "Bash"' in source


class TestWhatTheShellMayDo:
    @pytest.fixture
    def _root(self, tmp_path):
        """A real directory, resolved. `/tmp` is a link on a Mac and an
        unresolved root makes every path look outside."""
        root = tmp_path / "project"
        (root / "src" / "pages").mkdir(parents=True)
        (root / "README.md").write_text("x")
        type(self).ROOT = root
        return root

    @pytest.fixture(autouse=True)
    def _use(self, _root):
        return _root

    def refuse(self, command: str):
        return confine._shell_offence(command, self.ROOT)

    @pytest.mark.parametrize(
        "command",
        [
            'echo "DRYDOCK PHASE: reading"',
            "ls -la",
            "cat package.json",
            "git log --oneline -5",
            "git status --short",
            "node --version",
            "npm test",
            "npm run build && npm test",
            "python3 -m pytest -q",
            "find . -name '*.js'",
            "ls src/pages",
            "cat ./README.md",
        ],
    )
    def test_the_work_still_runs(self, command):
        assert self.refuse(command) is None, command

    @pytest.mark.parametrize(
        ("command", "what"),
        [
            ("cat ../CLAUDE.md", "the climb"),
            ("cat ../../etc/passwd", "two climbs"),
            ("cat /etc/passwd", "an absolute path"),
            ("grep -r LUMI /Users", "a search outside"),
            ("cat ~/.ssh/id_rsa", "a home directory"),
            ("npm test && cat ../CLAUDE.md", "the second link of a chain"),
            ("ls ../other-project", "a sibling"),
        ],
    )
    def test_it_may_not_leave_the_project(self, command, what):
        assert self.refuse(command), what

    @pytest.mark.parametrize(
        ("command", "what"),
        [
            ("echo $(cat ../CLAUDE.md)", "command substitution"),
            ("echo `cat ../CLAUDE.md`", "backticks"),
            ("cat ${HOME}/.ssh/id_rsa", "shell expansion"),
            ("diff <(cat a) <(cat b)", "process substitution"),
            ("npm test > ../out.txt", "redirection out"),
            ("cat < ../CLAUDE.md", "redirection in"),
            ("sleep 999 &", "a background command"),
            ("ls\\ncat ../CLAUDE.md", "a newline"),
        ],
    )
    def test_it_may_not_mean_something_other_than_it_reads(self, command, what):
        assert self.refuse(command), what

    @pytest.mark.parametrize(
        "command",
        ["curl https://example.com", "rm -rf /", "ssh host", "chmod 777 .", "sudo ls"],
    )
    def test_only_named_commands_run(self, command):
        said = self.refuse(command)
        assert said and "not a command this crew may run" in said

    def test_the_allow_list_can_be_read_in_one_sitting(self):
        """A list of names rather than a list of patterns is the point:
        a guard nobody can check by reading it is not a guard."""
        assert isinstance(confine.ALLOWED, frozenset)
        assert len(confine.ALLOWED) < 70
        assert all(" " not in name for name in confine.ALLOWED)

    def test_the_phase_marks_still_work(self):
        from drydock.start import PHASE_MARK, PHASES

        for phase in PHASES:
            assert self.refuse(f'echo "{PHASE_MARK} {phase}"') is None

    def test_an_empty_command_is_not_an_offence(self):
        assert self.refuse("") is None
        assert self.refuse("   ") is None

    def test_something_that_cannot_be_read_is_refused(self):
        assert self.refuse('cat "unclosed') is not None


class TestASymlinkIsNotAWayOut:
    def test_a_link_pointing_outside_is_followed_and_refused(self, tmp_path):
        """`..` is the obvious way out. A link is the boring one, and
        matching on spelling never sees it - `door` is a word."""
        root = tmp_path / "project"
        root.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "secret.txt").write_text("x")
        (root / "door").symlink_to(outside)

        assert confine._shell_offence("cat door/secret.txt", root) is not None
        assert confine._shell_offence("ls door", root) is not None

    def test_a_link_staying_inside_is_allowed(self, tmp_path):
        root = tmp_path / "project"
        (root / "real").mkdir(parents=True)
        (root / "real" / "a.txt").write_text("x")
        (root / "link").symlink_to(root / "real")
        assert confine._shell_offence("cat link/a.txt", root) is None


class TestTheHookStillRefusesAsItDid:
    def run_hook(self, payload: dict, root: Path):
        return subprocess.run(
            [sys.executable, "-m", "drydock.confine"],
            check=False,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "DRYDOCK_ROOT": str(root),
                "PYTHONPATH": str(Path("src").resolve()),
            },
        )

    def test_a_read_outside_is_still_blocked(self, tmp_path):
        done = self.run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}, tmp_path
        )
        assert done.returncode == 2
        assert "outside this project" in done.stderr

    def test_a_read_inside_is_still_allowed(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        done = self.run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "a.txt")}},
            tmp_path,
        )
        assert done.returncode == 0

    def test_a_shell_escape_is_blocked_end_to_end(self, tmp_path):
        done = self.run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "cat ../CLAUDE.md"}},
            tmp_path,
        )
        assert done.returncode == 2
        assert "outside this project" in done.stderr

    def test_a_build_is_allowed_end_to_end(self, tmp_path):
        done = self.run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "npm test"}}, tmp_path
        )
        assert done.returncode == 0

    def test_no_root_still_refuses_everything(self, tmp_path):
        done = subprocess.run(
            [sys.executable, "-m", "drydock.confine"],
            check=False,
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
            capture_output=True,
            text=True,
            env={
                k: v
                for k, v in {
                    **os.environ,
                    "PYTHONPATH": str(Path("src").resolve()),
                }.items()
                if k != "DRYDOCK_ROOT"
            },
        )
        assert done.returncode == 2


class TestTheScopeIsSaidOutLoud:
    def test_the_planner_is_told_the_folder_is_the_world(self):
        assert "**This folder is the whole world.**" in flat(START)

    def test_it_is_told_the_directory_above_is_not_evidence(self):
        said = flat(START)
        assert "Whatever is in the directory above it is somebody else's" in said
        assert "not its instructions" in said

    def test_it_is_told_a_refusal_is_the_answer(self):
        """So that being blocked is not read as a puzzle."""
        said = flat(START)
        assert "the refusal is not a puzzle to route around" in said

    def test_a_nested_folder_is_still_its_own_project(self):
        assert "is still its own project" in flat(START)


class TestTheRequestIsNotSaidTwice:
    TEMPLATE = (
        "Build {what}. Tests from the first commit, and nothing is "
        "finished until they pass."
    )

    def said(self, typed: str) -> str:
        return Command(
            name="/new", summary="s", asks="what", task_template=self.TEMPLATE
        ).task_for(typed)

    def test_the_verb_is_not_repeated(self):
        said = self.said("Build a website for an Italian restaurant called LUMI.")
        assert said.startswith("Build a website for an Italian restaurant")
        assert "Build Build" not in said

    def test_the_full_stop_is_not_doubled(self):
        said = self.said("Build a website for LUMI.")
        assert ".." not in said
        assert "for LUMI. Tests from the first commit" in said

    def test_a_lowercase_verb_is_caught_too(self):
        assert self.said("build a CLI").startswith("Build a CLI.")

    def test_somebody_who_did_not_repeat_it_is_untouched(self):
        said = self.said("a website for LUMI")
        assert said.startswith("Build a website for LUMI.")

    def test_a_word_that_merely_starts_the_same_is_left_alone(self):
        assert self.said("Builder tooling for the team").startswith(
            "Build Builder tooling"
        )

    def test_the_rest_of_what_they_wrote_is_not_touched(self):
        said = self.said("Build a site. It must work offline.")
        assert "It must work offline" in said

    def test_a_template_with_no_hole_is_unchanged(self):
        c = Command(name="/x", summary="s", asks="a", task_template="fixed text")
        assert c.task_for("anything") == "fixed text"

    def test_no_template_hands_back_what_was_typed(self):
        c = Command(name="/x", summary="s", asks="a", task_template="")
        assert c.task_for("  hello  ") == "  hello  "


class TestNothingNestedPollutesTheStatus:
    def test_the_projects_made_before_the_fix_are_ignored(self):
        for name in ("gkhntest", "TestProject", "newWebsiteProject"):
            # With the trailing slash, because the pattern is `/name/`
            # and git only matches that against a path spelt as a
            # directory. Here the folders exist and it matched either
            # way; on a fresh checkout they do not, and it did not.
            done = subprocess.run(
                ["git", "check-ignore", "-q", f"{name}/"],
                check=False,
                capture_output=True,
            )
            assert done.returncode == 0, name

    def test_nothing_was_moved_or_deleted_to_achieve_it(self):
        """They are somebody's work. The ignore file is the whole fix."""
        said = flat(Path(".gitignore").read_text())
        assert "Nothing is moved or deleted here" in said
