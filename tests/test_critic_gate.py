"""Which items get looked at.

Rendering a page and having somebody look at it costs a minute. A parser has
nothing to look at, so the check is for work that changed what somebody sees
- and the question of which work that is must not be a guess made per run.
"""

from drydock.orchestrate import _changes_the_view


def diff(*paths: str) -> str:
    return "\n".join(f"--- a/{p}\n+++ b/{p}\n+x" for p in paths)


class TestSomebodySeesThis:
    def test_stylesheets(self):
        for path in ("src/styles/site.css", "app.scss", "a/b/main.less"):
            assert _changes_the_view(diff(path)), path

    def test_templates_and_components(self):
        for path in (
            "src/pages/index.astro",
            "views/home.ejs",
            "src/components/Menu.tsx",
            "templates/base.html",
            "app/layout.tsx",
        ):
            assert _changes_the_view(diff(path)), path

    def test_anything_under_a_directory_that_is_rendered(self):
        assert _changes_the_view(diff("public/hero.svg"))
        assert _changes_the_view(diff("src/layouts/Base.astro"))


class TestNobodySeesThis:
    def test_logic_and_data(self):
        for path in ("src/hours/week.ts", "lib/parse.py", "cmd/main.go"):
            assert not _changes_the_view(diff(path)), path

    def test_tests(self):
        assert not _changes_the_view(diff("tests/week.test.ts"))

    def test_project_files(self):
        for path in ("package.json", "README.md", ".gitignore", "tsconfig.json"):
            assert not _changes_the_view(diff(path)), path

    def test_an_empty_diff(self):
        assert not _changes_the_view("")


def test_one_visible_file_among_many_is_enough():
    assert _changes_the_view(diff("src/hours/week.ts", "package.json", "app.css"))


def test_the_two_verdicts_do_not_share_a_name():
    """The verification says `passed`, the critic says `approved`, and both
    were called `verdict` in the same scope. The critic approved an item and
    the loop crashed on the next line reading `.passed` off the wrong one."""
    import inspect

    from drydock import orchestrate

    body = inspect.getsource(orchestrate.execute)
    assert "seen, spend = _show_it(" in body
    assert "verdict, spend = _show_it(" not in body
