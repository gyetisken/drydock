"""What counts as a page of the project's own site, and nothing else.

One validator, imported by the two places that have to agree about it.

`drydock-look /rooms` was refused for two different reasons at once and
neither of them was wrong on its own. The confiner reads every argument
that is not a switch as a filesystem path, resolves it, and refuses
anything landing outside the project - so `/rooms` was read as the
directory `/rooms` at the root of the disk. The worker then tried
`drydock-look rooms/`, which the confiner allowed because it is inside
the project, and the tool refused because a route has to begin with `/`.
A door locked from both sides: four of one run's six look calls went on
it, and three of that site's four pages were never seen.

The fix is not to loosen the confiner. It is to let it know that one
argument of one command is a URL path rather than a file path - and to
decide that by the same rule the tool itself applies, so that a route the
confiner passes is exactly a route the tool accepts.

What is refused, and why each one matters:

  a scheme or a host     `http://elsewhere/` points the browser off this
                         machine, which is the only way this command
                         could reach anything but the preview
  `//host/path`          the same thing spelt as a protocol-relative URL,
                         which looks like a path and is not one
  a `..` segment         the comment above the old pattern said this was
                         refused and it was not: `.` and `/` were both in
                         the character class, so `/../../etc` matched. It
                         is an HTTP path and not a file read either way,
                         but a server asked to walk upwards is a server
                         being asked the wrong question
  a percent escape       in the path, because `%2e%2e` is `..` spelt so
                         that a character class cannot see it. Escapes
                         are still allowed in the query, where they are
                         ordinary and cannot become a segment
  backslashes, spaces,   each of them is a way for one string to be read
  control characters     as two things by two different readers
"""

import re

# The command this is all about, named once. `confine` is a hook that
# runs on every tool call and `engines` is the whole worker stack, so the
# name lives in the one module both can import for nothing.
LOOK = "drydock-look"

# The other tool this program lends a worker: the one that reaches outside
# the machine. Same shape as the look tool - drydock owns it, the hook
# allows it by name, and the worker never gets a shell that can reach the
# network. See `outside.py`.
WEB = "drydock-web"

# Deliberately strict and deliberately not a URL parser. Everything this
# has to admit is a path somebody can type: letters, digits, and the four
# punctuation marks that appear in real routes.
_SHAPE = re.compile(r"^/[A-Za-z0-9._~/-]*(\?[A-Za-z0-9._~=&+%-]*)?$")

# Segments that walk upwards, however the path is spelt around them.
_UPWARDS = re.compile(r"(^|/)\.\.(/|$)")


def is_route(said: str) -> bool:
    """Whether this is a page of the project's own site.

    False for everything else, including everything that is a filesystem
    path. A caller that gets False here must go on treating the argument
    the way it treated it before.
    """
    if not said or not isinstance(said, str):
        return False
    # Before the shape, because a string with a newline in it can match a
    # pattern that was written with one line in mind.
    if said != said.strip() or any(c in said for c in "\\ \t\r\n\0"):
        return False
    # A protocol-relative URL is a host, not a path, and it is the one
    # that reads as a path to everybody who is not a browser.
    if said.startswith("//"):
        return False
    if not _SHAPE.match(said):
        return False
    return not _UPWARDS.search(said.split("?", 1)[0])


def tidy(said: str) -> str:
    """The route as it should be asked for, or empty if it is not one."""
    return said if is_route(said) else ""


def slug(said: str) -> str:
    """A directory name for one route's pictures, or "" for the home page.

    The home page keeps the top of the look directory, because that is
    where everything that already reads pictures looks for them. Every
    other route gets a directory of its own, so photographing a second
    page does not delete the first one's.
    """
    kept = "".join(c if c.isalnum() else "-" for c in said.split("?", 1)[0].strip("/"))
    return kept.strip("-")


# An address the fetching tool may be pointed at. Shape only: whether it
# leads anywhere it should not is settled by `outside.py`, which resolves
# the host and checks every address it lands on. This is here because the
# confinement hook has to tell a URL from a file path before it resolves
# anything, and it may not import the fetching machinery to do it.
_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d{2,5})?(/[^\s]*)?$")


def is_url(said: str) -> bool:
    """Whether this is an https address and nothing else.

    http is refused along with everything else: a worker reading a page
    over a connection somebody can rewrite is reading whatever they wrote.
    """
    if not said or not isinstance(said, str):
        return False
    if said != said.strip() or any(c in said for c in "\\ \t\r\n\0"):
        return False
    if len(said) > 2000:
        return False
    return bool(_URL.match(said))
