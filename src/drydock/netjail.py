"""Closing the network around the engineer, on macOS, when asked.

Off unless `DRYDOCK_NETJAIL=1`. Nothing here runs otherwise.

The reason it exists is a thing that was demonstrated rather than
argued: the fence around a worker is a list of command names, and a list
of command names is not a network boundary. An engineer writes a test
file, the verifier runs the project's own test command, the file opens a
socket. No refused command appears anywhere in that, because none is
used. Measured: a `node --test` file resolving a public address under
the existing fence, with every network command still absent from the
allow-list.

So this closes it one level down, where the operating system can be made
to care. The engineer's worker, and every process it starts, runs under
a seatbelt profile that denies outbound connections - except to one port
on loopback, where a proxy accepts CONNECT to a short list of package
registries and refuses everything else.

WHAT THIS IS NOT, and the word "isolation" is wrong for it:

  DNS still leaves.  macOS resolves names through mDNSResponder over a
                     path `network-outbound` does not mediate, and
                     denying every `mach-lookup` does not stop it
                     either - both tried, both measured. A worker can
                     put data in a hostname label and the lookup carries
                     it off the machine. Slow, noisy, loggable, open.
  Registries are a   The proxy tunnels TLS to npmjs and the rest. What
  channel.           travels inside that tunnel is not visible to it. A
                     worker could publish a package, or put bytes in a
                     request path.
  seatbelt is        Apple deprecated `sandbox-exec`. It works today.
  deprecated.        Nothing promises it works next release.

And the compatibility cost it used to have, and how it was paid:
`drydock-look` could not work in here. It starts the project's dev server
and then connects to it, and that connection is loopback-to-loopback,
which this profile denies along with everything else. Narrowing the
allowance to just that port was tried and cannot be written: seatbelt
takes an exact port or a wildcard - no range, no pattern - the profile
is fixed when the worker execs while the port is chosen inside the jail
minutes later, nothing inside can widen it (a nested profile is refused
outright, not merely ignored), and there is no filter for whose process
is listening, so an allowed port would trust a leftover server from an
unrelated run. All four were measured. See
`TestWhySpecificLocalPortsCannotBeAllowed`.

So the port was not opened and the work moved instead, following
`drydock-web`: drydock holds the socket, the worker asks. The profile
names a second loopback port - the errand desk - and both it and the
proxy are sockets this process bound before writing the profile, which
is how "whose port is it" gets answered without a filter for it.

What crosses is a token and some routes. Which repository, which command
starts it, where the pictures go and how many looks are left were all
decided here when the token was issued; a worker that lies about any of
them is describing something this side never reads. The routes are
checked on both sides, because a check that only runs where the caller
runs is not a check. The token dies with the item.

The desk takes one verb and answers in text. It is not a proxy and not
a shell: no address and no command appears anywhere in what it accepts.

WHERE THE ENGINEER'S CODE RUNS, which is more places than the engineer:

The jail first went around one worker, and that was not the boundary.
The repository's build command, its test command and its dev server are
the engineer's code under other names, and four stations run them:

  engineer      the worker itself                        jailed
  verifier      the build preflight, the build, the      jailed
                suite - it runs the files the engineer
                just wrote
  analyst       the baseline build and suite, before     jailed
                any work
  preview       `npm run dev`, for as long as the         jailed
                looking takes

Measured before they were: with the jail on, an engineer wrote a test
file that opened a socket and the verifier's `npm test` carried the
connection through. The engineer's own shell was shut at the time.

They are marked at one place - `shell.run(untrusted=True)` - and asked
for rather than assumed, because the callers that must not have it run
through the same function: `git fetch`, `git push` and the rest are
drydock's own commands, and a jail there would take the network from the
only part of the program that needs it.

WHAT IS STILL OUTSIDE, named rather than implied:

  the browser.    Chrome renders the page, which means it runs the
                  repository's JavaScript with an ordinary network. It
                  is launched by this process, deliberately outside -
                  a headless browser that cannot reach the network
                  cannot load a font or a picture, and the point of
                  looking is to see what a visitor sees. What it is
                  given is a loopback URL and a profile directory; what
                  it reads back is a screenshot and a count.
  toolchain       `detect.installed` runs `node --version` and four
  probes.         like it, before any work exists. Fixed command names
                  from this program, not from the repository.
  everything      Off by default. With `DRYDOCK_NETJAIL` unset none of
  when it is      this applies and the stations run as they always did.
  off.

What it does buy: the demonstrated path is closed, every allowed
connection is named in a log, and anything else fails loudly rather than
succeeding quietly.

It never degrades. A jail that cannot be built raises; it does not hand
back an unjailed command and let a run believe it was confined. That
failure mode - the guard that silently is not there - is worse than no
guard, because somebody then trusts it.
"""

