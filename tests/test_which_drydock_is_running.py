"""A server keeps the code it was started with, and nothing said so.

Modules are imported once. A fix committed after the server started is
in the repository and not in the process, so the run in front of you is
worked by the older code while every file on disk says otherwise.

That cost four mistakes in one afternoon: a benchmark started twice
against a server two commits behind, a critic prompt fix that was on
disk and not in the process, and a deadline that could not be passed
because the field lived in a file the server had never read. Each time
the only clue was behaviour that did not match the code, and each time
it took reading `ps -o lstart` against `git log` to notice.

So the process records what it was when it started, the repository is
asked what it is now, and the difference is shown. Nothing restarts
itself: a run in flight keeps the code it started with, and taking that
away mid-item is worse than being out of date.
"""

import subprocess
from pathlib import Path

from drydock import version


class TestWhatItReads:
    def test_the_loaded_commit_is_read_once(self):
        """Reading it again later would report the repository's commit
        rather than the process's, which is the confusion itself."""
        assert hasattr(version.loaded, "cache_info")
        first = version.loaded()
        assert version.loaded() == first

    def test_the_disk_commit_is_read_fresh(self):
        assert not hasattr(version.on_disk, "cache_info")

    def test_both_are_the_same_commit_in_this_checkout(self):
        """Nothing has been committed since this process imported the
        module, so they agree - and that is the ordinary case."""
        assert version.loaded() == version.on_disk()

    def test_it_is_a_real_commit(self):
        here = Path(__file__).resolve().parent.parent
        said = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert version.loaded() == said


class TestWhatItReports:
    def test_the_shape(self):
        s = version.status()
        assert set(s) == {"loaded", "on_disk", "short", "stale", "known"}

    def test_a_matching_pair_is_not_stale(self):
        assert version.status()["stale"] is False

    def test_the_short_form_is_what_a_person_reads(self):
        s = version.status()
        assert s["short"] == s["loaded"][:7]
        assert len(s["short"]) == 7

    def test_a_difference_is_stale(self, monkeypatch):
        monkeypatch.setattr(version, "on_disk", lambda: "0" * 40)
        s = version.status()
        assert s["stale"] is True
        assert s["on_disk"] == "0" * 40

    def test_an_installation_rather_than_a_checkout_says_it_does_not_know(
        self, monkeypatch
    ):
        """A program that cannot tell must say so rather than claim to
        be current."""
        monkeypatch.setattr(version.loaded, "__wrapped__", lambda: "")
        monkeypatch.setattr(version, "on_disk", lambda: "")
        monkeypatch.setattr(version, "loaded", lambda: "")
        s = version.status()
        assert s["known"] is False
        assert s["stale"] is False

    def test_one_side_missing_is_not_stale(self, monkeypatch):
        """Half an answer is not evidence of a mismatch."""
        monkeypatch.setattr(version, "on_disk", lambda: "")
        assert version.status()["stale"] is False


class TestItSurvivesABrokenGit:
    def test_no_git_is_not_a_crash(self, monkeypatch):
        def refuse(*a, **k):
            raise OSError("git is not here")

        monkeypatch.setattr(subprocess, "run", refuse)
        assert version._commit(Path("/nowhere")) == ""

    def test_a_non_zero_exit_is_not_a_commit(self, monkeypatch):
        class Done:
            returncode = 128
            stdout = "fatal: not a git repository"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
        assert version._commit(Path("/nowhere")) == ""


class TestTheWindowIsTold:
    def test_the_state_endpoint_carries_it(self):
        from fastapi.testclient import TestClient

        from drydock.web import app

        said = TestClient(app).get("/api/state").json()
        assert "version" in said
        assert said["version"]["loaded"] == version.loaded()

    def test_the_page_has_somewhere_to_put_it(self):
        page = Path("src/drydock/web.py").read_text()
        assert 'id="version"' in page

    def test_the_window_draws_it(self):
        js = Path("src/drydock/static/chat.js").read_text()
        assert "function drawVersion(" in js
        assert "drawVersion(full.version)" in js

    def test_it_says_what_to_do_about_it(self):
        js = Path("src/drydock/static/chat.js").read_text()
        assert "this server is older" in js
        assert "Restart it to pick the newer code up" in js

    def test_it_says_a_run_in_flight_keeps_its_code(self):
        """Nothing restarts itself. Taking the code away from an item
        mid-flight is worse than being out of date."""
        js = Path("src/drydock/static/chat.js").read_text()
        assert "a run in flight keeps the code it started with" in js

    def test_nothing_restarts_the_server(self):
        for name in ("web.py", "session.py", "orchestrate.py"):
            source = Path(f"src/drydock/{name}").read_text()
            assert "execv" not in source
            assert "uvicorn.run" not in source or name == "cli.py"

    def test_an_unknown_version_is_hidden_rather_than_guessed(self):
        js = Path("src/drydock/static/chat.js").read_text()
        assert "if (!v || !v.known) { box.hidden = true; return; }" in js
