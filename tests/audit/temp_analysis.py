"""Generate results/TEMPERATURE_AND_VACUITY.md from committed artifacts.

Answers the two questions the summary could not:
  - what do the 37 `valid` traces actually assert?  (results/vacuity_scan.json)
  - what did temperature 0.2 actually change?       (the two traces.jsonl files)

Reads only committed files. No Lean, no GPU. Run:
  python tests/audit/temp_analysis.py > results/TEMPERATURE_AND_VACUITY.md
"""
import difflib, io, json, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
J = lambda p: [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]

a = {r["sample_index"]: r for r in J("traces/temp0.0_n50_1each/traces.jsonl")}
b = {r["sample_index"]: r for r in J("traces/temp0.2_n50_1each/traces.jsonl")}
va = {r["sample_index"]: r for r in J("results/verify3_temp0.0.jsonl")}
vb = {r["sample_index"]: r for r in J("results/verify3_temp0.2.jsonl")}
vac = json.load(io.open("results/vacuity_scan.json", encoding="utf-8"))

P = print
P("# What the 74% actually contains, and what temperature actually changed")
P()
P("Two questions the summary could not answer, now answered by asking Lean rather")
P("than by reading.")
P()
P("- Vacuity scan: `tests/audit/vacuity_scan.py` → `results/vacuity_scan.json`")
P("- This document: `tests/audit/temp_analysis.py`")
P("- Verification pass: `results/verify3_temp0.{0,2}.jsonl`")
P()
P("---")
P()
P("## 1. HEADLINE: sample 42 is a false positive")
P()
P('Issue #1 asks the project to "debug for lean4 validity check (whether getting')
P('false positives like invalid traces showing up as valid in the checker)".')
P("**Here is one.**")
P()
P("```lean")
P(a[42]["formal_statement"].strip())
P("```")
P()
P("Every hypothesis is arithmetically false, and so is the goal:")
P()
P("| claim | asserted | actual |")
P("|---|---|---|")
P("| `9! * 5! * 2!` | 7,257,600 | **87,091,200** |")
P("| `8! * 6!` | 40,320 | **29,030,400** |")
P("| `7257600 / 40320` | 9 | **180** |")
P("| `(9!*5!*2!)/(8!*6!)` — **the goal** | 9 | **3** |")
P()
P("The premises are mutually inconsistent, so `False` follows from them and")
P("therefore **every** goal does. Lean confirms it: the probe")
P("`theorem contra (h₀ …) (h₁ …) (h₂ …) : False := by simp_all` succeeds. The")
P("model's proof (`simp_all [factorial] <;> norm_num <;> rfl`) works precisely")
P("because `simp_all` finds the contradiction.")
P()
P(f"- Our verdict: **`{va[42]['outcome']}`**")
P(f"- Dataset `state`: **{va[42]['state']}**")
P(f"- Axiom audit: `{va[42]['axioms']}` — clean, so the axiom check cannot catch this")
P()
P("A trace proving a **false statement** from **contradictory premises** counts")
P("toward the 74%, at both temperatures, and the dataset agrees it is a success.")
P("This is the exact failure mode issue #1 was opened to find. No prior pass caught")
P("it — the earlier hand-read of this sample classified it `proves_target`. Only")
P("asking Lean whether the hypotheses are consistent found it.")
P()
P("---")
P()
P("## 2. Vacuity scan: what do the 37 positives assert?")
P()
P("Every probe replaces the model's proof entirely, so this measures the *dataset's")
P("goal*, not the model's work. `with_reducible rfl` is the load-bearing choice: it")
P("closes `X = X` but will not unfold `Nat.factorial 4` to `24`, which is what")
P('separates "asserts nothing" from "asserts a real computation".')
P()
P("| class | T=0.0 | T=0.2 | what it means |")
P("|---|---|---|---|")
rows = {T: {} for T in ("0.0", "0.2")}
for T in ("0.0", "0.2"):
    for r in vac[T]:
        rows[T][r["class"]] = rows[T].get(r["class"], 0) + 1
