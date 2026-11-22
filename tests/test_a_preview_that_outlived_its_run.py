"""Two of three looks spent finding out a port was taken.

The successful LUMI run delivered, and said this about itself:

    engineer: npm start serves on port 4821, not a conventional one:
    4173 was already held by something else on this machine
    engineer: Two of the three looks were spent on those failed starts

The looks are the only way an engineer sees the page it is building, and
it gets three. Two went on a port.

What held 4173, measured on this machine afterwards: a `node server.js`
from an earlier run, beside two `python3 -m http.server` processes three
days old. All of them previews this program started and never stopped.

`stop()` works on `_RUNNING`, which is a dict in memory. A fresh
application owns no previews, so it reaps none of the ones it finds -
the roster file knows the pid and nothing ever read it back except for
one project at a time. So they accumulate, each keeping a port, and the
next run's engineer pays for it.

`reap()` reads the roster when the application starts and stops what an
application that has gone left behind. Two things have to hold before
anything is signalled, because either alone could point at somebody
else's process: the recorded port still answers, and the recorded pid is
still running the recorded command.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from drydock import preview

WEB = Path("src/drydock/web.py").read_text()


@pytest.fixture
def roster(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
    return tmp_path / "previews"


def note(roster: Path, project: str, url: str, pid: int, command: str) -> Path:
    roster.mkdir(parents=True, exist_ok=True)
    path = roster / (project.strip("/").replace("/", "-") + ".json")
    path.write_text(
        json.dumps({"project": project, "url": url, "pid": pid, "command": command})
    )
    return path


class TestWhatReapStops:
    def test_a_dead_port_only_loses_its_note(self, roster):
        """Nothing to stop. The note is the only thing left."""
        path = note(roster, "/tmp/a", "http://localhost:1", 999999, "npm run start")
        assert preview.reap() == 0
        assert not path.exists()

    def test_a_live_preview_of_a_departed_application_is_stopped(self, roster):
        served = subprocess.Popen(
            [sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            line = served.stdout.readline()
            port = int(line.rsplit("port ", 1)[1].split()[0])
            path = note(
                roster,
                "/tmp/b",
                f"http://localhost:{port}",
                served.pid,
                f"{sys.executable} -m http.server",
            )
            assert preview.reap() == 1
            assert not path.exists()
            served.wait(timeout=10)
        finally:
            if served.poll() is None:
                served.kill()

    def test_a_recycled_pid_is_not_signalled(self, roster, monkeypatch):
        """The port answering says something is serving. It does not say
        the something is ours."""
        monkeypatch.setattr(preview, "_answers", lambda *a, **k: True)
        monkeypatch.setattr(preview, "_still_that_command", lambda *a, **k: False)
        killed = []
        monkeypatch.setattr(preview, "_signal_group", lambda p, s: killed.append(p.pid))
        note(roster, "/tmp/c", "http://localhost:9999", 4242, "npm run start")
        assert preview.reap() == 0
        assert killed == []

    def test_both_conditions_are_required(self, roster, monkeypatch):
        monkeypatch.setattr(preview, "_answers", lambda *a, **k: False)
        monkeypatch.setattr(preview, "_still_that_command", lambda *a, **k: True)
        killed = []
        monkeypatch.setattr(preview, "_signal_group", lambda p, s: killed.append(p.pid))
        note(roster, "/tmp/d", "http://localhost:9999", 4242, "npm run start")
        assert preview.reap() == 0
        assert killed == []

    def test_a_broken_note_is_removed_rather_than_crashing(self, roster):
        roster.mkdir(parents=True, exist_ok=True)
        bad = roster / "tmp-nonsense.json"
        bad.write_text("{not json")
        assert preview.reap() == 0
        assert not bad.exists()

    def test_nothing_written_down_is_nothing_to_do(self, roster):
        assert preview.reap() == 0


class TestWhoseCommandIsStillRunning:
    def test_this_process_is_recognised_by_its_own_name(self):
        import os

        assert preview._still_that_command(os.getpid(), sys.executable)

    def test_a_pid_that_is_gone_is_not(self):
        assert not preview._still_that_command(999999, "python3 -m http.server")

    def test_no_pid_and_no_command_are_both_refusals(self):
        import os

        assert not preview._still_that_command(0, "npm start")
        assert not preview._still_that_command(os.getpid(), "   ")


class TestItRunsWhenTheApplicationStarts:
    def test_there_is_a_startup_hook(self):
        assert '@app.on_event("startup")' in WEB
        assert "preview.reap()" in WEB

    def test_the_shutdown_hook_is_untouched(self):
        """A preview this process started is its own and is stopped the
        ordinary way."""
        assert '@app.on_event("shutdown")' in WEB
        assert "preview.stop()" in WEB

    def test_it_says_how_many_it_found(self):
        assert "left by an earlier run" in WEB


class TestAStationsOwnCallsAreItsOwn:
    """Nine of the forty-three calls counted as the engineer's were the
    critic's and the reviewer's, with ninety-eight seconds of their time.
    A worker reports `("tool", ...)`, which names what happened and not
    who did it."""

    def test_the_relabeller_exists(self):
        from drydock.orchestrate import _said_by

        said = []
        _said_by("critic", lambda who, text: said.append((who, text)))("tool", "x")
        assert said == [("critic", "x")]

    def test_it_leaves_anything_already_named_alone(self):
        from drydock.orchestrate import _said_by

        said = []
        _said_by("critic", lambda who, text: said.append((who, text)))("model", "x")
        assert said == [("model", "x")]

    def test_no_feed_is_still_no_feed(self):
        from drydock.orchestrate import _said_by

        assert _said_by("critic", None) is None

    def test_the_critic_is_labelled(self):
        import inspect

        from drydock import orchestrate

        assert 'on_event=_said_by("critic", on_event)' in inspect.getsource(
            orchestrate._show_it
        )

    def test_the_reviewer_is_labelled(self):
        import inspect

        from drydock import orchestrate

        assert 'on_event=_said_by("reviewer", on_event)' in inspect.getsource(
            orchestrate._judge
        )

    def test_the_engineer_still_reports_as_itself(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        block = source[source.index("report, usage = work(") :][:900]
        assert "_said_by" not in block


class TestTheCriticIsToldHowThePictureWasMade:
    def said(self) -> str:
        from drydock.critic import PROMPT

        return " ".join(PROMPT.split())

    def test_it_is_told_the_shot_is_whole(self):
        assert "taken whole, in one go" in self.said()
        assert "Nothing is scrolled, nothing is joined" in self.said()

    def test_it_is_told_what_that_rules_out(self):
        said = self.said()
        assert "there is no seam for anything to be duplicated across" in said
        assert "do not account for it with a stitch that did not happen" in said

    def test_it_is_still_asked_to_say_what_it_sees(self):
        """Not a muzzle. The critic reported a ghost that is not in the
        pixels and hedged it correctly into `noticed`; what it lacked was
        a true account of how the picture is made."""
        said = self.said()
        assert "Say what you see and say you are unsure if you are" in said

    def test_the_sizes_it_is_given_are_the_sizes_taken(self):
        from drydock.shot import WIDTHS

        said = self.said()
        for width, height in WIDTHS.values():
            assert f"{width} by {height}" in said or f"{width} by {height}" in said

    def test_the_capture_really_is_one_shot(self):
        """Saying so would be worse than useless if it were not."""
        source = Path("src/drydock/shot.py").read_text()
        assert source.count("Page.captureScreenshot") == 1
        #  is a flag, not a scroll. These are the
        # things a stitched capture would need.
        for word in ("scrollTo", "scrollHeight", "stitch", "captureBeyondViewport"):
            assert word not in source, word
