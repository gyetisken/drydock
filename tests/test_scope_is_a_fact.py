"""Scope was a question put to somebody who could not answer it.

The reviewer is handed a diff and no repository, and was asked whether the
change does "anything the item did not ask for". While items named the
implementation, the size of the diff was predictable from the item's own
words and the question worked. Once items named outcomes it stopped
working, and the Corso B run is what that looks like: item 3 said "it
reads on a phone, held at arm's length on a sidewalk", the engineer
rewrote the stylesheet to achieve it, and the reviewer refused twice -

    "The item asked for one thing: that the page read on a phone. The diff
     replaces the entire stylesheet (one line -> 212 lines)"

- for a file the item had authorised. Two attempts went, the item was
split into two narrow ones, the clock ran out, and the item that was
actually about the design never ran.

So which files a diff touches is read as arithmetic, where it is a fact,
and the reviewer is told that the shape and size of the change inside
those files is not its business. What it keeps is everything that needs
judgement: does the change achieve the item, does it change behaviour
nobody asked for, and does it get there by weakening what was being
checked.
"""

import inspect

from drydock import orchestrate, reviewer
from drydock.inspect import _outside, look

STYLESHEET = """--- a/public/styles.css
+++ b/public/styles.css
@@ -1 +1,212 @@
-body { font-family: sans-serif; }
+:root { --paper: #f2ebdf; }
"""

ALSO_THE_SERVER = (
    STYLESHEET
    + """--- a/server.js
+++ b/server.js
@@ -1 +1,2 @@
+import fetch from "node-fetch";
"""
)


def flat(text: str) -> str:
    return " ".join(text.split())


class TestWhatCountsAsOutsideTheItem:
    def test_a_file_the_item_named(self):
        assert _outside(STYLESHEET, ["public/styles.css"]) == []

    def test_the_corso_b_case_is_not_a_scope_problem(self):
        """One line to two hundred and twelve, inside the authorised
        file. This is the diff that was refused twice."""
        report = look(STYLESHEET, files=["public/styles.css"])
        assert report.clean, report.reason

    def test_a_file_the_item_did_not_name(self):
        assert _outside(ALSO_THE_SERVER, ["public/styles.css"]) == ["server.js"]

    def test_that_is_reported_and_refuses(self):
        report = look(ALSO_THE_SERVER, files=["public/styles.css"])
        assert not report.clean
        assert "server.js" in report.reason
        assert "public/styles.css" in report.reason, "say what was authorised"

    def test_an_item_that_named_nothing_authorises_nothing_in_particular(self):
        """Silence is the honest answer: there is nothing to measure
        against. The reviewer still reads the change."""
        assert _outside(ALSO_THE_SERVER, []) == []
        assert look(ALSO_THE_SERVER, files=[]).clean
        assert look(ALSO_THE_SERVER).clean

    def test_blank_entries_are_not_a_list_of_files(self):
        assert _outside(ALSO_THE_SERVER, ["", "   "]) == []

    def test_globs(self):
        assert _outside(ALSO_THE_SERVER, ["public/*.css", "*.js"]) == []
        assert _outside(ALSO_THE_SERVER, ["public/*.css"]) == ["server.js"]

    def test_a_directory_authorises_what_is_under_it(self):
        diff = """--- a/src/views/home.js
+++ b/src/views/home.js
@@
+x
"""
        assert _outside(diff, ["src/views"]) == []
        assert _outside(diff, ["src/views/"]) == []
        assert _outside(diff, ["src/lib"]) == ["src/views/home.js"]

    def test_a_deleted_file_is_not_counted_as_a_stray_path(self):
        diff = """--- a/old.js
+++ /dev/null
@@
-x
"""
        assert _outside(diff, ["old.js"]) == []

    def test_every_stray_file_is_named_not_just_the_first(self):
        diff = (
            ALSO_THE_SERVER
            + """--- a/package.json
+++ b/package.json
@@
+y
"""
        )
        assert _outside(diff, ["public/styles.css"]) == ["package.json", "server.js"]


class TestTheInspectorDoesTheCounting:
    def test_it_is_handed_the_items_files(self):
        source = inspect.getsource(orchestrate._one_item)
        assert "files=item.files," in source

    def test_the_other_deterministic_checks_are_untouched(self):
        """Removing a test and silencing one are still refused, and they
        are the reason this station exists."""
        removed = """--- a/test/a.test.js
+++ b/test/a.test.js
@@
-test("it works", () => {});
"""
        assert not look(removed, files=["test/a.test.js"]).clean


class TestWhatTheReviewerKeeps:
    def test_it_still_asks_whether_the_item_was_achieved(self):
        assert "Does this diff achieve what the item said?" in reviewer.SYSTEM

    def test_it_still_catches_a_result_reached_by_weakening_the_checks(self):
        said = flat(reviewer.SYSTEM)
        assert "weakening what was being checked" in said
        for guard in ("a test loosened or deleted", "an assertion removed"):
            assert guard in said, guard

    def test_it_still_catches_a_secret_in_the_source(self):
        assert "a secret or a credential put in the source" in flat(reviewer.SYSTEM)

    def test_it_still_catches_unrelated_behaviour(self):
        said = flat(reviewer.SYSTEM)
        assert "Does it change behaviour the item never mentioned?" in said
        assert "an unrelated feature, a changed endpoint" in said

    def test_a_rejection_has_to_name_the_behaviour(self):
        """ "It is bigger than I expected" is not a finding."""
        said = flat(reviewer.SYSTEM)
        assert "If you cannot name the behaviour that changed" in said


class TestWhatTheReviewerGaveUp:
    def test_the_question_it_could_not_answer_is_gone(self):
        assert "Does it do anything the item did not ask for" not in flat(
            reviewer.SYSTEM
        )

    def test_size_is_named_as_not_its_business(self):
        said = flat(reviewer.SYSTEM)
        assert "How much changed is not one of the questions" in said
        assert "two hundred lines where you expected twenty" in said

    def test_it_is_told_the_files_were_already_checked(self):
        said = flat(reviewer.SYSTEM)
        assert "something that is not you has already checked" in said

    def test_the_prompt_says_what_was_authorised(self):
        assert "{files}" in reviewer.PROMPT
        said = flat(reviewer.PROMPT)
        assert "Files this item authorised" in said
        assert "the shape and the size of the change are the engineer's" in said

    def test_the_prompt_is_built_with_them(self):
        source = inspect.getsource(reviewer)
        assert 'files=", ".join(item.files)' in source


class TestNothingIndependentWasRemoved:
    def test_the_reviewer_still_runs(self):
        assert "review" in inspect.getsource(orchestrate._judge)

    def test_the_critic_still_runs(self):
        assert "_show_it" in inspect.getsource(orchestrate._judge)

    def test_file_paths_alone_do_not_approve_anything(self):
        """A clean scope report is not a verdict: the inspector reports,
        and the reviewer and the critic still have to agree."""
        source = inspect.getsource(orchestrate._one_item)
        after = source[source.index("report_card = look(") :]
        assert "_judge(" in after
