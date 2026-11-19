"""Can the worker actually open the pictures, or only read their paths?

The whole loop rests on one assumption: that a Claude Code worker handed
`.drydock-look/desktop.png` opens it and sees a page, rather than treating
it as a file it cannot read. If that is false then every picture written
here is a path in a prompt and nothing more, and the engineer is still
working blind while being told it is not.

So this asks it. One worker, one turn, Read and nothing else, the same
confinement the engineer runs under, a real screenshot of a page whose
contents are known - and the question is whether what comes back describes
that page.

It costs a model call, so it does not run in CI. Turn it on deliberately:

    DRYDOCK_LIVE_LOOK=1 uv run pytest tests/test_can_the_engineer_see.py -s

Everything else about looking is tested without a model, in
test_looking_at_your_own_work.py and test_who_may_look.py.
"""

import json
import os
import shutil
import subprocess

import pytest

from drydock.engines import _confinement, _shell_rule
from drydock.repo import OUR_LOOK
from drydock.shot import find_browser, take

# A page with four facts in it that no model could produce from a filename:
# the name, the colour of the band, the number, and the word on the button.
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Ca' Serena</title></head>
<body style="margin:0;font-family:Georgia,serif">
<div style="background:#1f4e46;color:#f6f1e7;padding:64px 48px">
  <h1 style="margin:0;font-size:56px">Ca' Serena</h1>
  <p style="margin:16px 0 0;font-size:22px">Dinner from five, Tuesday to Sunday</p>
</div>
<div style="padding:48px">
  <p style="font-size:40px;margin:0">41</p>
  <p style="margin:8px 0 32px">seats</p>
  <a href="/reservations" style="background:#b4531f;color:#fff;
     padding:16px 32px;text-decoration:none;font-size:20px">Reserve</a>
</div></body></html>"""

ASKED = (
    "Open the file .drydock-look/desktop.png with the Read tool and tell me "
    "what is in the picture. Answer with one line of the form: "
    "HEADING=<the large heading> BAND=<the colour of the band behind it> "
    "NUMBER=<the large number> BUTTON=<the text on the button>. "
    "If you cannot open the file at all, answer exactly: CANNOT OPEN."
)

live = pytest.mark.skipif(
    not os.environ.get("DRYDOCK_LIVE_LOOK"),
    reason="costs a model call; set DRYDOCK_LIVE_LOOK=1 to run it",
)


@live
def test_a_worker_opens_the_picture_and_describes_the_page(tmp_path):
    binary = shutil.which("claude")
    if not binary:
        pytest.skip("the claude command is not on PATH")
    if not find_browser():
        pytest.skip("no browser on this machine")

    (tmp_path / "index.html").write_text(PAGE)
    shots = take(
        f"file://{tmp_path / 'index.html'}", tmp_path / OUR_LOOK, widths=("desktop",)
    )
    assert shots, "no screenshot to show it"
    assert shots[0].path.stat().st_size > 1000

    # And then the page itself goes. With the html still sitting there a
    # worker with Read could answer every one of these questions without
    # ever opening the picture - the first version of this test left it
    # there, and the answer it got proved nothing. Now the only thing in
    # this directory that knows what the page looks like is the png.
    (tmp_path / "index.html").unlink()
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["desktop.png"]

    # The same confinement the engineer gets: file tools fenced to this
    # directory by the PreToolUse hook, and no look budget, because this
    # worker is being asked to read a picture rather than to make one.
    settings, env = _confinement(tmp_path)
    done = subprocess.run(
        [
            binary,
            "--settings",
            settings,
            "-p",
            "--output-format",
            "json",
            "--model",
            "claude-haiku-4-5",
            "--max-turns",
            "4",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read",
        ],
        # Through stdin, the way the engine hands a worker its instruction.
        input=ASKED,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    said = json.loads(done.stdout).get("result", "")
    print(f"\nthe worker said: {said}\n")

    assert "CANNOT OPEN" not in said.upper()
    # Four facts that are in the image and nowhere else: not in the
    # filename, not in the prompt, not in any text file it could reach.
    flat = said.lower()
    assert "serena" in flat
    assert "41" in flat
    assert "reserve" in flat
    assert any(word in flat for word in ("green", "teal", "#1f4e46", "1f4e46"))


RUN_IT = (
    "Run the command `drydock-look` and then tell me, in one line, the "
    "first word it printed and the names of any png files it listed. If you "
    "were not allowed to run it, answer exactly: NOT ALLOWED."
)


@live
def test_a_worker_is_actually_allowed_to_run_it(tmp_path):
    """Whether the allow-rule works, not whether it is in the argv.

    `Bash(drydock-look)` is a permission pattern handed to somebody else's
    CLI. Every test around this one asserts the string is on the command
    line, which is a claim about what we asked for and not about what was
    granted - and a rule that is quietly wrong leaves the whole capability
    doing nothing while every test still passes. That has happened here
    before, more than once, so it is checked against the real thing.
    """
    binary = shutil.which("claude")
    if not binary:
        pytest.skip("the claude command is not on PATH")
    if not find_browser():
        pytest.skip("no browser on this machine")

    (tmp_path / "index.html").write_text(PAGE)
    settings, env = _confinement(tmp_path, look_key="live-item1", looks=2)
    done = subprocess.run(
        [
            binary,
            "--settings",
            settings,
            "-p",
            "--output-format",
            "json",
            "--model",
            "claude-haiku-4-5",
            "--max-turns",
            "6",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read " + _shell_rule("", can_look=True),
        ],
        input=RUN_IT,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    said = json.loads(done.stdout).get("result", "")
    print(f"\nthe worker said: {said}\n")

    assert "NOT ALLOWED" not in said.upper()
    assert "LOOKED" in said.upper()
    # It ran the real thing: a static index.html, served by how_to_run,
    # photographed at two widths into the tree.
    assert "desktop.png" in said
    assert (tmp_path / OUR_LOOK / "desktop.png").stat().st_size > 1000
