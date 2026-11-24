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

And one compatibility cost, measured rather than expected:
`drydock-look` does not work in here. It starts the project's dev server
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

So a jailed run and a looked-at run are, for now, two different runs.

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

;; One way out: the dependency proxy on loopback.
(allow network-outbound (remote ip "localhost:{port}"))

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
    try:
        where = Path(tempfile.mkdtemp(prefix="drydock-netjail-")) / "profile.sb"
        where.write_text(PROFILE.format(port=port))
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
