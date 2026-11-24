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
from typing import ClassVar

import pytest

from drydock import engineer, engines, look, netjail, preview, shell

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

    def test_drydock_web_never_wraps_anything_itself(self):
        """The validated path is the same code on both sides of the
        desk. It knows nothing about the jail and builds no sandbox: it
        is either run by the worker, when nothing is closed, or by
        drydock, when the worker's network is."""
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

    def test_the_profile_allows_exactly_two_loopback_ports(self):
        """It was one. It is two now, and both are sockets drydock bound
        itself before writing the profile - which is how "whose port is
        it" gets answered without a filter for it. The preview's port is
        still not among them, and that is why the looking moved out
        instead of the port being opened."""
        out = [
            line
            for line in netjail.PROFILE.splitlines()
            if line.startswith("(allow network-outbound (remote ip")
        ]
        assert len(out) == 2
        assert '(remote ip "localhost:{port}")' in netjail.PROFILE
        assert '(remote ip "localhost:{errand}")' in netjail.PROFILE
        assert '(allow network-outbound (remote ip "localhost:*"))' not in (
            netjail.PROFILE
        )

    def test_the_ports_are_drydocks_own_and_no_others(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        command, env = netjail.around(["echo"], {})
        profile = Path(command[2]).read_text()
        port, errand = env["DRYDOCK_NETJAIL_PORT"], env["DRYDOCK_LOOK_VIA"]
        out = [
            line
            for line in profile.splitlines()
            if line.startswith("(allow network-outbound (remote ip")
        ]
        assert len(out) == 2
        assert f'"localhost:{port}"' in profile
        assert f'"localhost:{errand}"' in profile
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


# --------------------------------------------------------------------------
# The errand desk: the looking moved out, the authority did not
# --------------------------------------------------------------------------


class TestTheWorkerAsksRatherThanDoes:
    """`drydock-look` could not work inside the jail, because starting a
    project and then connecting to it is loopback to loopback. Seatbelt
    cannot be told to allow one dynamic port belonging to one process,
    so the port was not opened - the work moved instead.

    The split follows `drydock-web`: drydock holds the socket, the worker
    asks. What crosses is a token and some routes. Which repository,
    which command starts it, where the pictures go and how many looks are
    left were all decided on this side when the token was issued.
    """

    def test_the_worker_sends_routes_and_a_token_and_nothing_else(self):
        source = inspect.getsource(look._by_errand)
        assert '" ".join(["LOOK", token, *paths])' in source
        for naming in ("DRYDOCK_ROOT", "build_command", "live.url", "where"):
            assert naming not in source

    def test_the_repository_comes_from_the_token(self):
        """A closure, not a field in the request. A worker that lies
        about the path is describing something this side never reads."""
        source = inspect.getsource(engines._an_errand_for)
        assert "def doing(routes: list[str]) -> str:" in source
        assert 'privileged(list(routes) or ["/"]' in source
        assert "repo" in source

    def test_an_unknown_token_is_refused(self):
        assert "this request was not recognised" in netjail._Errand._answer(
            "LOOK nope /"
        )

    def test_a_missing_token_is_refused(self):
        assert "not recognised" in netjail._Errand._answer("LOOK /")

    def test_the_refusal_does_not_say_which_part_was_wrong(self):
        """A worker that can tell "no such token" from "bad route" can
        enumerate."""
        said = netjail._Errand._answer("LOOK nope /")
        for leaking in ("token", "expired", "unknown", "forbidden"):
            assert leaking not in said.lower()

    @pytest.mark.parametrize("verb", ["RUN", "EXEC", "GET", "SHELL", "", "look"])
    def test_only_one_verb(self, verb):
        assert "not a request this desk takes" in netjail._Errand._answer(
            f"{verb} token /"
        )

    def test_it_is_not_a_shell(self):
        source = inspect.getsource(netjail._Errand._answer)
        for running in ("subprocess", "Popen", "system(", "eval(", "exec("):
            assert running not in source

    def test_it_is_not_a_proxy(self):
        """One verb, one answer, no address anywhere in it."""
        source = inspect.getsource(netjail._Errand._answer)
        assert "CONNECT" not in source
        assert "create_connection" not in source


class TestWhatTheDeskRefusesToLookAt:
    def _desk(self, monkeypatch, routes):
        seen = {}

        def doing(routes):
            seen["r"] = routes
            return "LOOKED"

        monkeypatch.setitem(netjail.ERRANDS, "tok", ("LOOK", doing))
        said = netjail._Errand._answer("LOOK tok " + " ".join(routes))
        return said, seen

    @pytest.mark.parametrize(
        "route",
        [
            "https://evil.test/",
            "http://localhost:8400/",
            "//evil.test/x",
            "/../../etc/passwd",
            "/..",
            "/a%2e%2e/b",
            "/x;",
            "/a b",
            "file:///etc/passwd",
            "rooms",
        ],
    )
    def test_anything_that_is_not_a_route(self, route, monkeypatch):
        said, seen = self._desk(monkeypatch, [route])
        assert "NOT LOOKED" in said
        assert "not a path on this project" in said
        assert "r" not in seen, "the errand ran despite a bad route"

    def test_one_bad_route_refuses_the_whole_request(self, monkeypatch):
        said, seen = self._desk(monkeypatch, ["/", "/../etc"])
        assert "NOT LOOKED" in said
        assert "r" not in seen

    def test_good_routes_are_passed_through(self, monkeypatch):
        said, seen = self._desk(monkeypatch, ["/", "/rooms"])
        assert said == "LOOKED"
        assert seen["r"] == ["/", "/rooms"]

    def test_the_check_runs_on_both_sides(self):
        """The worker checks too. A check that only runs where the caller
        runs is not a check."""
        assert "is_route" in inspect.getsource(netjail._not_asked)
        assert "is_route" in inspect.getsource(look.main)


class TestTheTokenIsScopedAndTemporary:
    def test_a_token_is_long_enough_not_to_be_guessed(self):
        token = netjail.an_errand(lambda r: "")
        assert len(token) >= 24
        netjail.forget(token)

    def test_two_errands_do_not_share_one(self):
        a = netjail.an_errand(lambda r: "a")
        b = netjail.an_errand(lambda r: "b")
        assert a != b
        assert netjail._Errand._answer(f"LOOK {a} /") == "a"
        assert netjail._Errand._answer(f"LOOK {b} /") == "b"
        netjail.forget(a)
        netjail.forget(b)

    def test_forgetting_one_revokes_it(self):
        token = netjail.an_errand(lambda r: "done")
        assert netjail._Errand._answer(f"LOOK {token} /") == "done"
        netjail.forget(token)
        assert "not recognised" in netjail._Errand._answer(f"LOOK {token} /")

    def test_the_item_forgets_its_token(self):
        """A worker holding one after its turn would hold authority over
        a repository it no longer has."""
        source = inspect.getsource(engines.ClaudeCodeEngine.work)
        assert "netjail.forget(token)" in source

    def test_it_is_only_issued_when_the_item_may_look(self):
        source = inspect.getsource(engines.ClaudeCodeEngine.work)
        at = source.index("netjail.an_errand")
        assert "if looks > 0 and look_key:" in source[at - 160 : at]


class TestTheSecondPortIsDrydocksOwn:
    def test_the_profile_names_both_and_only_both(self):
        assert netjail.PROFILE.count("(allow network-outbound (remote ip") == 2
        assert '"localhost:{port}"' in netjail.PROFILE
        assert '"localhost:{errand}"' in netjail.PROFILE
        assert '(allow network-outbound (remote ip "localhost:*"))' not in (
            netjail.PROFILE
        )

    def test_both_are_bound_before_the_profile_is_written(self):
        """This is what answers the question seatbelt cannot: whose port
        is it. Both were opened here, by this process, before the worker
        was told their numbers."""
        source = inspect.getsource(netjail.around)
        assert source.index("proxy()") < source.index("write_text")
        assert source.index("desk()") < source.index("write_text")

    def test_the_worker_is_told_where_to_ask(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        _command, env = netjail.around(["echo"], {})
        assert env["DRYDOCK_LOOK_VIA"] == str(netjail.desk().server_address[1])

    def test_the_desk_listens_on_loopback_only(self):
        source = inspect.getsource(netjail.desk)
        assert 'ThreadingTCPServer(("127.0.0.1", 0), _Errand)' in source


class TestTheLocalPathIsUnchanged:
    """Netjail is off by default, and with it off nothing about looking
    is different: the same command, run by the worker, doing the work
    where it always did."""

    def test_the_command_is_the_same(self):
        from drydock.route import LOOK as NAME

        assert NAME == "drydock-look"

    def test_it_does_the_work_itself_when_nothing_is_closed(self):
        source = inspect.getsource(look.main)
        assert "if via and token:" in source
        assert "said = privileged(paths, budget, where)" in source

    def test_the_budget_is_counted_once(self):
        """When the looking is delegated the tally belongs to the other
        side. Two counts of one budget is no budget."""
        source = inspect.getsource(look.main)
        assert source.index("if via and token:") < source.index("budget = _asked_for()")

    def test_the_same_code_writes_both_answers(self):
        """The worker prints what came back without interpreting it, so
        a delegated look and a local one read identically."""
        source = inspect.getsource(look._by_errand)
        assert "decode" in source
        # It writes one refusal of its own, for a desk that did not
        # answer. Everything else it prints came from the other side
        # untouched.
        for parsing in ("MEASURED", "PICTURES", "ROUTES", "json.", "split('\\n')"):
            assert parsing not in source


# --------------------------------------------------------------------------
# The stations that run the engineer's code
# --------------------------------------------------------------------------


class TestEveryPlaceTheRepositorysOwnCodeRuns:
    """The jail used to go around one worker. But the engineer's code is
    not only run by the engineer: the verifier runs the suite, the
    analyst runs the baseline, the preview runs the dev server. Those
    were open, and measured open - a test file that opened a socket got
    through `npm test` while the engineer's own shell was shut.

    So `untrusted` is asked for at the one chokepoint, and these pin
    that every caller which hands over a command from the repository
    asks for it.
    """

    REPOSITORYS: ClassVar[dict[str, int]] = {
        "verify.py": 3,  # the build preflight, the build, the suite
        "analyst.py": 2,  # the baseline build and the baseline suite
        "tools.py": 1,  # the build the engineer may ask for by name
    }

    @pytest.mark.parametrize("module,how_many", sorted(REPOSITORYS.items()))
    def test_the_command_from_the_repository_is_marked(self, module, how_many):
        source = Path("src/drydock") / module
        text = source.read_text()
        runs = text.count("check(") + text.count("run(")
        marked = text.count("untrusted=True")
        assert marked == how_many, f"{module}: {marked} marked of {runs} calls"

    # Drydock's own git, run through the same function. A jail here
    # would take the network from `git push`, which is the one command
    # in the program that needs it.
    @pytest.mark.parametrize("module", ["repo.py", "workspace.py"])
    def test_drydocks_own_commands_are_not_marked(self, module):
        text = (Path("src/drydock") / module).read_text()
        assert "untrusted" not in text

    def test_git_push_goes_through_the_same_door(self):
        """If this stops being true the reason the flag is asked for
        rather than defaulted has gone, and so has the care."""
        from drydock import publish, repo

        assert "run(" in inspect.getsource(repo)
        assert "untrusted" not in inspect.getsource(publish)

    def test_nothing_is_jailed_unless_it_says_so(self, monkeypatch):
        monkeypatch.setenv(netjail.FLAG, "1")
        seen = []
        monkeypatch.setattr(netjail, "around", lambda a, e: seen.append(a) or (a, e))
        shell.run("true", Path.cwd())
        assert seen == []

    def test_and_it_is_jailed_when_it_does(self, monkeypatch):
        monkeypatch.setenv(netjail.FLAG, "1")
        seen = []
        monkeypatch.setattr(netjail, "around", lambda a, e: seen.append(a) or (a, e))
        shell.run("true", Path.cwd(), untrusted=True)
        assert seen == [["true"]]

    def test_the_flag_still_decides(self, monkeypatch):
        """Marked untrusted and the jail switched off is an ordinary
        run. The mark says what the command is, not that it is confined."""
        monkeypatch.delenv(netjail.FLAG, raising=False)
        seen = []
        monkeypatch.setattr(netjail, "around", lambda a, e: seen.append(a) or (a, e))
        shell.run("true", Path.cwd(), untrusted=True)
        assert seen == []


class TestThePreviewServerIsTheEngineersCodeToo:
    """`npm run dev` is a long-lived process out of the repository's own
    package.json, and before this it was the widest hole of the lot: not
    one command but a server, running for as long as the looking takes."""

    def test_it_is_spelled_so_it_can_be_wrapped(self):
        """It used to be `shell=True`, which hands the string to a shell
        this program never sees and cannot put a sandbox in front of."""
        source = inspect.getsource(preview)
        assert 'args = ["/bin/sh", "-c", command]' in source
        # As a keyword, not as the word in the comment explaining why it
        # is no longer passed.
        for shape in ("shell=True,", "shell=True)", "shell=True\n"):
            assert shape not in source

    def test_the_jail_goes_around_it(self):
        source = inspect.getsource(preview)
        assert "args, started_with = netjail.around(args, started_with)" in source

    def test_and_the_errand_token_is_taken_off_it(self):
        """The dev server is the engineer's code. Handing it the token
        that reaches drydock's own privileged looking would undo the
        separation the delegation exists for."""
        source = inspect.getsource(preview)
        wrapped = source.index("netjail.around(args, started_with)")
        popped = source.index("started_with.pop(authority, None)")
        # Counting from the pop, because `subprocess.Popen` is written
        # once more further up as the type of the field it is kept in.
        assert wrapped < popped < source.index("subprocess.Popen(", popped)


@pytest.mark.skipif(
    platform.system() != "Darwin" or not netjail.shutil.which("sandbox-exec"),
    reason="seatbelt is macOS only",
)
class TestOnThisMachineTheStationsAreClosedToo:
    def test_an_untrusted_command_cannot_open_a_socket(self, monkeypatch, tmp_path):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        monkeypatch.setenv(netjail.FLAG, "1")
        script = tmp_path / "reach.py"
        script.write_text(TRY_A_SOCKET)
        said = shell.check(
            "reach",
            f"{sys.executable} {script}",
            tmp_path,
            timeout=30,
            untrusted=True,
        )
        assert said.detail.strip() == "REFUSED"

    def test_and_drydocks_own_still_can(self, monkeypatch, tmp_path):
        """The same script, the same jail switched on, run as drydock's
        own command. If this were refused too, `git push` would be."""
        monkeypatch.setattr(netjail, "possible", lambda: "")
        monkeypatch.setenv(netjail.FLAG, "1")
        script = tmp_path / "reach.py"
        script.write_text(TRY_A_SOCKET)
        said = shell.check("reach", f"{sys.executable} {script}", tmp_path, timeout=30)
        # Not "ALLOWED": nothing answers at TEST-NET-3. What says the
        # sandbox was absent is that the refusal came from the network
        # and not from the kernel.
        assert said.detail.strip() == "NOT-REFUSED"


# --------------------------------------------------------------------------
# The second verb: fetching, when the worker cannot reach the network
# --------------------------------------------------------------------------


class TestWikimediaIsNotOnTheProxysList:
    """The jail's proxy exists for package registries. The reason
    `drydock-web` goes over the desk instead of through it is that a
    tunnel to a picture host is a tunnel, and the list is the blast
    radius."""

    @pytest.mark.parametrize(
        "host", ["commons.wikimedia.org", "upload.wikimedia.org", "wikimedia.org"]
    )
    def test_it_is_not_permitted_through_the_tunnel(self, host):
        assert netjail._permitted(host) is False

    def test_the_list_is_still_only_registries(self):
        for entry in netjail.REGISTRIES:
            assert "wikimedia" not in entry
            assert "wikipedia" not in entry


class TestOneDeskTwoAuthorities:
    def test_both_verbs_are_named(self):
        assert set(netjail.VERBS) == {"LOOK", "WEB"}

    def test_each_wears_its_own_heading(self):
        """A worker reads the heading to tell "refused" from "nothing
        found". The wrong one reads as an answer."""
        assert netjail.VERBS["LOOK"] == "NOT LOOKED"
        assert netjail.VERBS["WEB"] == "NOT FETCHED"

    def test_a_token_is_issued_for_one_verb(self):
        token = netjail.an_errand(lambda rest: "DONE", verb="WEB")
        try:
            assert netjail.ERRANDS[token][0] == "WEB"
        finally:
            netjail.forget(token)

    def test_a_verb_the_desk_does_not_take_is_not_issuable(self):
        with pytest.raises(ValueError):
            netjail.an_errand(lambda rest: "DONE", verb="SHELL")

    @pytest.mark.parametrize("issued,asked", [("WEB", "LOOK"), ("LOOK", "WEB")])
    def test_one_cannot_be_spent_on_the_other(self, issued, asked, monkeypatch):
        ran = []
        token = netjail.an_errand(lambda rest: ran.append(rest) or "DONE", verb=issued)
        try:
            said = netjail._Errand._answer(f"{asked} {token} find hotel")
        finally:
            netjail.forget(token)
        assert "this request was not recognised" in said
        assert ran == []

    def test_a_forgotten_token_is_no_token(self):
        """Authorization dies with the item. A worker that kept one
        would hold it after its turn had ended."""
        token = netjail.an_errand(lambda rest: "DONE", verb="WEB")
        netjail.forget(token)
        assert "not recognised" in netjail._Errand._answer(f"WEB {token} find hotel")

    def test_the_run_forgets_every_token_it_issued(self):
        source = inspect.getsource(engines)
        assert "for token in tokens:" in source
        assert "netjail.forget(token)" in source
        assert source.count("tokens.append(token)") == 2


class TestWhatTheDeskWillNotFetch:
    """What crosses is one of `drydock-web`'s own named operations. Not
    a host this side chose, not a command, not a shell."""

    def _ask(self, rest):
        ran = []
        token = netjail.an_errand(lambda got: ran.append(got) or "FETCHED", verb="WEB")
        try:
            said = netjail._Errand._answer(f"WEB {token} {rest}")
        finally:
            netjail.forget(token)
        return said, ran

    @pytest.mark.parametrize(
        "rest,why",
        [
            ("curl https://evil.test", "not something this does"),
            ("sh -c ls", "not something this does"),
            ("get http://evil.test/x public/a.jpg", "not an https address"),
            ("get file:///etc/passwd public/a.jpg", "not an https address"),
            ("get https://ok.test/a.jpg /etc/passwd", "not a path inside this project"),
            ("get https://ok.test/a.jpg ../../x.jpg", "not a path inside this project"),
            ("get https://ok.test/a.jpg ~/x.jpg", "not a path inside this project"),
            ("get https://ok.test/a.jpg", "get takes an address and a path"),
            ("read https://a.test/1 https://a.test/2", "read takes one address"),
            ("read notanaddress", "not an https address"),
            ("find", "say what to look for"),
            ("have", "reads this project's own files"),
        ],
    )
    def test_it_is_refused_before_anything_is_asked_for(self, rest, why):
        said, ran = self._ask(rest)
        assert said.startswith("NOT FETCHED")
        assert why in said
        assert ran == [], "the errand ran despite a refused request"

    @pytest.mark.parametrize("verb", ["find", "get", "read"])
    def test_the_three_that_need_the_network_are_the_three_it_takes(self, verb):
        from drydock import outside

        assert verb in outside.ASKABLE

    def test_and_have_is_not_one_of_them(self):
        """It reads the project's own directory and reaches nothing, so
        it works inside the jail and costs no fetch."""
        from drydock import outside

        assert "have" not in outside.ASKABLE

    def test_a_search_cannot_be_made_arbitrarily_long(self):
        from drydock import outside

        said, ran = self._ask("find " + " ".join(["x"] * 40))
        assert f"{outside.MOST_WORDS} is the most" in said
        assert ran == []

    def test_a_good_request_reaches_the_errand_unchanged(self):
        said, ran = self._ask("find art deco facade")
        assert said == "FETCHED"
        assert ran == [["find", "art", "deco", "facade"]]


class TestTheCheckRunsOnBothSidesForFetchingToo:
    def test_the_worker_checks_and_so_does_the_desk(self):
        from drydock import outside

        assert "not_permitted" in inspect.getsource(netjail._not_asked)
        # The worker's own `main` refuses an unknown verb before it ever
        # reaches a socket.
        assert '"have", "find", "get", "read"' in inspect.getsource(outside.main)

    def test_the_privileged_side_runs_drydock_webs_own_main(self):
        """Not a second copy of the checks out here. The address check,
        the size caps, the licence recording and the tally are the ones
        that were already there."""
        from drydock import outside

        source = inspect.getsource(outside.privileged)
        assert "main(list(args))" in source
        for ours in ("urlopen", "socket.create_connection", "Refused"):
            assert ours not in source

    def test_the_delegation_happens_before_the_budget_is_read(self):
        """When the fetching happens elsewhere the budget belongs to the
        other side. Two counts of one budget is no budget."""
        from drydock import outside

        source = inspect.getsource(outside.main)
        assert source.index("if via and token") < source.index("budget = _budget()")

    def test_the_privileged_side_cannot_delegate_to_itself(self):
        from drydock import outside

        source = inspect.getsource(outside.privileged)
        assert 'os.environ.pop("DRYDOCK_WEB_VIA", None)' in source
        assert 'os.environ.pop("DRYDOCK_WEB_TOKEN", None)' in source

    def test_the_worker_is_told_where_to_send_a_fetch(self, monkeypatch):
        monkeypatch.setattr(netjail, "possible", lambda: "")
        _command, env = netjail.around(["echo"], {})
        assert env["DRYDOCK_WEB_VIA"] == str(netjail.desk().server_address[1])
        assert env["DRYDOCK_WEB_VIA"] == env["DRYDOCK_LOOK_VIA"]
