"""The gate that cannot be talked round.

Everything here is a way of making a suite green by making it smaller. The
point of testing this hard is that these are the failures a green build is
specifically unable to report.
"""

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
