# Testing notes

## The standing rule: a clean result from an unfired gate is not evidence

> **Any gate, classifier, probe, or extractor must be shown to fire on a negative
> control before its clean result is believed.**
>
> A zero that has never been made non-zero is indistinguishable from a zero
> produced by reading the wrong field, the wrong file, or the wrong shape of
> input. Demonstrate the failure mode on purpose, then trust the pass.

This is not a style preference. It is the response to a repeated, specific defect
in this repository: **four separate gate-style components have returned confident
clean results while measuring nothing.** In every case the code ran, the tests
passed, and the number was wrong.

### The four

| # | component | the clean result | what was actually wrong | how it was caught |
|---|---|---|---|---|
| 1 | pipeline liveness (finding 1-D) | sub-10 ms `valid` results looked like a pipeline that never elaborated | nothing — but it was unprovable either way until controls ran | `phase1_live.py`: `(2:Nat)+2 = 5` → `compile_error` in 107 ms, unknown identifier → 4 ms. A dead pipeline would have returned `valid` for all three. |
| 2 | dead branches (finding 1-C) | `timeout` and `verifier_crash` never observed across 100 traces | `verifier_crash` **was** live and unreachable only by accident | `phase1_deadbranches.py`: forced a 0.01 s budget → `timeout`; a nonexistent environment id → `verifier_crash`. 4/4 fired. |
| 3 | axiom escape hatch (finding 1-F) | 0 `axiom` declarations across all traces | the gate did not exist — no `collectAxioms` anywhere in `verifier.py` | fired on purpose: `axiom cheat : (2:Nat)+2 = 5` returned **`valid` in 9 ms** |
| 4 | answer extraction (2026-09-02) | 0.2% extraction failure, a suspiciously clean rate | the extractor took the **last** number in the sentence; maths prose states the answer **first** and restates the problem after, so correct trajectories scored `incorrect` | hand-reading the `incorrect` bucket. "there are **15** ways to put 4 balls in **3** boxes" extracted `3`. Fixing it moved **133 trajectories**. |

Defect 4 is the clearest illustration: the *failure rate* was clean, so nothing
looked wrong. The bug lived entirely in the rows that succeeded.

### What this looks like in practice

Three mechanisms, in rough order of strength:

1. **A preflight that aborts the run.** `tests/audit/vacuity_scan.py` ships a
   `PREFLIGHT` table pairing every new probe with a statement it *must* close
   and one it *must not*, checked before any real work; the scan raises
   `SystemExit` rather than emitting numbers from a probe that misbehaves. A
   probe never seen to fire is not known to work; a probe never seen to stay
   silent is not known to be sound. **Both directions are required.**
2. **A test that asserts the guard raises.** `tests/test_answer_correctness.py`
   parametrises over every forbidden field so the independence guard is shown to
   reject each one individually, plus an explicit
   `test_guard_fires_on_purpose`.
3. **A static check verified against a known violator.** The AST import gate was
   run against a synthetic `import verifier` module, a `from config import …`
   module, and the real `verifier.py` — catching all three — before its clean
   result on `answer_correctness.py` was accepted.

### When a control cannot be fired, say so

Finding 1-C stayed open for a full cycle because `timeout` could not be
provoked: the `decide` probe hit `maxRecDepth` and returned `compile_error`
first. The honest record was "**unfired, finding stays unresolved**", not
"no timeouts observed, therefore none occur". Carry the unresolved state rather
than converting an absence of evidence into a result.

### Checklist for a new gate, probe, or classifier

- [ ] a positive control that makes it fire
- [ ] a negative control that keeps it silent
- [ ] both run automatically, not once by hand
- [ ] the run aborts (or the test fails) if either misbehaves
- [ ] if a control cannot be constructed, the limitation is written down in the
      report, not omitted
- [ ] for anything reading a file or field by name, one test that would fail if
      the name were wrong

## Related conventions already in force

- **Report intervals, always**, and never to more precision than n supports. A
  point estimate with no interval invites reading `phi = +0.009` as "no
  association proved", which n = 49 cannot support.
- **Samples within a problem are not independent draws.** Compute at the problem
  level or declare the clustering. FormalStep ships ~5 trajectories per problem.
- **If you run many tests, say how many and apply a correction.**
- **Importing an audit module must not run it.** `vacuity_scan.py` guards its
  work behind `main()` for this reason — it previously re-probed every pass and
  overwrote a committed artifact as an import side effect.
