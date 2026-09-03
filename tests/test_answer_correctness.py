"""Tests for the answer-correctness axis.

Two jobs:
  1. pin `normalize_answer` / `answers_match` against the forms that actually
     occur in FormalStep `ground_truth` values
  2. prove the axis cannot see a Lean verdict -- the independence assertion

Run: python -m pytest tests/test_answer_correctness.py -q
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from answer_correctness import (  # noqa: E402
    LEAN_VERDICT_FIELDS,
    LeanLeakError,
    answer_value,
    answers_match,
    assert_no_lean_verdict,
    extract_answer,
    normalize_answer,
    score_trajectory,
)

MODULE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "answer_correctness.py")


# --------------------------------------------------------------------------- #
# 1. The normalisation table from the brief, verbatim
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    (r"45,\!045",        "45045"),
    (r"\frac1{216}",     "1/216"),
    (r"\frac{1}{216}",   "1/216"),
    (r"\dfrac{3}{4}",    "3/4"),
    (r"\frac{2}{4}",     "1/2"),      # reduce
    ("101",              "101"),
    ("$101$",            "101"),
])
def test_normalisation_table(raw, expected):
    assert normalize_answer(raw) == expected


def test_decimal_and_fraction_compare_equal():
    assert answers_match("0.5", r"\frac{1}{2}")
    assert normalize_answer("0.5") == normalize_answer(r"\frac{1}{2}") == "1/2"


# --------------------------------------------------------------------------- #
# 2. The documented rules, each pinned
# --------------------------------------------------------------------------- #
def test_rule_fraction_reduction():
    assert normalize_answer(r"\frac{6}{8}") == "3/4"
    assert normalize_answer(r"\frac{4}{2}") == "2"      # integral, loses /1


def test_rule_decimal_is_exact_not_float():
    # 0.1 is not representable in binary floating point; this must still be 1/10.
    assert answer_value("0.1") == answer_value(r"\frac{1}{10}")
    assert answers_match("0.1", r"\frac{1}{10}")


def test_rule_negative_signs_inside_or_outside():
    assert normalize_answer(r"-\frac{2}{3}") == "-2/3"
    assert normalize_answer(r"\frac{-2}{3}") == "-2/3"
    assert normalize_answer("-7") == "-7"


def test_rule_whitespace_and_spacing_macros():
    assert normalize_answer(r"\frac{1} {2}") == "1/2"
    assert normalize_answer(r"29,\!322,\!216") == "29322216"
    assert normalize_answer("  101  ") == "101"


def test_rule_percent_has_two_readings():
    # value reading -- the data needs 10% == 1/10
    assert answer_value(r"10\%") == answer_value(r"\frac{1}{10}")
    assert answers_match(r"10\%", "0.1")
    assert answers_match(r"10\%", r"\frac{1}{10}")
    # bare-numeral reading -- the data ALSO needs 15% == 15
    assert answers_match(r"15\%", "15")
    assert answers_match("15", r"15\%")
    # a percent still does not match an unrelated number
    assert not answers_match(r"15\%", "16")


def test_rule_currency_stripped():
    assert normalize_answer(r"\$15.17") == normalize_answer("15.17")
    assert normalize_answer(r"\$2") == "2"


def test_braceless_latex_arguments():
    # The bug this repo would otherwise have repeated: \frac19 is 1/9.
    assert normalize_answer(r"\frac19") == "1/9"
    assert normalize_answer(r"\dfrac34") == "3/4"


def test_non_numeric_compares_by_string_only():
    assert answers_match(r"\text{B}", "B")
    assert not answers_match(r"\text{B}", "101")
    assert answer_value(r"\frac{\pi}{6}") is None
    assert not answers_match(r"\frac{\pi}{6}", "0.5236")


def test_zero_denominator_is_not_numeric():
    assert answer_value(r"\frac{1}{0}") is None


# --------------------------------------------------------------------------- #
# 3. Extraction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("step,gt,verdict", [
    ("The value of q/p is 162.", "162", "correct"),
    (r"So, the probability is $\frac{5}{12}$.", r"\frac{5}{12}", "correct"),
    ("The final answer is $7 + 52 = 59$.", "59", "correct"),
    ("Therefore, there are 36260 four-digit numbers greater than 2999.",
     "4970", "incorrect"),
    ("So, the probability that the arrangement reads XOXOX is 0.1 or 10%.",
     r"\frac{1}{10}", "correct"),
    ("So, the probability that the ticket you hold has the winning numbers "
     "is 1 in 29,322,216.", r"\dfrac{1}{29,\!322,\!216}", "correct"),
])
def test_score_trajectory_end_to_end(step, gt, verdict):
    assert score_trajectory([step], gt)["verdict"] == verdict


# Regression: the extractor originally took the LAST number in the sentence.
# English maths prose states the answer FIRST and then restates the problem, so
# that scored correct trajectories as `incorrect`. Every case below was found by
# hand-reading the `incorrect` bucket and is the reason `_resolve_span` exists.
@pytest.mark.parametrize("step,gt,verdict,want", [
    # answer stated first, problem restated after -> must NOT take the last number
    ("So, there are 15 ways to put 4 indistinguishable balls in 3 "
     "distinguishable boxes.", "15", "correct", "15"),
    ("Therefore, there are 14 positive multiples of 7 that end with the digit "
     "3 and are less than 1000.", "14", "correct", "14"),
    ("Therefore, there are 491 ways for Alpha and Beta to leave the store "
     "with 3 products collectively.", "351", "incorrect", "491"),
    # `=` chain -> the result is what follows the LAST `=`
    ("Therefore, the difference is 187 - 118 = 69.", "90", "incorrect", "69"),
    ("The sum of the numerator and denominator is: 903 + 2300 = 3203.",
     "57", "incorrect", "3203"),
    (r"Therefore, the total number of distinct squares containing at least 5 "
     r"black squares is $32+16=48$.", "73", "incorrect", "48"),
    # \boxed outranks everything
    (r"So, the final answer is: $9 + 100 = \boxed{109}$.", "200", "incorrect", "109"),
    # answer stated first, with trailing prose containing other numerals
    (r"So, the coefficient of $x^3$ in the expansion of $(x+2\sqrt{3})^7$ is "
     r"$5040$.", "5040", "correct", "5040"),
])
def test_answer_is_stated_first_not_last(step, gt, verdict, want):
    r = score_trajectory([step], gt)
    assert r["extracted"] == want, r
    assert r["verdict"] == verdict, r


def test_unextractable_is_answer_unknown_not_incorrect():
    r = score_trajectory(["We should think about this more carefully."], "101")
    assert r["verdict"] == "answer_unknown"
    assert r["verdict"] != "incorrect"


def test_empty_trajectory_is_answer_unknown():
    assert score_trajectory([], "101")["verdict"] == "answer_unknown"


def test_lookback_when_final_step_has_no_number():
    steps = ["The answer is 42.", "That completes the proof."]
    r = score_trajectory(steps, "42")
    assert r["verdict"] == "correct" and r["steps_back"] == 1


# --------------------------------------------------------------------------- #
# 4. INDEPENDENCE -- these are the tests that must fail if the axes touch
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field", sorted(LEAN_VERDICT_FIELDS))
def test_guard_rejects_every_lean_verdict_field(field):
    with pytest.raises(LeanLeakError):
        assert_no_lean_verdict({field: "anything", "ground_truth": "101"})


def test_guard_passes_clean_record():
    assert_no_lean_verdict({"ground_truth": "101", "previous_steps": ["x"]})


def test_guard_fires_on_purpose():
    """A gate that has never fired is not known to work (repo history: three
    gates returned clean zeros because they read the wrong field)."""
    fired = False
    try:
        assert_no_lean_verdict({"outcome": "valid", "ground_truth": "101"})
    except LeanLeakError:
        fired = True
    assert fired, "the independence guard did not fire on a leaked verdict"


def test_module_imports_nothing_from_the_lean_pipeline():
    """Static check: answer_correctness.py must not import the Lean side."""
    tree = ast.parse(open(MODULE, encoding="utf-8").read())
    forbidden = {"verifier", "trace_valid", "parser", "config", "model",
                 "generate", "data_loader", "failure_taxonomy"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    leaked = imported & forbidden
    assert not leaked, f"answer path imports the Lean pipeline: {sorted(leaked)}"


def test_score_trajectory_signature_takes_no_record():
    """score_trajectory must take step TEXTS and a ground truth, nothing else --
    so there is no parameter a Lean verdict could ride in on."""
    import inspect
    params = list(inspect.signature(score_trajectory).parameters)
    assert params == ["steps", "ground_truth"], params


# Regression: the therefore/so family takes the LAST copula, the existential
# "there are" family takes the FIRST. Both shapes occur and they disagree.
@pytest.mark.parametrize("step,want", [
    (r"Therefore, the remainder when the sum of $1! + 2! + \cdots + 50!$ is "
     r"divided by 15 is 3.", "3"),
    ("Therefore, there are 14 positive multiples of 7 that end with the digit "
     "3 and are less than 1000.", "14"),
    ("So, there are 15 ways to put 4 indistinguishable balls in 3 "
     "distinguishable boxes.", "15"),
    ("Therefore, the difference is 187 - 118 = 69.", "69"),
])
def test_copula_choice(step, want):
    assert extract_answer([step])["answer"] == want