MEAN = {
    "1_goal_is_True": "goal is literally `True`",
    "2_hypotheses_contradictory": "premises inconsistent — **anything** is provable",
    "3_goal_restates_a_hypothesis": "goal IS a hypothesis, verbatim (`assumption` closes it)",
    "4_syntactic_tautology": "substituting its own hypotheses makes the goal `X = X`",
    "5_ground_computation": "closed by `rfl`/`decide` — real arithmetic, no reasoning",
    "6_contentful": "needs the hypotheses in a non-trivial way",
}
for k in sorted(MEAN):
    P(f"| `{k}` | **{rows['0.0'].get(k,0)}** | **{rows['0.2'].get(k,0)}** | {MEAN[k]} |")
n0 = sum(rows["0.0"].get(k, 0) for k in
         ("1_goal_is_True", "2_hypotheses_contradictory",
          "3_goal_restates_a_hypothesis", "4_syntactic_tautology"))
g0 = rows["0.0"].get("5_ground_computation", 0)
c0 = rows["0.0"].get("6_contentful", 0)
P()
P(f"**{n0} of 37 positives ({n0/37:.0%}) assert nothing at all.** Another {g0} are ground")
P(f"arithmetic. Only {c0} of 37 ({c0/37:.0%}) require a real inference.")
P()
P("Rewritten as rates over all 50 samples:")
P()
P("| claim | count | rate |")
P("|---|---|---|")
P("| produced a compiling Lean proof of the target | 37/50 | **74%** |")
P(f"| …of a goal that asserts *something* | {g0+c0}/50 | **{(g0+c0)/50:.0%}** |")
P(f"| …of a goal needing more than ground arithmetic | {c0}/50 | **{c0/50:.0%}** |")
P()
P("**74% is a compile rate. The content rate is "
  f"{(g0+c0)/50:.0%}, and the reasoning rate is {c0/50:.0%}.**")
P()
P("The scan is deliberately conservative — it classifies only what it can *prove*")
P("vacuous, so these are lower bounds. Two cases it under-called, found by reading:")
P("sample 22's conclusion (`5*6*8 + 5*6*8 = 480`) uses none of its five bound")
P("variables and none of the numbers in its own hypotheses; sample 3's goal is the")
P("conjunction of its own four hypotheses. Both scored `6_contentful` because the")
P("probes cannot strip an implication or split a conjunction.")
P()
P("### The vacuous ones, named")
P()
P("| sample | class | goal |")
P("|---|---|---|")
for r in vac["0.0"]:
    if r["class"][0] in "1234":
        P(f"| {r['sample']} | `{r['class']}` | `{r['goal'][:62]}` |")
P()
P("---")
P()
P("## 3. Temperature: 80% of proofs were rewritten, 5% of verdicts moved")
P()
ident = [i for i in a if a[i]["full_code"] == b[i]["full_code"]]
diff = [i for i in sorted(a) if a[i]["full_code"] != b[i]["full_code"]]
sims = sorted((round(difflib.SequenceMatcher(None, a[i]["full_code"],
                                             b[i]["full_code"]).ratio(), 3), i)
              for i in diff)
