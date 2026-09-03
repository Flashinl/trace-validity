"""The contentless-class list is duplicated in two places. Pin them together.

`tests/audit/two_axis.py` cannot import `tests/audit/vacuity_scan.py` without
dragging in the Lean verifier, so the class tuple is copied. A copy that drifts
would silently reclassify a contentless goal as contentful in the grid -- the
exact failure the vacuity patch exists to fix. Read both by AST, no imports, no
Lean.

Run: python -m pytest tests/test_two_axis_sync.py -q
"""
import ast
import os

_AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit")


def _tuple_const(path, name):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found at module level in {path}")


def test_contentless_class_lists_agree():
    scan = _tuple_const(os.path.join(_AUDIT, "vacuity_scan.py"),
                        "CONTENTLESS_CLASSES")
    grid = _tuple_const(os.path.join(_AUDIT, "two_axis.py"),
                        "CONTENTLESS_CLASSES")
    assert scan == grid, (
        "the contentless class lists have drifted:\n"
        f"  vacuity_scan.py: {scan}\n"
        f"  two_axis.py    : {grid}\n"
        "A class present in the scan but missing here is counted as CONTENTFUL "
        "in the grid, which inflates the valid row."
    )


def test_every_class_the_classifier_can_return_is_accounted_for():
    """No class may be silently neither contentless nor a known contentful one."""
    src = open(os.path.join(_AUDIT, "vacuity_scan.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "classify")
    returned = {n.value.value for n in ast.walk(fn)
                if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)}
    known = set(_tuple_const(os.path.join(_AUDIT, "vacuity_scan.py"),
                             "CONTENTLESS_CLASSES"))
    known |= {"5_ground_computation", "6_contentful"}
    unaccounted = returned - known
    assert not unaccounted, (
        f"classify() can return {sorted(unaccounted)}, which is in neither the "
        "contentless band nor the known contentful classes. Add it to "
        "CONTENTLESS_CLASSES or to this test's known set deliberately."
    )
