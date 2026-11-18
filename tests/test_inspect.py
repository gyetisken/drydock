"""The gate that cannot be talked round.

Everything here is a way of making a suite green by making it smaller. The
point of testing this hard is that these are the failures a green build is
specifically unable to report.
"""

import pytest

from drydock.inspect import look


def diff(*lines: str) -> str:
    return "--- a/x\n+++ b/x\n" + "\n".join(lines)


class TestLosingTests:
    def test_a_deleted_test_is_refused(self):
        r = look(
            diff("-    @Test", "-    public void parses() { assertEquals(1, x); }")
        )
        assert not r.clean
        assert "test declarations were removed" in r.reason

    def test_a_test_moved_rather_than_deleted_is_fine(self):
        r = look(diff("-    @Test public void a() {}", "+    @Test void a() {}"))
        assert r.clean

    def test_an_item_that_says_it_removes_tests_is_allowed_to(self):
        r = look(diff("-    @Test public void duplicate() {}"), allow_removals=True)
        assert r.clean

    def test_python_go_and_javascript_count_too(self):
        for line in (
            "-def test_parses(self):",
            "-func TestParses(t *testing.T) {",
            "-  it('parses', () => {",
        ):
            assert not look(diff(line)).clean, line


class TestSilencing:
    def test_a_newly_skipped_test_is_refused(self):
        r = look(diff('+    @Disabled("flaky")', "+    @Test void a() {}"))
        assert not r.clean
        assert "switched off" in r.reason

    def test_pytest_and_jest_markers_count(self):
        assert not look(diff("+@pytest.mark.skip")).clean
        assert not look(diff("+  it.skip('parses', () => {")).clean


class TestWeakening:
    def test_quietly_dropping_several_assertions_is_refused(self):
        r = look(diff(*[f"-    assertEquals({i}, x);" for i in range(5)]))
        assert not r.clean
        assert "assertions were removed" in r.reason

    def test_swapping_an_assertion_for_another_is_fine(self):
        r = look(diff("-    Assert.assertEquals(1, x);", "+    assertEquals(1, x);"))
        assert r.clean


class TestSecrets:
    def test_a_committed_env_file_is_refused(self):
        assert not look("--- /dev/null\n+++ b/app/.env\n+KEY=1").clean

    def test_a_key_in_the_diff_is_refused(self):
        r = look(diff("+ANTHROPIC_API_KEY=sk-ant-abcdef1234567890"))
        assert not r.clean
        assert "credential" in r.reason

    def test_a_pem_file_is_refused(self):
        assert not look("--- /dev/null\n+++ b/certs/server.pem\n+x").clean


class TestQuiet:
    def test_an_ordinary_change_says_nothing(self):
        r = look(diff("-    int a = 1;", "+    int a = 2;"))
        assert r.clean
        assert r.reason == ""


class TestThingsNobodyWrote:
    """Build output and downloaded dependencies, which is how a first commit
    quietly becomes forty thousand files."""

    def test_node_modules_is_refused(self):
        r = look("--- /dev/null\n+++ b/node_modules/lodash/index.js\n+x")
        assert not r.clean
        assert "node_modules" in r.reason

    def test_build_output_is_refused(self):
        for path in (
            "target/classes/A.class",
            "dist/app.js",
            "__pycache__/x.pyc",
            ".venv/lib/python3.13/site-packages/a.py",
            "coverage/index.html",
        ):
            assert not look(f"--- /dev/null\n+++ b/{path}\n+x").clean, path

    def test_a_file_merely_named_after_one_is_fine(self):
        assert look("--- /dev/null\n+++ b/src/build_tools.py\n+x").clean
        assert look("--- /dev/null\n+++ b/docs/node_modules.md\n+x").clean

    def test_it_is_reported_once_per_directory_not_per_file(self):
        diff = "".join(
            f"--- /dev/null\n+++ b/node_modules/p{i}/index.js\n+x\n" for i in range(50)
        )
        assert (
            len([f for f in look(diff).findings if f.kind == "not ours to commit"]) == 1
        )


