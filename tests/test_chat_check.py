"""chat-layer 2.3: the source-layer check on the way out."""

from datetime import date

from domestique.chat.check import LABELS, MARK, check_layers, mark_unlabelled
from domestique.claims.rules import SourceLayer
from domestique.output.comments import LAYER_LABEL, Remark, Statement, render
from domestique.rails import DayData, joint_pain

RAIL = joint_pain(DayData(date(2026, 9, 9), subjective_tags=("joint-pain",)), {}).wording
QUESTION = "Did the session as ridden match what you intended for it?"


def test_labels_are_the_ones_the_comments_render():
    assert tuple(f"({v})" for v in LAYER_LABEL.values()) == LABELS
    text = render(Remark(tuple(Statement("Steady.", layer) for layer in SourceLayer)))
    assert check_layers(text).ok


def test_labelled_bullets_pass():
    text = (
        "Here is the debrief:\n"
        "- (your data shows) Rep 5 held 312 W against 318 W on rep 1.\n"
        "- (you told me) The last climb felt heavy.\n"
        "* (The literature says) Some HR drift is expected.\n"
    )
    checked = check_layers(text)
    assert checked.ok and checked.unlabelled == ()


def test_an_unlabelled_bullet_comes_back_as_a_fragment():
    text = "- (your data shows) HRV 71 against 82.\n- You should rest today\n1. Fine: sleep more.\n"
    checked = check_layers(text)
    assert not checked.ok
    assert checked.unlabelled == ("You should rest today", "Fine: sleep more.")


def test_sentence_lines_are_statements_headings_tables_and_code_are_not():
    text = (
        "## Summary\n"
        "| metric | value |\n"
        "```\nplain code line.\n```\n"
        "Overall a solid week.\n"
        "(your data shows) Three of four predictions hit.\n"
        "Notes:\n"
    )
    assert check_layers(text).unlabelled == ("Overall a solid week.",)


def test_exempt_rail_wording_and_question_text_pass_unchanged():
    text = f'{RAIL}\n- {QUESTION}\n> "{QUESTION}"\n'
    assert not check_layers(text).ok
    checked = check_layers(text, exempt=(RAIL, QUESTION))
    assert checked.ok, checked.unlabelled
    assert mark_unlabelled(text, exempt=(RAIL, QUESTION)) == text.rstrip("\n")


def test_mark_keeps_the_bullet_and_marks_only_failing_statements():
    text = "- (you told me) Legs felt fine.\n- Take a day off.\nAll good."
    assert mark_unlabelled(text) == (
        f"- (you told me) Legs felt fine.\n- {MARK} Take a day off.\n{MARK} All good."
    )