import contextlib
import ipaddress
import os
import platform
import secrets
import select
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

FLAG = "DRYDOCK_NETJAIL"

# The hosts a build genuinely needs. Suffix-matched on a label boundary,
# so `.npmjs.org` matches `registry.npmjs.org` and not `evil-npmjs.org`.
# Short on purpose: every entry is somewhere bytes could be put, and the
# list is the blast radius.
REGISTRIES = (
    ".npmjs.org",
    ".yarnpkg.com",
    "pypi.org",
    ".pythonhosted.org",
    ".golang.org",
    ".crates.io",
    ".maven.apache.org",
    ".nuget.org",
)

PROFILE = """(version 1)
(allow default)

;; Everything outbound is closed. The engineer's own code runs under
;; this, which is the point: a list of command names never saw the test
;; file that opened a socket.
(deny network-outbound)
(deny network-inbound)

;; Two ways out, both to sockets this process bound itself before the
;; profile was written - so "whose port is it" is answered by having
;; opened it, which is the one way seatbelt cannot answer. The first is
;; the dependency proxy. The second is where `drydock-look` sends its
;; request, because the looking happens out here where there is a
;; loopback to use.
(allow network-outbound (remote ip "localhost:{port}"))
(allow network-outbound (remote ip "localhost:{errand}"))

;; Not the network, and some toolchains need them.
(allow network-outbound (remote unix-socket))
(allow network-inbound (local ip "localhost:*"))
"""


class CannotJail(RuntimeError):
    """The jail could not be built, so the run must not pretend it was."""


def wanted() -> bool:
    return os.environ.get(FLAG, "") == "1"


# --------------------------------------------------------------------------
# The proxy
# --------------------------------------------------------------------------


def _permitted(host: str) -> bool:
    """The host, or a subdomain of it. Never a name that merely ends in it.

    The first version matched by suffix against the list as written, and
    `pypi.org` is in it without a leading dot - so `notpypi.org` ends
    with `pypi.org` and was allowed. Caught by its own test before
    anything ran. Every entry is normalised to a bare domain here and
    matched on a label boundary, so the list cannot be made unsafe by
    how somebody spells an entry in it.
    """
    host = host.lower().rstrip(".")
    if not host:
        return False
    for rule in REGISTRIES:
        bare = rule.lower().strip().lstrip(".")
        if host == bare or host.endswith("." + bare):
            return True
    return False


def _public(host: str) -> tuple[bool, str]:
    """Resolve here, and refuse anything landing off the open internet.

    Here rather than in the worker: the jail has no resolver it may use,
    so a name is only ever turned into an address on this side, by code
    that then checks what it got.
    """
    try:
        found = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:
        return False, f"{host} does not resolve ({exc})"
    for info in found:
        where = info[4][0]
        ip = ipaddress.ip_address(where)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"{host} resolves to {where}, which is not public"
    return True, found[0][4][0]


REFUSAL = (
    "{why}\n\n"
    "This run has the network closed except for package registries. If "
    "the item needs something else from the internet, say so in your "
    "report rather than working around it.\n"
)


