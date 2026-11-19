"""A small tool-use loop.

Each agent is this loop with a different system prompt and a different set of
tools. The loop itself is deliberately dull: send, read the tool calls, run
them, send the results back, stop when the model stops asking. What makes one
agent different from another is what it is allowed to do, which is why the
tools are passed in rather than built in.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field

import anthropic

# Judgement runs on the expensive model; looking things up does not. The split
# is per agent rather than global because the Analyst spends most of its turns
# grepping, and paying Opus prices to read a file listing is waste.
JUDGEMENT = "claude-opus-5"
LOOKUP = "claude-haiku-4-5"

# The picker in the interface offers the same three names a Claude subscription
# offers, because that is what someone choosing between them already knows.
# On the subscription engine those names go through verbatim; on the API they
# have to become full model ids.
API_MODEL = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}

# Which model does the typing. The one that was chosen, unless somebody
# asks for the cheaper one.
#
# This used to read {"opus": "sonnet"}, which meant a run started on Opus
# had its code written by Sonnet on every first attempt, and Opus appeared
# only on a retry. The measurement behind it was real - the engineer took
# 180 to 210 seconds an item while every other station took 45 to 95, so
# three quarters of a run was one station writing files, and it is also the
# station whose output is checked hardest - but it was applied silently, in
# a dict nobody reading the picker would ever see. "I chose Opus" has to
# mean Opus did the work, or the picker is lying about what the run is.
#
# The saving is still here and now it has to be asked for:
#
#     DRYDOCK_CHEAP_ENGINEER=1
#
# which routes the engineer's first attempt to the cheaper model and says
# so, once per item, where the run can be read. A retry is never routed:
# once an item has come back refused, the attempt that follows is the one
# that must not fail.
CHEAPER = {"opus": "sonnet", "sonnet": "sonnet", "haiku": "haiku"}

CHEAP_ENGINEER = "DRYDOCK_CHEAP_ENGINEER"


def cheap_engineer() -> bool:
    """Whether the engineer's first attempt was asked to run cheaply."""
    return os.environ.get(CHEAP_ENGINEER) == "1"


def for_work(model: str) -> str:
    """The model the engineer uses, given the one chosen for the run.

    The same one, unless the cheaper engineer was asked for. A deliberate
    choice of the cheapest model is never overridden either way: somebody
    who picked Haiku wanted Haiku.
    """
    if not cheap_engineer():
        return model
    return CHEAPER.get(model, model)


MODEL = JUDGEMENT


class BudgetExceeded(RuntimeError):
    """Raised when a run has spent what it was allowed to spend."""


# Opus 5 list price, dollars per million tokens.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[..., str]
    strict: bool = False

    def spec(self) -> dict:
        spec = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }
        if self.strict:
            # Without this the shape of the arguments is a request. With it the
            # API guarantees them, which matters for the tool an agent hands its
            # result back through: a list that arrives as a string is a failure
            # three functions later, where it is expensive to understand.
            spec["strict"] = True
        return spec


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    turns: int = 0
    dollars: float = 0.0

    def add(self, message, model: str) -> None:
        use = message.usage
        cached = getattr(use, "cache_read_input_tokens", 0) or 0
        fresh = use.input_tokens
        self.input_tokens += fresh
        self.cached_tokens += cached
        self.output_tokens += use.output_tokens
        self.turns += 1

        rate_in, rate_out = PRICES.get(model, PRICES["claude-opus-5"])
        # A cache read is charged at a tenth of the input rate; a write at
        # 1.25x. Writes are not broken out here because the loop writes one
        # breakpoint per turn and the difference is inside the rounding.
        self.dollars += (
            fresh / 1e6 * rate_in
            + cached / 1e6 * rate_in * 0.1
            + use.output_tokens / 1e6 * rate_out
        )


