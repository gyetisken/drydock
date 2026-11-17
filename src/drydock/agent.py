"""A small tool-use loop.

Each agent is this loop with a different system prompt and a different set of
tools. The loop itself is deliberately dull: send, read the tool calls, run
them, send the results back, stop when the model stops asking. What makes one
agent different from another is what it is allowed to do, which is why the
tools are passed in rather than built in.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import anthropic

MODEL = "claude-opus-5"


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
    turns: int = 0

    def add(self, message) -> None:
        self.input_tokens += message.usage.input_tokens
        self.output_tokens += message.usage.output_tokens
        self.turns += 1


@dataclass
class Agent:
    name: str
    system: str
    tools: list[Tool] = field(default_factory=list)
    max_turns: int = 30
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
                model=MODEL,
                max_tokens=16000,
                system=self.system,
                tools=tools,
                messages=messages,
            )
            self.usage.add(message)

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


def _result(call_id: str, content: str, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": content[:20000],
        "is_error": is_error,
    }


def _short(payload: dict) -> str:
    return ", ".join(f"{k}={str(v)[:60]}" for k, v in payload.items())
