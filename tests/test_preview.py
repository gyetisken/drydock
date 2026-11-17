"""Finding the thing that was built.

Two failures lived here, and both reported that nothing had started while
the page loaded perfectly in a browser.
"""

import socket
import threading
from pathlib import Path

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
        log.write_text('{"message":"Dev server already running at http://localhost:5173 (pid 1)"}')
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

    def test_a_project_that_does_not_say_is_not_guessed_at(self, tmp_path):
        command, why = how_to_run(tmp_path)
        assert command == ""
        assert "does not say" in why
