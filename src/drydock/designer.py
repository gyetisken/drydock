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

SYSTEM = """You have art-directed several hundred sites and you are directing
this one. You are not choosing colours. You are deciding what somebody sees
and in what order, and then writing it down precisely enough that an engineer
who has never spoken to you builds exactly that.

The failure to design against is not ugliness. It is the page that is a
single centred column of stacked text on one flat surface, where the only
hierarchy is font size and nothing composes. That page passes every test,
offends nobody, and was designed by nobody. Restraint is not the absence of
decisions; it is fewer decisions, made harder.

So every one of these has to have an answer, and "it is a clean column" is
not one:

**Composition.** Where does the eye land, where does it go second, and what
makes it go there. Name the structure: a grid and how many columns, where
the asymmetry is, what is flush and what is indented, what breaks the column
and why. A page where every block is the same width in the same place is a
document.

**Scale contrast.** State the ratio between the largest thing on the page
and the body text. Under about 4:1 nothing reads as a hierarchy; a real
display moment is usually 6:1 or more. Say what gets the top of that range
and what is deliberately quiet.

**At least one structural device, and at most two.** A full-bleed band of a
second ground. A two-column split where one side is sticky and one scrolls.
A rule that runs the measure. A figure that breaks its container. An index
down one edge. Name yours, say what it does, and say why this page needs it.

**Density.** Sections should not all breathe the same. A dense list beside
an airy opening is rhythm; the same spacing everywhere is wallpaper. Say
which sections are tight and which are open.

**Edges and surfaces.** How many planes does the page have - one ground, or
a ground and a raised surface? Where does an edge appear and what is it
made of? A page with exactly one surface and no edges anywhere has nothing
holding it together.

**One moment.** The single thing somebody would remember and describe to
somebody else. Set type at a size you would defend, a colour field, a
photograph treated a particular way, a piece of structure nobody expects.
Name it. If there is nothing to describe, there is nothing designed.

**References, by name.** Two or three real sites or publications this should
sit beside, and one sentence each on what is being taken - the rhythm, the
way the type is set, the restraint, the density. Not to copy; to aim.

**Photographs: you cannot make one, but you can use one.** This process has
no camera and no image generator, and a hand-written file named .jpg is a
lie that passes a build. But a photograph somebody else took, licensed for
this and fetched by URL, is neither made nor faked - and a page with one
good image on it is a different page. Most of the sites worth sitting beside
are carried by photography.

So direct the photography properly, the way the rest of this is directed:
how many images, where each one sits, what is in it, how it is cropped and
treated, and what it is doing that type could not. Name the source
concretely - give the Unsplash URL itself, in full - along with the aspect
ratio and what the page does while it loads. Give the URL rather than a
search term, because the engineer has no network and cannot go looking:
asked to find one, it spends the entire item trying and finishes nothing. An image
with no art direction is a stock photograph of a handshake and is worse than
no image at all.

If the subject genuinely cannot be photographed - an idea, a service,
something that does not exist yet - say so, and make it work with type,
colour, space, rule and a drawn mark instead. That is a harder brief and
often a better page. What is not allowed is an image conjured into the
repository by the thing building it.

Then the specifics, in enough detail to build from: hex values with their
contrast ratios, Google Font names with weights, a type scale in rem, a
spacing scale, and the breakpoints where the composition changes.

And say what the generic version of this would be, in detail, so it cannot
arrive by default."""

PROMPT = """What is being built: {task}

{shape}

Direct it. Be specific and be local to this business - its city, its kind of
room, who walks in, what they are deciding. Draw the mark yourself as SVG;
that one is yours and is never a stock icon.

Aim high. The brief that gets built is the brief that was written, and a
cautious one becomes a column of text on a coloured background - which is
what this produced until somebody put it beside a page that had been given
real art direction. Say what the best version of this looks like.

Remember that the engineer building this has your words and nothing else. A
sentence they cannot act on is a sentence that becomes a flat column."""


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
                "composition": {
                    "type": "string",
                    "description": (
                        "The grid, the asymmetry, where the eye lands and goes "
                        "next, what breaks the column and why. Name the "
                        "structural device. Be buildable, not evocative."
                    ),
                },
                "scale_contrast": {
                    "type": "string",
                    "description": (
                        "The ratio between the largest thing and the body "
                        "text, what gets it, and what is deliberately quiet."
                    ),
                },
                "density": {
                    "type": "string",
                    "description": (
                        "Which sections are tight and which are open, and the "
                        "spacing scale in rem that produces that."
                    ),
                },
                "moment": {
                    "type": "string",
                    "description": (
                        "The one thing somebody would describe to somebody "
                        "else afterwards."
                    ),
                },
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Two or three named sites or publications and one "
                        "sentence each on what is being taken from them."
                    ),
                },
                "layout": {
                    "type": "string",
                    "description": (
                        "What is above the fold, the order of the page, and "
                        "where the composition changes at each breakpoint."
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
                "composition",
                "scale_contrast",
                "density",
                "moment",
                "references",
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
            '"composition": "...", "scale_contrast": "...", "density": "...", '
            '"moment": "...", "references": ["..."], "layout": "...", '
            '"logo_svg": "<svg ...>...</svg>", "logo_reasoning": "...", '
            '"words": "...", "avoid": ["..."]}',
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
    """What the planner and the engineer are held to.

    Written as a list of parts rather than one long concatenation: this is
    the text that decides whether the thing gets built as directed, and it
    has to be easy to read and easy to add to.
    """
    if not found:
        return ""

    def block(label: str, key: str) -> str:
        said = (found.get(key) or "").strip()
        return f"{label}: {said}" if said else ""

    def listed(label: str, key: str) -> str:
        rows = found.get(key) or []
        return f"{label}:\n" + "\n".join(f"- {r}" for r in rows) if rows else ""

    opening = (
        "How this is to look. It was directed before anything was planned "
        "and it is not up for reinterpretation item by item; an item that "
        "renders anything renders it this way."
    )
    closing = (
        "One item near the start writes the stylesheet that holds the "
        "palette, the type scale and the spacing scale, and every later item "
        "uses those tokens rather than inventing values of its own."
    )
    parts = [
        opening,
        block("The idea", "idea"),
        block("The one moment", "moment"),
        block("Composition", "composition"),
        block("Scale contrast", "scale_contrast"),
        block("Density", "density"),
        listed("Palette", "palette"),
        block("Type", "type_scale"),
        block("Layout and breakpoints", "layout"),
        listed("It should sit beside", "references"),
        block("Voice", "words"),
        (
            "The mark is already drawn and is in `brand/logo.svg`. "
            f"{(found.get('logo_reasoning') or '').strip()} "
            "Use it; do not redraw it."
        ),
        listed("Specifically avoid", "avoid"),
        closing,
    ]
    return "\n\n" + "\n\n".join(p for p in parts if p)


def write_logo(repo: Path, found: dict) -> str:
    """Put the mark on disk, and commit it, so items can reference a file.

    Committed immediately on purpose. It is the project's own asset rather
    than something drydock left lying about, and the loop refuses to start on
    a dirty tree - so a file written here and not committed stops the whole
    job before the first item.
    """
    svg = (found.get("logo_svg") or "").strip()
    if not svg.startswith("<svg"):
        return ""
    brand = repo / "brand"
    brand.mkdir(exist_ok=True)
    (brand / "logo.svg").write_text(svg + "\n")

    from .repo import Repo

    Repo(repo).commit("The mark, drawn before anything was built")
    return "brand/logo.svg"


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
