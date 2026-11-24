"""The network jail: off by default, loud when it cannot be built.

A prototype behind `DRYDOCK_NETJAIL=1`. What these pin is mostly about
what it must not do - run by default, wrap the wrong worker, or hand
back an unjailed command while a run believes it was confined.

The live end of it - that seatbelt actually refuses a socket - is
exercised by hand on macOS and reported, not asserted here: it needs the
network and a platform, and a test that quietly skips on CI is a test
that says nothing on the machine where it would matter.
"""

import inspect
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from drydock import engineer, engines, netjail

# One script, used twice: inside the jail it must be refused, outside it
# must not. 203.0.113.1 is TEST-NET-3 and answers nowhere, so what the
# two runs differ by is the sandbox and not the address.
# One script, run twice: inside the jail it must be refused, outside it
# must not. 203.0.113.1 is TEST-NET-3 and answers nowhere, so the only
# thing the two runs differ by is the sandbox rather than the address.
TRY_A_SOCKET = (
    "import socket\n"
    "try:\n"
    "    socket.create_connection(('203.0.113.1', 443), timeout=2)\n"
    "    print('ALLOWED')\n"
    "except PermissionError:\n"
    "    print('REFUSED')\n"
    "except OSError:\n"
    "    print('NOT-REFUSED')\n"
)


def flat(text: str) -> str:
    return " ".join(text.split())


# --------------------------------------------------------------------------
# Off unless asked
# --------------------------------------------------------------------------


class TestItIsOffByDefault:
    def test_nothing_turns_it_on_but_the_flag(self, monkeypatch):
        monkeypatch.delenv(netjail.FLAG, raising=False)
        assert netjail.wanted() is False

    @pytest.mark.parametrize("said", ["", "0", "true", "yes", "on", "2"])
    def test_only_the_exact_value_counts(self, said, monkeypatch):
        """A flag that turns on for "true" and "yes" and "on" is a flag
        somebody enables by accident."""
        monkeypatch.setenv(netjail.FLAG, said)
        assert netjail.wanted() is False

    def test_one_turns_it_on(self, monkeypatch):
        monkeypatch.setenv(netjail.FLAG, "1")
        assert netjail.wanted() is True

    def test_no_proxy_is_started_until_it_is_wanted(self):
        """Importing the module must not open a port."""
        source = Path("src/drydock/netjail.py").read_text()
        at = source.index("_RUNNING: _Proxy | None = None")
        assert "_RUNNING: _Proxy | None = None" in source[at : at + 60]
        assert "serve_forever" in source  # started inside proxy(), not at import


# --------------------------------------------------------------------------
# Only the engineer
# --------------------------------------------------------------------------


class TestOnlyTheEngineersWorker:
    def test_work_is_wrapped(self):
        source = inspect.getsource(engines.ClaudeCodeEngine.work)
        assert "if netjail.wanted():" in source
        assert "command, env = netjail.around(command, env)" in source

    def test_every_other_station_is_not(self):
        """`structured` is the analyst, the planner, the reviewer and the
        critic. None of them has a shell, so jailing them would buy
        nothing and give the planner a new way to fail."""
        source = inspect.getsource(engines.ClaudeCodeEngine.structured)
        assert "netjail" not in source

    def test_only_one_caller_of_the_wrapped_method(self):
        """If something else starts calling `work`, this stops being an
        engineer-only change and nobody would notice."""
        callers = [
            name
            for name in Path("src/drydock").glob("*.py")
            if ").work(" in name.read_text()
        ]
        assert [p.name for p in callers] == ["engineer.py"]

    def test_the_run_is_told(self):
        source = inspect.getsource(engines.ClaudeCodeEngine.work)
        assert 'on_event("tool", netjail.said())' in source


# --------------------------------------------------------------------------
# It never degrades quietly
# --------------------------------------------------------------------------