@dataclass
class Agent:
    name: str
    system: str
    tools: list[Tool] = field(default_factory=list)
    max_turns: int = 20
    model: str = JUDGEMENT
    budget: float = 0.0
    usage: Usage = field(default_factory=Usage)
    on_event: Callable[[str, str], None] | None = None

    def _say(self, kind: str, text: str) -> None:
        if self.on_event:
            self.on_event(kind, text)

    def run(self, prompt: str, final_tool: Tool | None = None) -> dict | str:
        """Work until the model stops calling tools.

        When `final_tool` is given the agent is required to end by calling it,
        and its arguments are the return value. That is how an agent hands back
        something typed instead of a paragraph that has to be parsed.
        """
        client = anthropic.Anthropic()
        tools = [t.spec() for t in self.tools]
        by_name = {t.name: t for t in self.tools}
        if final_tool:
            tools.append(final_tool.spec())
            by_name[final_tool.name] = final_tool

        budget = (
            f"\n\nYou have at most {self.max_turns} tool calls for this. Stop and "
            "report as soon as you can answer, not when you have read everything: "
            "a survey that is 90 percent complete and delivered is worth more than "
            "one that runs out of turns."
        )
        messages: list[dict] = [{"role": "user", "content": prompt + budget}]

        for turn in range(self.max_turns):
            message = client.messages.create(
                model=self.model,
                max_tokens=16000,
                # The system prompt and the tool list are identical on every
                # turn of a loop that can run twenty times, and the transcript
                # only grows at the end. Caching the prefix turns the repeated
                # part of the bill into a tenth of itself.
                system=[
                    {
                        "type": "text",
                        "text": self.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=tools,
                messages=_with_cache_breakpoint(messages),
            )
            self.usage.add(message, self.model)

            if self.budget and self.usage.dollars > self.budget:
                raise BudgetExceeded(
                    f"{self.name} spent ${self.usage.dollars:.2f} of a "
                    f"${self.budget:.2f} budget and was stopped"
                )

            calls = [b for b in message.content if b.type == "tool_use"]
            for block in message.content:
                if block.type == "text" and block.text.strip():
                    self._say("thinking", block.text.strip())

            if not calls:
                text = "".join(b.text for b in message.content if b.type == "text")
                return text.strip()

            messages.append({"role": "assistant", "content": message.content})

            results = []
            for call in calls:
                if final_tool and call.name == final_tool.name:
                    self._say("done", f"{self.name} finished")
                    return call.input
                tool = by_name.get(call.name)
                if tool is None:
                    results.append(_result(call.id, f"no tool named {call.name}", True))
                    continue
                self._say("tool", f"{call.name} {_short(call.input)}")
                try:
                    output = tool.run(**call.input)
                    results.append(_result(call.id, output))
                except Exception as exc:  # noqa: BLE001 - a tool may raise
                    # anything, and the loop has to survive it: the model is
                    # told what broke and gets to choose what to do next.
                    results.append(
                        _result(call.id, f"{type(exc).__name__}: {exc}", True)
                    )

            left = self.max_turns - turn - 1
            if left <= 3 and final_tool:
                results.append(
                    {
                        "type": "text",
                        "text": f"{left} tool calls left. Call {final_tool.name} now "
                        "with what you have.",
                    }
                )
            messages.append({"role": "user", "content": results})

        raise RuntimeError(f"{self.name} did not finish within {self.max_turns} turns")


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Mark the end of the history so everything before it can be reused.

    The marker has to land on a content block, and by the second turn almost
    every message in this loop carries a list of blocks rather than a string:
    assistant turns hold tool_use blocks, user turns hold tool_result blocks.
    An earlier version only handled the string case, so the breakpoint was
    silently never placed and the cache stayed nearly empty while the bill did
    not.

    Only the last message is marked. The four available breakpoints are better
    spent elsewhere, and a marker at the end already covers everything before
    it.
    """
    if not messages:
        return messages

    marked = list(messages)
    last = dict(marked[-1])
    content = last.get("content")

    if isinstance(content, str):
        last["content"] = [
            {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        ]
    elif isinstance(content, list) and content:
        blocks = [
            block if isinstance(block, dict) else block.model_dump()
            for block in content
        ]
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
        last["content"] = blocks
    else:
        return messages

    marked[-1] = last
    return marked


def _result(call_id: str, content: str, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": content[:20000],
        "is_error": is_error,
    }


def _short(payload: dict) -> str:
    return ", ".join(f"{k}={str(v)[:60]}" for k, v in payload.items())
