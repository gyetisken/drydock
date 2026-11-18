"""Whether the task already says what to build it with.

The Architect decides a toolchain for an empty repository. It is a station
like any other, which means it costs a worker: on a measured run it took
forty-one seconds to write "Node.js 20+, no framework, node:http and
node:test" for a task whose first line was "the stack is already decided:
use Node.js built-in modules and the built-in test runner".

That was a third of everything the run spent working. The floor for any
station here is about twenty-five seconds - a process, a system prompt,
a first token - so the saving is in not running one, not in making one
faster.

Deterministic on purpose, like `intent.py`: a model call to decide whether
a model call is needed costs the thing it is trying to save. And strict on
purpose, because the two mistakes are not equal. Running the Architect when
the task already settled the stack costs forty seconds. Skipping it when
the task did not leaves nobody deciding, and the Planner invents one
halfway through writing the plan.

So two signals are required, not one: a toolchain named specifically
enough to act on, and language that settles it rather than mentions it.
"""

import re
from dataclasses import dataclass

# Named specifically enough to build from. "JavaScript" is not here and
# "a web app" certainly is not: those name a world, not a toolchain.
NAMED = re.compile(
    r"""\b(
      node(?:\.?js)? | deno | bun
    | python | django | flask | fastapi
    | react | next(?:\.?js)? | astro | svelte(?:kit)? | vue | nuxt | remix
    | typescript
    | go(?:lang)? | rust | ruby\s+on\s+rails | rails
    | java | kotlin | spring\s+boot | \.net | c\#
    | express | hono | fastify
    | vite | tailwind
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# Language that settles a choice rather than mentioning one. "Build a Node
# API" names a thing; "the stack is already decided" ends an argument.
SETTLED = re.compile(
    r"""(
      \b(stack|toolchain|tooling|framework|language|runtime)\b
      [^.]{0,40}?\b(is|are|has been|was)\b[^.]{0,20}?\b(decided|chosen|set|fixed|settled|given)\b
    | \balready\s+(decided|chosen|settled|picked|fixed)\b
    | \b(use|using|build\s+(?:it\s+)?with|written\s+in|must\s+use|only\s+use)\b
      [^.]{0,30}?\b(node|deno|bun|python|django|flask|fastapi|react|next|astro|
        svelte|vue|nuxt|remix|typescript|go|rust|rails|java|kotlin|spring|
        \.net|express|hono|fastify|vite|tailwind)\b
    | \bdo\s+not\s+(choose|pick|decide|change)\s+(the\s+)?(stack|framework|toolchain)\b
    | \bno\s+(framework|dependencies|libraries)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class Settled:
    """Whether the task decided the stack, and what said so."""

    decided: bool
    why: str

    def __bool__(self) -> bool:
        return self.decided


def already_decided(task: str) -> Settled:
    """Whether this task settles its own toolchain.

    Both signals or neither. A task that names a toolchain without
    settling it - "a small Python script would be nice" - is a preference,
    and a task that settles without naming - "use whatever you decided
    last time" - settles nothing this can act on.
    """
    said = (task or "").strip()
    if not said:
        return Settled(False, "there is no task to read")

    named = NAMED.search(said)
    settled = SETTLED.search(said)
    if not named:
        return Settled(False, "the task does not name a toolchain")
    if not settled:
        return Settled(
            False,
            f"the task mentions {named.group(0)} but does not say it is decided",
        )
    return Settled(
        True,
        f"the task names {named.group(0)} and says it is settled: "
        f'"{_tidy(settled.group(0))}"',
    )


def _tidy(said: str) -> str:
    return re.sub(r"\s+", " ", said).strip()[:80]