class TestImprovisedAssets:
    """An item asked for a photograph. Nothing in this process can take one,
    so a worker hand-wrote a 16x20 bitmap of flat colour blocks and committed
    it as public/corner.jpg. Three gates passed it; the one with eyes caught
    it. This is the mechanical version of that catch."""

    def added(self, path: str) -> str:
        return f"--- /dev/null\n+++ b/{path}\n+binary"

    def test_a_bitmap_wearing_a_jpg_extension(self, tmp_path):
        (tmp_path / "corner.jpg").write_bytes(b"BM" + b"\x00" * 4000)
        report = look(self.added("corner.jpg"), repo=tmp_path)
        assert not report.clean
        assert "is .bmp" in report.reason

    def test_an_image_too_small_to_be_of_anything(self, tmp_path):
        (tmp_path / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        report = look(self.added("hero.png"), repo=tmp_path)
        assert not report.clean
        assert "bytes" in report.reason

    def test_a_real_image_is_left_alone(self, tmp_path):
        (tmp_path / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 9000)
        assert look(self.added("hero.png"), repo=tmp_path).clean

    def test_an_svg_is_not_checked_for_magic_bytes(self, tmp_path):
        """SVG is text and is readable in the diff like anything else."""
        (tmp_path / "mark.svg").write_text("<svg/>")
        assert look(self.added("mark.svg"), repo=tmp_path).clean

    def test_nothing_happens_without_a_repository_to_look_in(self):
        assert look(self.added("corner.jpg")).clean


class TestCredentialsAreRecognisedOnSight:
    """Every prefix here was chosen by the provider so that a leaked key
    can be spotted, which is the only reason this can be a regular
    expression rather than a judgement. It is matched in the diff before
    the commit, because a committed key cannot be taken back by deleting
    it: the history has it, and so does anything that mirrored it."""

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-api03-abcDEF123456789012345",
            "sk-proj-abcdefghijklmnopqrstuvwxyz",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_abcdefghijklmnopqrst12",
            "gho_abcdefghijklmnopqrst12",
            "github_pat_11ABCDEFG0abcdefghijkl",
            "AIzaSyA1234567890abcdefghijklmnopqrstu",
            "sk_live_abcdefghijklmnopqrstu",
            "glpat-abcdefghijklmnop",
            "xoxb-1234567890-abc",
            "npm_abcdefghijklmnopqrstuvwxyz1234",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
        ],
    )
    def test_it_is_caught(self, secret):
        report = look(f"+++ b/config.js\n+const key = '{secret}';\n")
        assert not report.clean
        assert "credential" in report.reason.lower()

    @pytest.mark.parametrize(
        "innocent",
        [
            "task-list-container-wrapper",
            "disk-usage-reporter-module",
            "background-color: var(--paper);",
            "--skip-tests",
            "const stripeKey = process.env.STRIPE_KEY;",
            "AKIA123",
            "ghp_short",
        ],
    )
    def test_ordinary_code_is_not(self, innocent):
        """A refusal nobody can act on is worse than no check at all: it
        costs an attempt and teaches the engineer nothing."""
        report = look(f"+++ b/app.css\n+{innocent}\n")
        assert report.clean, report.reason


class TestAnAssertionSwappedForAWeakerOne:
    """The quietest way there is to make a failing test pass. The counts do
    not move, the suite stays the same size, every test still runs - and
    the test no longer says anything about what the code produces. A
    reviewer reading a diff of three hundred lines does not see it, and no
    runner in the world reports it.

    The README claimed this was caught before anything caught it.
    """

    @pytest.mark.parametrize(
        ("language", "diff"),
        [
            (
                "javascript",
                (
                    "-  expect(total(cart)).toBe(42);\n"
                    "+  expect(total(cart)).toBeDefined();\n"
                ),
            ),
            (
                "java",
                (
                    "-    assertEquals(42, total(cart));\n"
                    "+    assertNotNull(total(cart));\n"
                ),
            ),
            (
                "python",
                "-    assert total(cart) == 42\n+    assert total(cart) is not None\n",
            ),
            (
                "python, bare",
                "-    assert total(cart) == 42\n+    assert total(cart)\n",
            ),
            (
                "rust",
                (
                    "-    assert_eq!(total(&cart), 42);\n"
                    "+    assert!(total(&cart).is_some());\n"
                ),
            ),
            (
                "c#",
                (
                    "-    Assert.AreEqual(42, Total(cart));\n"
                    "+    Assert.IsNotNull(Total(cart));\n"
                ),
            ),
        ],
    )
    def test_it_is_caught(self, language, diff):
        report = look(f"+++ b/src/total.test\n{diff}")
        assert not report.clean, language
        assert "weakened" in report.reason or "no longer say" in report.reason

    def test_making_an_assertion_stronger_is_not_a_complaint(self):
        """The same two lines the other way round. A rule that cannot tell
        these apart would refuse every improvement to a test."""
        report = look(
            "+++ b/src/total.test.js\n"
            "-  expect(total(cart)).toBeDefined();\n"
            "+  expect(total(cart)).toBe(42);\n"
        )
        assert report.clean, report.reason

    def test_a_new_test_with_a_loose_assertion_is_fine(self):
        """Checking that something is not null is a real assertion. This is
        only a complaint when an exacting one disappeared to make room."""
        report = look(
            "+++ b/src/total.test.js\n"
            "+  it('returns something', () => {\n"
            "+    expect(total(cart)).toBeDefined();\n"
            "+  });\n"
        )
        assert report.clean, report.reason

    def test_changing_what_an_assertion_looks_at_is_fine(self):
        report = look(
            "+++ b/src/total.test.js\n-  expect(a).toBe(1);\n+  expect(b).toBe(1);\n"
        )
        assert report.clean, report.reason

    def test_it_says_both_halves_of_what_happened(self):
        """So the engineer knows which assertion to put back, rather than
        being told its diff was rejected."""
        report = look(
            "+++ b/src/total.test.js\n"
            "-  expect(total(cart)).toBe(42);\n"
            "+  expect(total(cart)).toBeTruthy();\n"
        )
        assert "named the value they expected" in report.reason
        assert "almost any value" in report.reason
