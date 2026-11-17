"""Deciding what the thing looks like, before anyone builds it.

Nothing in this crew was responsible for that, which is why everything it
built looked the same: an architect picks a stack, a planner slices work, an
engineer writes code that passes tests. Default HTML passes every test there
is. "Make it nice" is not an item anybody can verify, so it never became one,
so it never happened.

This station makes the look a decision, taken once, written down, and handed
to the planner the way the shape is - so that "the hours block uses the type
scale and the card treatment" is a thing an item can say and a reviewer can
check.

It decides for this business, not in general. A Nolita trattoria and a tax
practice are not the same page with different words, and a palette chosen
from the first is wrong for the second.
"""

from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent, Tool
from .engines import ClaudeCodeEngine
from .skills import Skill, briefing

SYSTEM = """You decide how something looks, for one specific business, before
anyone writes a line of it.

You are not decorating. Every choice answers a question about who this is for
and what they came to do, and you say which question it answers. A palette
that could belong to any restaurant is a palette you have not chosen.

What good looks like, now:

- One idea carries the page. A single photographic or typographic gesture at
  the top, then quiet. Pages that shout in six places are read as cheap.
- Type does most of the work. A real typeface pairing, a scale with clear
  steps rather than six sizes within four pixels of each other, generous line
  height on body text, and headings tight enough to read as headings.
- Space is the design. Sections separated by room rather than by rules and
  boxes. If it looks sparse at desktop width it is probably right.
- Colour is used sparingly and on purpose: a ground, an ink, and one accent
  that means something. Gradients and shadows date a page faster than
  anything else.
- It has to hold up on a phone. Most people looking at a restaurant's site
  are standing outside it.

Say it in enough detail that an engineer who has never spoken to you builds
the right thing: the actual hex values, the actual font names from Google
Fonts, the actual scale in pixels or rem."""

PROMPT = """What is being built: {task}

{shape}

Decide the look. Be specific and be local to this business - its city, its
kind of room, who walks in. Draw the mark yourself as SVG; nothing is
downloaded and nothing is a stock icon."""


def _tool() -> Tool:
    return Tool(
        name="design_language",
        description="State how this should look.",
        schema={
            "type": "object",
            "properties": {
                "idea": {
                    "type": "string",
                    "description": (
                        "The one idea the whole thing hangs on, in a sentence, "
                        "and who it is for."
                    ),
                },
                "palette": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Named hex values as `name #rrggbb - what it is for`. "
                        "Four to six. A ground, an ink, one accent."
                    ),
                },
                "type_scale": {
                    "type": "string",
                    "description": (
                        "Typefaces by their Google Fonts names and the sizes "
                        "and line heights that go with them."
                    ),
                },
                "layout": {
                    "type": "string",
                    "description": (
                        "What is above the fold, what order the page runs in, "
                        "and how much room sits between sections."
                    ),
                },
                "logo_svg": {
                    "type": "string",
                    "description": (
                        "A complete <svg> element, drawn by you, that works at "
                        "28 pixels as well as 200. No external references."
                    ),
                },
                "logo_reasoning": {
                    "type": "string",
                    "description": "Why this mark and not another, in a sentence.",
                },
                "words": {
                    "type": "string",
                    "description": (
                        "How the copy sounds, with one example line that could "
                        "go on the page."
                    ),
                },
                "avoid": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific things that would make this generic.",
                },
            },
            "required": [
                "idea",
                "palette",
                "type_scale",
                "layout",
                "logo_svg",
                "logo_reasoning",
                "words",
                "avoid",
            ],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def decide(
    repo: Path,
    task: str,
    shape: str = "",
    skills: list[Skill] | None = None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "api",
    model: str = "opus",
) -> tuple[dict, object]:
    prompt = PROMPT.format(task=task, shape=shape or "")
    system = SYSTEM + briefing(skills or [], "design")

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=6).structured(
            repo,
            system,
            prompt,
            '{"idea": "...", "palette": ["..."], "type_scale": "...", '
            '"layout": "...", "logo_svg": "<svg ...>...</svg>", '
            '"logo_reasoning": "...", "words": "...", "avoid": ["..."]}',
            on_event=on_event,
            tools="",
            without="Bash Read Glob Grep Edit NotebookEdit WebFetch WebSearch Task",
        )
        return found, _Spend(dollars, turns)

    agent = Agent(
        name="Designer",
        model=API_MODEL.get(model, JUDGEMENT),
        system=system,
        tools=[],
        max_turns=2,
        budget=budget,
        on_event=on_event,
    )
    return agent.run(prompt, final_tool=_tool()), agent.usage


def as_briefing(found: dict) -> str:
    """What the planner and the engineer are held to."""
    if not found:
        return ""
    avoid = found.get("avoid") or []
    return (
        "\n\nHow this is to look. It was decided before anything was planned "
        "and it is not up for reinterpretation item by item; an item that "
        "renders anything renders it this way.\n\n"
        f"The idea: {found.get('idea', '')}\n\n"
        "Palette:\n"
        + "\n".join(f"- {c}" for c in found.get("palette", []))
        + f"\n\nType: {found.get('type_scale', '')}\n\n"
        f"Layout: {found.get('layout', '')}\n\n"
        f"Voice: {found.get('words', '')}\n\n"
        f"The mark is already drawn and is in `brand/logo.svg`. "
        f"{found.get('logo_reasoning', '')} Use it; do not redraw it.\n\n"
        "Specifically avoid:\n"
        + "\n".join(f"- {a}" for a in avoid)
        + "\n\nOne item near the start writes the stylesheet that holds the "
        "palette, the type scale and the spacing, and every later item uses "
        "it rather than inventing values of its own."
    )


def write_logo(repo: Path, found: dict) -> str:
    """Put the mark on disk so items can reference a file, not a description."""
    svg = (found.get("logo_svg") or "").strip()
    if not svg.startswith("<svg"):
        return ""
    brand = repo / "brand"
    brand.mkdir(exist_ok=True)
    (brand / "logo.svg").write_text(svg + "\n")
    return "brand/logo.svg"


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