class _Through(socketserver.BaseRequestHandler):
    """CONNECT to a registry, on 443, and nothing else.

    Deliberately not a forward proxy: a plain GET would make this an
    open relay for anything that speaks HTTP. Deliberately not
    port-agnostic: CONNECT to 22 is how a proxy becomes an SSH tunnel.
    """

    def handle(self) -> None:
        sock = self.request
        sock.settimeout(20)
        try:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 8192:
                chunk = sock.recv(1024)
                if not chunk:
                    return
                head += chunk
        except OSError:
            return

        parts = head.split(b"\r\n", 1)[0].decode("latin-1").split()
        if len(parts) < 2:
            return self._no(sock, 400, "that is not a request this understands")
        method, target = parts[0].upper(), parts[1]

        if method != "CONNECT":
            self.server.noted.append(("refused", f"{method} {target[:60]}"))
            return self._no(
                sock,
                403,
                f"{method} is not forwarded. This tunnels CONNECT to a "
                "package registry and is not a general web proxy.",
            )
        host, _, port = target.rpartition(":")
        host = host.strip("[]")
        if port != "443":
            self.server.noted.append(("refused", f"CONNECT {target} (port)"))
            return self._no(
                sock, 403, f"port {port or '?'} is not open from here. Only 443."
            )
        if not _permitted(host):
            self.server.noted.append(("refused", f"CONNECT {target} (host)"))
            return self._no(
                sock,
                403,
                f"{host} is not a package registry this run may reach. "
                f"Allowed: {', '.join(REGISTRIES)}.",
            )
        ok, where = _public(host)
        if not ok:
            self.server.noted.append(("refused", f"CONNECT {target} ({where})"))
            return self._no(sock, 403, where)

        try:
            out = socket.create_connection((where, 443), timeout=20)
        except OSError as exc:
            self.server.noted.append(("failed", f"{host}: {exc}"))
            return self._no(sock, 502, f"{host} did not answer: {exc}")

        self.server.noted.append(("allowed", f"CONNECT {host}:443 -> {where}"))
        sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        self._pipe(sock, out)

    @staticmethod
    def _no(sock, code: int, why: str) -> None:
        body = REFUSAL.format(why=why).encode()
        with contextlib.suppress(OSError):
            sock.sendall(
                b"HTTP/1.1 %d Forbidden\r\nContent-Type: text/plain\r\n"
                b"Content-Length: %d\r\nConnection: close\r\n\r\n%s"
                % (code, len(body), body)
            )

    @staticmethod
    def _pipe(a, b) -> None:
        a.settimeout(None)
        b.settimeout(None)
        try:
            while True:
                ready, _, _ = select.select([a, b], [], [], 180)
                if not ready:
                    return
                for who in ready:
                    data = who.recv(65536)
                    if not data:
                        return
                    (b if who is a else a).sendall(data)
        except OSError:
            return
        finally:
            for s in (a, b):
                with contextlib.suppress(OSError):
                    s.close()


class _Proxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    noted: list


_RUNNING: _Proxy | None = None
_LOCK = threading.Lock()


def proxy() -> _Proxy:
    """The one dependency proxy for this process, started on first use.

    Loopback only. A proxy on 0.0.0.0 is a proxy for the local network,
    and the jail is the only thing that should be able to reach it.
    """
    global _RUNNING
    with _LOCK:
        if _RUNNING is None:
            server = _Proxy(("127.0.0.1", 0), _Through)
            server.noted = []
            threading.Thread(target=server.serve_forever, daemon=True).start()
            _RUNNING = server
        return _RUNNING


def allowed_so_far() -> list:
    """What the proxy has been asked for. For the record and the report."""
    return list(proxy().noted) if _RUNNING is not None else []


# --------------------------------------------------------------------------
# The jail
# --------------------------------------------------------------------------


def possible() -> str:
    """Empty if a jail can be built here, otherwise why it cannot."""
    if platform.system() != "Darwin":
        return (
            f"{FLAG}=1 was set and this is {platform.system()}, not macOS. "
            "This prototype is seatbelt and nothing else; there is no "
            "Linux implementation yet."
        )
    if not shutil.which("sandbox-exec"):
        return f"{FLAG}=1 was set and `sandbox-exec` is not on this machine."
    return ""


# --------------------------------------------------------------------------
# The errand desk
# --------------------------------------------------------------------------


ERRANDS: dict[str, object] = {}
_DESK: socketserver.ThreadingTCPServer | None = None
_DESK_LOCK = threading.Lock()


