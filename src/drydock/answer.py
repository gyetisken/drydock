"""Answering a question about a repository without touching it.

Everything else here changes code and proves the change was allowed to stay.
That is the right amount of ceremony for a change and an absurd amount for a
question, and a tool that cannot answer a question is a tool somebody leaves
to open a terminal instead - which is how they end up doing the next change
there too.

So this is the short path: read the repository, answer, change nothing. No
plan, no approval, no branch, no commit. The guard that keeps the crew inside
the project still applies, and the write tools are simply absent.
"""

from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent
from .engines import ClaudeCodeEngine
from .memory import Memory
from .tools import read_only

SYSTEM = """You answer questions about a codebase by reading it.

You change nothing. There is no edit tool here and there is no branch; if
the answer is that something should change, say what and where, and the
person asking can run the change as its own job.

Answer the question that was asked. Not the surrounding area, not what you
would have built instead. If the answer is short, give the short answer -
somebody asking where a thing lives wants the path, not an essay with the
path in the middle of it.

Read before answering. A guess that sounds right is worse than "the code
does not say", because the second one is true and can be acted on.

Quote what you are relying on, with the file and the line, so the answer can
be checked without being taken on trust."""


def ask(
    repo: Path,
    question: str,
    engine: str = "claude",
    model: str = "opus",
    on_event=None,
    memory: Memory | None = None,
    commit: str = "",
) -> tuple[str, object]:
    """Read the repository and answer. Returns the answer and what it cost."""
    known = memory.briefing(commit) if memory and commit else ""
    prompt = f"{question}{known}"

    if engine == "claude":
        answer, dollars, turns = ClaudeCodeEngine(model=model, max_turns=30).structured(
            repo,
            SYSTEM,
            prompt,
            '{"answer": "...", "looked_at": ["path:line", "..."]}',
            on_event=on_event,
        )
        return answer.get("answer", ""), _Spend(dollars, turns)

    agent = Agent(
        name="Answer",
        model=API_MODEL.get(model, JUDGEMENT),
        system=SYSTEM,
        tools=read_only(repo),
        max_turns=20,
        on_event=on_event,
    )
    return agent.run(prompt), agent.usage


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