med = sorted(s for s, _ in sims)[len(sims) // 2]
chg = [i for i in diff if va[i]["outcome"] != vb[i]["outcome"]]
P("The summary reported McNemar p = 1.000 on 2 discordant pairs and called it")
P('"no power". True, but incomplete: it never asked whether T=0.2 changed the')
P("generations at all. It did, substantially.")
P()
P("| | n | % |")
P("|---|---|---|")
P(f"| generations byte-identical to T=0.0 | {len(ident)}/50 | {len(ident)/50:.0%} |")
P(f"| **generations materially different** | **{len(diff)}/50** | **{len(diff)/50:.0%}** |")
P(f"| …of those, verdict UNCHANGED | {len(diff)-len(chg)}/{len(diff)} | **{(len(diff)-len(chg))/len(diff):.0%}** |")
P(f"| …of those, verdict flipped | {len(chg)}/{len(diff)} | {len(chg)/len(diff):.0%} |")
P()
P(f"Character-level similarity of the {len(diff)} differing pairs: median **{med:.3f}**,")
P(f"minimum **{sims[0][0]:.3f}** (sample {sims[0][1]}). These are not cosmetic reorderings —")
P("the least similar pairs share under half their characters, i.e. genuinely")
P("different proofs of the same goal.")
P()
P("**This turns the temperature result from an absence of evidence into a positive")
P(f"one.** The model rewrote {len(diff)/50:.0%} of its proofs, often substantially, and")
P(f"{(len(diff)-len(chg))/len(diff):.0%} of those landed on the identical verdict. The outcome is robust to how")
P("the proof is written.")
P()
P("### And section 2 explains why")
P()
P("The vacuity classification is **identical at both temperatures — all six counts")
P("match exactly.** That is not coincidence. Temperature changes the *proof*; the")
P("*goal* is fixed by the prompt; and section 2 shows the goal is what decides the")
P(f"outcome. {n0} of 37 goals cannot be failed and {g0} more are closed by evaluation, so")
P("there is very little left for sampling to move.")
P()
P('So "temperature makes no difference" is not a null result about the model. It is')
P("a statement about **this benchmark**: the goals are too easy for decoding")
P("strategy to matter.")
P()
P("### The two that flipped")
P()
for i in chg:
    s = next(v for v, k in sims if k == i)
    P(f"- **Sample {i}**: `{va[i]['outcome']}` at T=0.0 → `{vb[i]['outcome']}` at T=0.2 "
      f"(text similarity {s:.3f})")
P()
P("Both are single samples with no replication, and they cancel exactly — which is")
P("why the aggregate is 37/50 at both temperatures.")
P()
P("---")
P()
P("## 4. Trajectories: the 500-record baseline is 50 records")
P()
base = J("traces/temp_0.jsonl")
by = {}
for r in base:
    by.setdefault(r["sample_index"], []).append(r)
ntraj = len(next(iter(by.values())))
allid = sum(1 for rs in by.values() if len({r["raw_output"] for r in rs}) == 1)
uniq = sum(len({r["raw_output"] for r in rs}) for rs in by.values())
P(f"`traces/temp_0.jsonl` holds {len(base)} records: {len(by)} samples × {ntraj} trajectories.")
P()
P("| | value |")
P("|---|---|")
P(f"| samples whose {ntraj} trajectories are ALL byte-identical | **{allid}/{len(by)}** |")
P(f"| distinct generations in the file | **{uniq}** of {len(base)} |")
P(f"| exact duplicates | **{len(base)-uniq}** ({(len(base)-uniq)/len(base):.0%}) |")
P()
P("Greedy decoding is deterministic, so all ten trajectories per sample are the same")
P(f"bytes. **{(len(base)-uniq)/len(base):.0%} of that file is duplication.** It cost 10× the generation time for")
P("zero additional information, and any statistic computed over its 500 rows as if")
P(f"they were independent has an effective n of {uniq}, not {len(base)}.")
P()
P("That is why the current runs use one trajectory per sample — correct at T=0.0.")
P("It is also why T=0.2 needs *more* than one: at T>0 trajectories genuinely differ")
P("(section 3 measures how much), and multiple draws per sample is the only design")
P("under which a temperature effect could be detected at all.")
P()
P("---")
P()
P("## What this changes")
P()
P("| claim | before | after |")
P("|---|---|---|")
P("| validity | 37/50 = 74% | unchanged — but it is a **compile** rate |")
P(f"| content | not measured | **{g0+c0}/50 = {(g0+c0)/50:.0%}** assert something |")
P(f"| reasoning | not measured | **{c0}/50 = {c0/50:.0%}** need more than arithmetic |")
P('| false positives | "zero" | **at least one confirmed — sample 42** |')
P("| vacuous positives | 1, hand-found | **14 of 37**, Lean-verified, a lower bound |")
P('| temperature | "no power" | 80% of proofs rewritten, 95% same verdict |')
P("| baseline set | 500 traces | **50 traces**, 90% duplication |")
