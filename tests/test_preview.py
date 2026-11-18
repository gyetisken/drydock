"""Finding the thing that was built.

Two failures lived here, and both reported that nothing had started while
the page loaded perfectly in a browser.
"""

import json
import socket
import threading

from drydock.preview import _announced, _answers, how_to_run


def listening(family: int, host: str) -> int:
    """A socket on one address family only, like a real dev server."""
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    threading.Timer(2.0, sock.close).start()
    return port


class TestKnowingSomethingIsThere:
    def test_an_ipv4_server_is_found(self):
        assert _answers(listening(socket.AF_INET, "127.0.0.1"))

    def test_an_ipv6_server_is_found(self):
        """Node binds [::1] when told `localhost`. Probing IPv4 only made a
        running server invisible."""
        assert _answers(listening(socket.AF_INET6, "::1"))

    def test_nothing_listening_is_nothing_listening(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            free = sock.getsockname()[1]
        assert not _answers(free)


class TestReadingWhatTheServerSays:
    def test_the_announced_address_is_taken_from_the_log(self, tmp_path):
        log = tmp_path / "out.log"
        log.write_text("> astro dev\n\nDev server running at http://localhost:4321\n")
        assert _announced(log) == 4321

    def test_an_already_running_message_counts(self, tmp_path):
        """Astro's second invocation exits immediately and names where the
        first one is listening. That address is the answer."""
        log = tmp_path / "out.log"
        log.write_text(
            '{"message":"Dev server already running at http://localhost:5173 (pid 1)"}'
        )
        assert _announced(log) == 5173

    def test_the_last_address_wins(self, tmp_path):
        log = tmp_path / "out.log"
        log.write_text("http://localhost:3000 in use\nnow on http://127.0.0.1:3001\n")
        assert _announced(log) == 3001

    def test_a_log_with_no_address_says_nothing(self, tmp_path):
        log = tmp_path / "out.log"
        log.write_text("building...\ndone\n")
        assert _announced(log) is None


class TestHowToRunIt:
    def test_a_start_script_is_preferred_over_dev(self, tmp_path):
        import json

        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"dev": "vite", "start": "node ."}})
        )
        assert how_to_run(tmp_path)[0] == "npm run start"

    def test_a_folder_with_a_page_in_it_is_served(self, tmp_path):
        """Not a guess. A folder whose root is an index.html is not a
        project keeping quiet about how it runs - it is a page, and a
        static server is the only thing it could mean. Without this a
        plain HTML site could not be previewed or looked at at all."""
        (tmp_path / "index.html").write_text("<h1>hello</h1>")

        command, why = how_to_run(tmp_path)

        assert "http.server" in command
        assert '"$PORT"' in command, "it has to take the port it was given"
        assert "127.0.0.1" in command, "not on every interface of the machine"
        assert "index.html" in why

    def test_the_interpreter_is_this_one(self, tmp_path):
        """Not whatever `python3` happens to be on the path. The machine
        running drydock has this one for certain, and a system python that
        is missing or is 2.7 would fail for a reason that has nothing to
        do with the project."""
        import sys

        (tmp_path / "index.html").write_text("<h1>hello</h1>")
        assert how_to_run(tmp_path)[0].startswith(sys.executable)

    def test_anything_that_states_a_server_beats_the_page(self, tmp_path):
        """A page and a server in the same folder means the server renders
        the page."""
        (tmp_path / "index.html").write_text("<h1>hello</h1>")
        (tmp_path / "app.py").write_text("...")

        assert how_to_run(tmp_path)[0] == "python app.py"

    def test_a_manifest_still_wins(self, tmp_path):
        (tmp_path / "index.html").write_text("<h1>hello</h1>")
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"start": "vite"}})
        )

        assert how_to_run(tmp_path)[0] == "npm run start"

    def test_a_page_somewhere_else_is_not_looked_for(self, tmp_path):
        """A build output under dist/ is a project with a manifest, and
        hunting for pages in subdirectories is the guessing this module
        exists not to do."""
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "index.html").write_text("<h1>hello</h1>")

        assert how_to_run(tmp_path)[0] == ""

    def test_a_project_that_does_not_say_is_not_guessed_at(self, tmp_path):
        command, why = how_to_run(tmp_path)
        assert command == ""
        assert "does not say" in why


class TestAPreviewThatOutlivedTheApplication:
    """A dev server does not stop because the thing that started it did. It
    keeps the port, keeps watching the files and keeps serving whatever it
    last built - so the next run either cannot take the port or starts a
    second server beside the first, and somebody looks at a page built an
    hour ago and reports that their change did nothing."""

    def test_one_that_is_still_up_is_found_again(self, tmp_path, monkeypatch):
        from drydock import preview

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(preview, "_answers", lambda port: True)
        _write_a_note(preview, tmp_path / "nero", 4321, pid=0)

        found = preview.running(tmp_path / "nero")
        assert found is not None
        assert found.url == "http://localhost:4321"

    def test_one_that_has_gone_is_struck_off(self, tmp_path, monkeypatch):
        """The note is a cache of something the operating system knows, and
        the port is the thing that settles it."""
        from drydock import preview

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(preview, "_answers", lambda port: False)
        _write_a_note(preview, tmp_path / "nero", 4321, pid=0)

        assert preview.running(tmp_path / "nero") is None
        assert not list((tmp_path / "home" / "previews").glob("*.json"))

    def test_a_note_that_cannot_be_read_is_struck_off(self, tmp_path, monkeypatch):
        from drydock import preview

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        where = tmp_path / "home" / "previews"
        where.mkdir(parents=True)
        (where / preview._note_name(tmp_path / "nero")).write_text("{ not json")

        assert preview.running(tmp_path / "nero") is None

    def test_two_projects_keep_two_notes(self, tmp_path, monkeypatch):
        from drydock import preview

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(preview, "_answers", lambda port: True)
        _write_a_note(preview, tmp_path / "nero", 4321, pid=0)
        _write_a_note(preview, tmp_path / "other", 4322, pid=0)

        assert preview.running(tmp_path / "nero").url.endswith("4321")
        assert preview.running(tmp_path / "other").url.endswith("4322")

    def test_stopping_reaches_one_this_application_did_not_start(
        self, tmp_path, monkeypatch
    ):
        """Which is the whole point: finding it is no use if it cannot then
        be taken down."""
        from drydock import preview

        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(preview, "_answers", lambda port: True)
        preview._RUNNING.clear()
        _write_a_note(preview, tmp_path / "nero", 4321, pid=0)

        assert preview.stop(tmp_path / "nero") == 0  # pid 0: nothing to signal
        assert not list((tmp_path / "home" / "previews").glob("*.json"))


def _write_a_note(preview, repo, port: int, pid: int) -> None:
    import json

    where = preview._roster()
    (where / preview._note_name(repo)).write_text(
        json.dumps(
            {
                "project": str(repo),
                "url": f"http://localhost:{port}",
                "command": "npm run dev",
                "pid": pid,
            }
        )
    )