class TestAJailThatCannotBeBuiltRaises:
    def test_it_raises_rather_than_returning_the_command(self, monkeypatch):
        """The failure this exists to prevent: a run that reports a
        confinement it did not have."""
        monkeypatch.setattr(netjail, "possible", lambda: "no sandbox here")
        with pytest.raises(netjail.CannotJail) as refused:
            netjail.around(["echo", "hi"], {})
        assert "no sandbox here" in str(refused.value)

    def test_a_foreign_platform_is_named(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        why = netjail.possible()
        assert "not macOS" in why
        assert "no Linux implementation yet" in why

    def test_a_missing_sandbox_binary_is_named(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(netjail.shutil, "which", lambda name: None)
        assert "`sandbox-exec` is not on this machine" in netjail.possible()

    def test_a_profile_that_cannot_be_written_raises(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        monkeypatch.setattr(
            netjail.tempfile,
            "mkdtemp",
            lambda **kw: (_ for _ in ()).throw(OSError("full")),
        )
        with pytest.raises(netjail.CannotJail):
            netjail.around(["echo"], {})

    def test_nothing_anywhere_catches_it_into_a_fallback(self):
        """A `try` around the wrap that carried on would be the whole
        guarantee undone."""
        source = inspect.getsource(engines.ClaudeCodeEngine.work)
        at = source.index("netjail.around")
        window = source[at - 200 : at + 200]
        assert "except" not in window
        assert "try" not in window


# --------------------------------------------------------------------------
# What the profile says
# --------------------------------------------------------------------------


class TestTheProfile:
    def test_outbound_is_denied(self):
        assert "(deny network-outbound)" in netjail.PROFILE
        assert "(deny network-inbound)" in netjail.PROFILE

    def test_the_only_way_out_is_the_proxy(self):
        assert '(allow network-outbound (remote ip "localhost:{port}"))' in (
            netjail.PROFILE
        )

    def test_the_port_is_filled_in(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        command, env = netjail.around(["echo", "hi"], {})
        assert command[0] == "sandbox-exec"
        assert command[-2:] == ["echo", "hi"]
        profile = Path(command[2]).read_text()
        port = env["DRYDOCK_NETJAIL_PORT"]
        assert f'"localhost:{port}"' in profile
        assert "{port}" not in profile

    def test_the_proxy_is_pointed_at(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        _command, env = netjail.around(["echo"], {})
        through = env["HTTPS_PROXY"]
        assert through.startswith("http://127.0.0.1:")
        for name in ("https_proxy", "HTTP_PROXY", "npm_config_https_proxy"):
            assert env[name] == through
        assert env["NO_PROXY"] == ""

    def test_the_environment_it_was_given_survives(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        _command, env = netjail.around(["echo"], {"PATH": "/usr/bin", "MINE": "kept"})
        assert env["PATH"] == "/usr/bin"
        assert env["MINE"] == "kept"


# --------------------------------------------------------------------------
# The proxy is not a tunnel
# --------------------------------------------------------------------------


class TestWhatTheProxyAllows:
    @pytest.mark.parametrize(
        "host",
        [
            "registry.npmjs.org",
            "pypi.org",
            "files.pythonhosted.org",
            "proxy.golang.org",
            "static.crates.io",
        ],
    )
    def test_a_registry(self, host):
        assert netjail._permitted(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example.com",
            "evil-npmjs.org",
            "npmjs.org.evil.test",
            "pypi.org.evil.test",
            "notpypi.org",
            "",
            "localhost",
        ],
    )
    def test_anything_else(self, host):
        assert netjail._permitted(host) is False

    def test_the_match_is_on_a_label_boundary(self):
        """`evil-npmjs.org` ends with `npmjs.org` as a string and is not
        a subdomain of it. The leading dot is what makes the difference
        and it is easy to drop."""
        assert netjail._permitted("evil-npmjs.org") is False
        assert netjail._permitted("registry.npmjs.org") is True

    def test_a_name_resolving_inward_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            netjail.socket,
            "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))],
        )
        ok, why = netjail._public("registry.npmjs.org")
        assert ok is False
        assert "not public" in why

    def test_a_public_name_is_allowed(self, monkeypatch):
        monkeypatch.setattr(
            netjail.socket,
            "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("104.16.5.34", 443))],
        )
        ok, where = netjail._public("registry.npmjs.org")
        assert ok is True
        assert where == "104.16.5.34"

    def test_only_connect_and_only_443(self):
        source = inspect.getsource(netjail._Through.handle)
        assert 'if method != "CONNECT":' in source
        assert 'if port != "443":' in source
        assert "is not a general web proxy" in source

    def test_it_listens_on_loopback_only(self):
        source = inspect.getsource(netjail.proxy)
        assert '_Proxy(("127.0.0.1", 0), _Through)' in source

    def test_every_decision_is_kept(self):
        source = inspect.getsource(netjail._Through.handle)
        assert source.count("self.server.noted.append") >= 4
        assert "allowed" in source and "refused" in source


# --------------------------------------------------------------------------
# What is said about what it is not
# --------------------------------------------------------------------------


class TestItDoesNotClaimIsolation:
    def test_the_module_says_dns_still_leaves(self):
        said = flat(Path("src/drydock/netjail.py").read_text())
        assert "DNS still leaves" in said
        assert "put data in a hostname label and the lookup carries it off" in said

    def test_the_module_says_registries_are_a_channel(self):
        said = flat(Path("src/drydock/netjail.py").read_text())
        assert "travels inside that tunnel is not visible to it" in said

    def test_the_module_says_seatbelt_is_deprecated(self):
        said = flat(Path("src/drydock/netjail.py").read_text())
        assert "Apple deprecated `sandbox-exec`" in said

    def test_the_word_isolation_is_refused(self):
        said = flat(Path("src/drydock/netjail.py").read_text())
        assert 'the word "isolation" is wrong for it' in said

    def test_the_line_in_the_feed_says_so_too(self):
        said = flat(netjail.said())
        assert "this is not isolation" in said
        assert "package registries only" in said

    def test_the_engineer_is_told_the_same(self):
        said = flat(engineer.JAILED)
        assert "this is not isolation" in said
        assert "A hostname lookup still leaves this machine" in said


class TestWhatTheEngineerIsTold:
    def test_only_when_jailed(self):
        source = inspect.getsource(engineer.work)
        assert 'if netjail.wanted() and engine == "claude":' in source
        assert "briefed += JAILED" in source

    def test_the_errors_it_will_meet_are_named(self):
        said = flat(engineer.JAILED)
        for mangled in (
            "EPERM",
            "PermissionError",
            "ENOTFOUND",
            "Tunnel connection failed",
        ):
            assert mangled in said

    def test_it_says_the_machine_is_not_broken(self):
        said = flat(engineer.JAILED)
        assert "the machine is not broken and retrying will not help" in said

    def test_it_says_registries_still_work(self):
        said = flat(engineer.JAILED)
        assert "Package registries work" in said
        assert "you do not have to do anything for that" in said

    def test_it_forbids_working_around_it(self):
        """The failure this is written against: a worker reading a
        refusal as a broken machine and spending the item on it. One did
        exactly that with the command fence."""
        said = flat(engineer.JAILED)
        assert "Do not work around it" in said
        assert "do not weaken a test to make it pass" in said

    def test_it_says_what_to_do_instead(self):
        said = flat(engineer.JAILED)
        assert "say in your report what you could not reach" in said


class TestNothingElseChanged:
    def test_the_allow_list_is_untouched(self):
        from drydock.confine import ALLOWED

        for reaching in ("curl", "wget", "nc", "ssh"):
            assert reaching not in ALLOWED

    def test_the_approval_path_is_untouched(self):
        from drydock import session

        source = inspect.getsource(session.Session._after_plan)
        assert "if auto_run:" in source
        assert 'self.feed.emit("awaiting.approval")' in source

    def test_the_gates_are_untouched(self):
        from drydock import orchestrate

        assert orchestrate.GATES == ("verifier", "inspector", "reviewer", "critic")

    def test_drydock_web_is_outside_the_jail(self):
        """It runs in drydock's own process, not the worker's, so the
        validated path keeps working when the jail is on."""
        source = Path("src/drydock/outside.py").read_text()
        assert "netjail" not in source


@pytest.mark.skipif(
    platform.system() != "Darwin" or not netjail.shutil.which("sandbox-exec"),
    reason="seatbelt is macOS only",
)
class TestOnThisMachineItActuallyRefuses:
    """The one live check, and it needs no network to be meaningful:
    connecting to an address the sandbox denies fails whether or not
    anything is listening there."""

    def test_a_socket_to_a_denied_address_is_refused(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        command, env = netjail.around(
            [
                sys.executable,
                "-c",
                TRY_A_SOCKET,
            ],
            dict(os.environ),
        )
        said = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env, timeout=60
        )
        assert said.stdout.strip() == "REFUSED", said.stdout + said.stderr

    def test_the_same_connection_is_not_refused_without_the_jail(self):
        """So the test above is measuring the jail and not the address."""
        said = subprocess.run(
            [
                sys.executable,
                "-c",
                TRY_A_SOCKET,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "NOT-REFUSED" in said.stdout, said.stdout + said.stderr

    def test_a_jailed_command_still_runs(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        command, env = netjail.around(
            [sys.executable, "-c", "print('ran')"], dict(os.environ)
        )
        said = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env, timeout=60
        )
        assert said.stdout.strip() == "ran"

    def test_the_project_is_still_writable_from_inside(self, monkeypatch, tmp_path):
        """The jail is about the network. Taking the filesystem with it
        would break every item."""
        monkeypatch.setattr(netjail, "possible", lambda: "")
        target = tmp_path / "written.txt"
        command, env = netjail.around(
            [sys.executable, "-c", f"open({str(target)!r}, 'w').write('ok')"],
            dict(os.environ),
        )
        subprocess.run(
            command, check=False, capture_output=True, text=True, env=env, timeout=60
        )
        assert target.read_text() == "ok"


class TestWhySpecificLocalPortsCannotBeAllowed:
    """Why the jail allows one loopback port and not the preview's.

    Asked for: allow only the ports this run's preview server, browser
    and CDP connection need, and make sure the port belongs to the
    process it is supposed to. Measured against seatbelt, and it cannot
    be done - so it is written down here rather than quietly traded for
    opening all of localhost.

    The grammar, from `sandbox-exec` itself:

        (remote ip "localhost:9001")      accepted
        (remote ip "localhost:*")         accepted
        (remote ip "localhost:9001-9010") invalid port in network address
        (remote ip (regex #"localhost:9[0-9]+"))
                                          remote expects string argument
        (remote ip "127.0.0.1:9001")      host must be * or localhost
        ... (process-name "node")         unbound variable: process-name

    So the expressible universe is exact single ports or a wildcard.
    There is no range, no pattern, and no way to say whose port it is.

    Three things follow, and each on its own would be enough:

    1. The profile is fixed when the worker execs. The preview port is
       chosen minutes later, inside the jail, by `preview._free_port`.
    2. Nothing inside can widen it. A nested `sandbox-exec` does not
       merely fail to add permissions - it cannot be applied at all:
       `sandbox_apply: Operation not permitted`.
    3. Even with the port known, seatbelt would trust whatever is
       listening on it. On this machine that is not hypothetical: a
       leftover `astro dev` from an earlier run was holding 4321 while
       these were being measured.
    """

    def test_the_profile_allows_exactly_one_loopback_port(self):
        assert netjail.PROFILE.count("(allow network-outbound") == 2
        assert '(remote ip "localhost:{port}")' in netjail.PROFILE
        assert '(remote ip "localhost:*")' not in netjail.PROFILE

    def test_the_port_is_the_proxys_and_nothing_else(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        command, env = netjail.around(["echo"], {})
        profile = Path(command[2]).read_text()
        port = env["DRYDOCK_NETJAIL_PORT"]
        assert profile.count("allow network-outbound") == 2
        assert f'"localhost:{port}"' in profile
        assert env["HTTPS_PROXY"].endswith(":" + port)

    def test_the_preview_port_is_chosen_after_the_profile_is_written(self):
        """The ordering that makes a per-run allowance impossible: the
        jail is built around the worker, and the worker starts the
        preview later from inside it."""
        from drydock import preview

        source = inspect.getsource(preview.start)
        assert "port = _free_port()" in source

    def test_the_module_says_the_preview_does_not_work_jailed(self):
        said = flat(Path("src/drydock/netjail.py").read_text())
        assert "drydock-look" in said
        assert (
            "that connection is loopback-to-loopback, which this profile denies" in said
        )