class _Errand(socketserver.BaseRequestHandler):
    """One request, one verb, and the worker names no path and no command.

    It sends a token and some routes. What repository that token belongs
    to, where the pictures go and what command starts the project are all
    decided here, from what was written down when the token was issued.
    A worker that lies about any of it is describing something this side
    never reads.
    """

    def handle(self) -> None:
        sock = self.request
        sock.settimeout(600)
        try:
            said = b""
            while b"\n" not in said and len(said) < 4096:
                chunk = sock.recv(512)
                if not chunk:
                    return
                said += chunk
        except OSError:
            return
        answer = self._answer(said.split(b"\n", 1)[0].decode("utf-8", "replace"))
        with contextlib.suppress(OSError):
            sock.sendall(answer.encode() + b"\n\x00")

    @staticmethod
    def _answer(line: str) -> str:
        from .route import is_route

        parts = line.split()
        if len(parts) < 2 or parts[0] != "LOOK":
            return "NOT LOOKED\n  that is not a request this desk takes"
        token, routes = parts[1], parts[2:]
        errand = ERRANDS.get(token)
        if errand is None:
            # Not "wrong token" - a worker that can enumerate is a worker
            # that can find one. Nothing here says which part was wrong.
            return "NOT LOOKED\n  this request was not recognised"
        # Routes are checked again on this side. The worker checked them
        # too, and a check that only runs where the caller runs is not a
        # check.
        for route in routes:
            if not is_route(route):
                return f"NOT LOOKED\n  {route!r} is not a path on this project"
        return errand(routes)


def desk() -> socketserver.ThreadingTCPServer:
    """The one errand desk for this process, bound on first use."""
    global _DESK
    with _DESK_LOCK:
        if _DESK is None:
            server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Errand)
            server.daemon_threads = True
            server.allow_reuse_address = True
            threading.Thread(target=server.serve_forever, daemon=True).start()
            _DESK = server
        return _DESK


def an_errand(doing) -> str:
    """Register one piece of privileged work and return its token.

    The token is the whole of the worker's authority: it names one
    repository, one item and one budget, it was issued here, and it is
    forgotten when the item is.
    """
    token = secrets.token_urlsafe(24)
    ERRANDS[token] = doing
    return token


def forget(token: str) -> None:
    ERRANDS.pop(token, None)


def around(command: list[str], env: dict) -> tuple[list[str], dict]:
    """Wrap one command in the jail, and point it at the proxy.

    Raises `CannotJail` rather than returning the command unwrapped. A
    guard that quietly is not there is worse than none, because the run
    then reports a confinement it did not have.
    """
    why = possible()
    if why:
        raise CannotJail(why)

    port = proxy().server_address[1]
    errand = desk().server_address[1]
    try:
        where = Path(tempfile.mkdtemp(prefix="drydock-netjail-")) / "profile.sb"
        where.write_text(PROFILE.format(port=port, errand=errand))
    except OSError as exc:
        raise CannotJail(f"the sandbox profile could not be written: {exc}") from exc

    through = f"http://127.0.0.1:{port}"
    env = {
        **env,
        # Proxy-aware clients reach the registries. Everything else finds
        # the network closed, which is the whole point.
        "HTTPS_PROXY": through,
        "https_proxy": through,
        "HTTP_PROXY": through,
        "http_proxy": through,
        "npm_config_proxy": through,
        "npm_config_https_proxy": through,
        "NO_PROXY": "",
        # So a worker can see it is in one without being told twice.
        "DRYDOCK_NETJAIL_PORT": str(port),
        # Where to send a look. The token that goes with it is added per
        # item, by whoever registered the errand.
        "DRYDOCK_LOOK_VIA": str(errand),
    }
    return ["sandbox-exec", "-f", str(where), *command], env


def said() -> str:
    """One line for the feed, so a jailed run says so out loud."""
    return (
        "the network is closed for the engineer: package registries only, "
        "through a proxy. DNS and the registries themselves are still "
        "channels - this is not isolation."
    )


if __name__ == "__main__":  # pragma: no cover - a hand check, not a test
    print(possible() or f"a jail can be built here; proxy on {proxy().server_address}")
    sys.exit(0)
