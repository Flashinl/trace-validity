# trace-validity

Does an **invalid reasoning trace** still land on a **correct answer**?

The setting is formal: [Goedel-Prover-SFT](https://huggingface.co/Goedel-LM/Goedel-Prover-SFT)
samples proof trajectories for the first 50 problems of
[liuchengwu/FormalStep](https://huggingface.co/datasets/liuchengwu/FormalStep),
and **Lean 4 + Mathlib** is the judge — no LLM grader, no string match.

Per trajectory we record two things:

| field | definition |
| --- | --- |
| `trace_valid` | the proof has **no syntax errors and no unknown-constant/identifier errors** — i.e. the reasoning is well-formed Lean that refers to things that exist |
| `end_correct` | Lean reports **zero errors and no `sorry`** — the theorem is actually proved |

Then we sweep temperature and look at how the two move.

---

## Two stages, deliberately separate

Generation needs a GPU. Verification needs a built Mathlib and no GPU at all.
They are separate processes that communicate only through files in `results/`,
so a Colab timeout in one **cannot** destroy the other's work.

```
                 GPU runtime                         CPU runtime
  ┌──────────────────────────────┐      ┌────────────────────────────────┐
  │ --stage generate             │      │ --stage verify                 │
  │ FormalStep -> Goedel-Prover  │ ---> │ traj_temp{T}.json -> Lean 4    │
  │ traj_temp{T}.jsonl (resume)  │      │ results_temp{T}.jsonl (resume) │
  │ traj_temp{T}.json            │      │ results_temp{T}.json           │
  └──────────────────────────────┘      └────────────────────────────────┘
                                                        |
                                          ┌─────────────▼──────────────┐
                                          │ --stage analyze            │
                                          │ summary.csv, figs/*.png    │
                                          └────────────────────────────┘
```

Both stages append one record per question to a `.jsonl` **as it finishes** and
skip ids already present on startup. A disconnect costs you the single item in
flight; re-running the same command picks up exactly where it stopped.

## CLI

```bash
python3 trace_valid.py --temp 0 --stage generate            # GPU
python3 trace_valid.py --temp 0 --stage verify              # CPU + Lean
python3 trace_valid.py --stage analyze --sweep 0 0.2 0.5 0.8 1
python3 trace_valid.py --temp 0                             # all three, one box
```

`--sweep` also works for `generate`/`verify` to run several temperatures in
sequence. `python3 trace_valid.py --help` lists everything.

## Layout

```
trace_valid.py            argparse entrypoint, dispatches to a stage
src/config.py             prompt format, paths, pins, jsonl resume helpers
src/generate.py           stage 1 (GPU)
src/verify.py             stage 2 (Lean)
src/analysis.py           stage 3 (pandas + matplotlib)
scripts/setup_lean.sh     elan + mathlib4 @ v4.19.0 + cache get + lake build
notebooks/trace_validity.ipynb   one notebook, STAGE switch in the first cell
```

---

## Stage 1 — generate (GPU)

### Prompt format — this is the part that matters

Goedel-Prover-SFT is a **formal** prover, not a chat model. Handing it the
natural-language `problem` field makes it invent its own theorem statement,
which then can't be scored against the dataset's statement. It wants a partial
Lean file to continue:

```
Complete the following Lean 4 code:

```lean4
import Mathlib
import Aesop

set_option maxHeartbeats 400000
/-- <row["problem"]> -/
theorem foo ... := by
```

Construction, in order:

* `HEADER` = `"import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 400000\n"`
* `informal` = `"/-- " + row["problem"] + " -/\n"`
* `statement` = `row["formal_statement"]` with the trailing `sorry` stripped, so
  it ends at `:= by`
* the prompt is **left unclosed** — no closing ``` — because the model's job is
  to continue it.

### Sampling

* `max_new_tokens=1536`. The model's context is 4096 **total**; setting 20000
  does not give you a longer proof, it gives you an error.
* 10 trajectories per question via `num_return_sequences`, `do_sample=True`,
  `temperature=T`, `top_p=0.95`.
* **Except at temperature 0**: decoding is greedy, so 10 samples would be 10
  identical strings. `n` is forced to 1 and `greedy: true` / `n_traj: 1` is
  recorded in the output so the analysis knows why that row has 50 trajectories
  instead of 500.
* `device_map="auto"`. Do **not** call `torch.set_default_device("cuda")` — it
  makes tokenizer ops build tensors on the GPU and breaks them.

Output: `results/traj_temp{T}.jsonl` (append-as-you-go) → `results/traj_temp{T}.json`.

## Stage 2 — verify (CPU + Lean 4)

### Lean setup

`bash scripts/setup_lean.sh` does exactly this, idempotently:

```bash
curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none
git clone --depth 1 --branch v4.19.0 https://github.com/leanprover-community/mathlib4.git
cd mathlib4
elan toolchain install $(cat lean-toolchain)
lake exe cache get      # MANDATORY
lake build
```

Two failure modes worth naming:

* **`lake exe cache get` is not optional.** Without it, `lake build` compiles
  Mathlib from source — hours, not minutes.
* **Never hand-write `lean-toolchain`.** Let the cloned repo's own file drive
  `elan`. A hand-written version that disagrees with the checkout gives
  `incompatible header` at import time.

### Checking

* One `lean_interact` server. `import Mathlib\nimport Aesop` runs **once** to get
  a base env id, and every proof is then `Command(cmd=..., env=BASE)`.
  Re-importing per proof costs 30–60s × ~500 proofs.
* **Smoke test before any real work**: `example : (2:ℝ) + 2 = 4 := by norm_num`
  must return no errors, and the same with `= 5` must return one. If either
  fails we raise instead of reporting numbers from a broken server — a server
  that silently answers "no errors" to everything would score 100% validity and
  100% accuracy. (`#check norm_num` is *not* a valid probe: `norm_num` is a
  tactic, not a term, so it fails for an unrelated reason.)

Per completion, before it reaches Lean:

1. repair byte-level BPE artefacts if present (`Ġ`/`Ċ` — the inverse of GPT-2's
   `bytes_to_unicode`; skipped entirely when those characters are absent,
   because the mapping is lossy for genuine unicode like `ℝ` and `∀`),
2. cut at the closing ```` ``` ````,
3. drop a dangling unclosed `/-` comment,
4. graft the tactic block onto the **dataset's** statement:
   `informal + statement + body`.

Step 4 is the important one: the model is free to restate the theorem in its
completion, sometimes wrong or weaker. Scoring that would be scoring a different
problem, so the theorem line always comes from the dataset and only the tactic
block comes from the model.

Recorded per trajectory: `trace_valid`, `end_correct`, `syntax_err`,
`unknown_err`, `unsolved_goals`, `has_sorry`, `n_errors`, and the first 3 error
strings.

Output: `results/results_temp{T}.jsonl` → `results/results_temp{T}.json`.

## Stage 3 — analyze

* `results/summary.csv` — one row per temperature: trace validity rate,
  accuracy, `acc_given_valid`, `acc_given_invalid`, syntax / unknown / unsolved
  error rates, and the Mathlib tag.
* `results/crosstab.csv` — the 2×2 of `trace_valid` × `end_correct`.
* `figs/temp_sweep.png` — temperature on x, trace validity and accuracy as two
  curves.
* `figs/crosstab.png` — the 2×2 rendered as a table.

---

## Colab

One notebook, `notebooks/trace_validity.ipynb`, with a `STAGE` switch in the
first cell. Set `STAGE` and run all cells; every cell is safe to re-run and
nothing already in `results/` is recomputed. The exact cells:

### Cell 1 — config

```python
STAGE = "generate"          # "generate" | "verify" | "analyze" | "all"
TEMPS = [0, 0.2, 0.5, 0.8, 1.0]
N_QUESTIONS = 50
N_TRAJ = 10                 # forced to 1 at temperature 0 (greedy)
```

Pick the runtime to match: **generate → GPU**, **verify / analyze → CPU**
(a GPU runtime for verify just burns quota).

### Cell 2 — clone + install

```python
import os, subprocess
REPO_URL = "https://github.com/<you>/trace-validity.git"
REPO_DIR = "/content/trace-validity"
if not os.path.isdir(REPO_DIR):
    subprocess.run(["git", "clone", REPO_URL, REPO_DIR], check=True)
os.chdir(REPO_DIR)

NEEDS_GPU = STAGE in ("generate", "all")
NEEDS_LEAN = STAGE in ("verify", "all")

!pip install -q -r requirements.txt
if NEEDS_GPU:
    !pip install -q -r requirements-gpu.txt      # torch/transformers/vllm: GPU only
if NEEDS_LEAN:
    !pip install -q -r requirements-verify.txt
    !bash scripts/setup_lean.sh mathlib4         # skipped if already built
```

### Cell 3 — mount Drive, restore

```python
from google.colab import drive
drive.mount('/content/drive')
DRIVE = "/content/drive/MyDrive/trace-validity"
!mkdir -p {DRIVE} results figs
!cp -n {DRIVE}/results/* results/ 2>/dev/null || true
# Restore the prebuilt Mathlib tarball instead of rebuilding it (~30 min saved)
if NEEDS_LEAN and not os.path.isdir("mathlib4") and os.path.exists(f"{DRIVE}/mathlib4_build.tar.gz"):
    !tar xzf {DRIVE}/mathlib4_build.tar.gz -C .
```

### Cell 4 — run

```python
for T in (TEMPS if STAGE != "analyze" else []):
    !python3 trace_valid.py --stage {STAGE} --temp {T} --n-questions {N_QUESTIONS}
if STAGE in ("analyze", "all"):
    !python3 trace_valid.py --stage analyze --sweep {" ".join(str(t) for t in TEMPS)}
```

### Cell 5 — back up

```python
!mkdir -p {DRIVE}/results {DRIVE}/figs
!cp -r results/* {DRIVE}/results/ 2>/dev/null || true
!cp -r figs/* {DRIVE}/figs/ 2>/dev/null || true
if os.path.isdir("mathlib4") and not os.path.exists(f"{DRIVE}/mathlib4_build.tar.gz"):
    !tar czf {DRIVE}/mathlib4_build.tar.gz mathlib4
```

### Cell 6 — display (analyze only)

```python
import pandas as pd
from IPython.display import Image, display
display(pd.read_csv("results/summary.csv"))
display(Image("figs/temp_sweep.png"), Image("figs/crosstab.png"))
```

**Suggested order:** GPU runtime with `STAGE="generate"` for every temperature,
then switch to a CPU runtime with `STAGE="verify"`, then `STAGE="analyze"`.
Cell 5 puts everything in Drive between runtimes.

---

## Two things worth calling out

### 1. `end_correct` implies `trace_valid`, so one cell of the 2×2 is empty by construction

The study asks about the *invalid trace → correct answer* cell. Under formal
verification that cell **cannot be populated**: `end_correct` requires Lean to
report zero errors, and `trace_valid` is the absence of a *subset* of those
errors (syntax, unknown constant). A proof with a syntax error is not a proof
Lean accepts. So:

```
                     end_correct=False   end_correct=True
trace_valid=False           n                  0        <- empty by construction
trace_valid=True            n                  n
```

This is a **design question about the study, not a bug in the code**. The `0` is
still reported rather than hidden, and `analyze` prints a note when it sees it.
If the question you actually want to answer is "can broken reasoning still reach
the right answer", a formal verifier is the wrong instrument for it, because it
defines away the case. Options, roughly in order of how much they change the study:

* **Reframe the measurement.** Keep Lean, and treat `trace_validity` as the
  outcome and the error-type breakdown (`syntax` vs `unknown` vs
  `unsolved_goals`) as the interesting signal: *how* proofs fail as temperature
  rises, rather than whether invalid traces succeed.
* **Loosen `trace_valid` so the two are genuinely independent.** Score the
  *intermediate* steps — e.g. does the trace use a lemma that doesn't apply,
  take a detour, or contain a step that is individually unsound — while still
  reaching a `sorry`-free proof. FormalStep is a step-level dataset, so this is
  the version of the study its structure actually supports.
* **Change the verifier.** In an informal setting (natural-language math, graded
  by answer match) invalid traces *can* produce correct answers, and that cell
  fills. That is a different experiment, not this one.

### 2. Lean results are not comparable across Mathlib versions

A proof that checks under one Mathlib may fail under the next: lemma names get
renamed, simp sets change, `norm_num` extensions come and go. A `trace_validity`
number without a Mathlib version attached is not interpretable.

So the tag is **pinned** (`v4.19.0`, `src/config.py:MATHLIB_TAG`) and **recorded**
— `mathlib_tag` goes into every `results_temp{T}.json` and every row of
`summary.csv`, resolved from the checkout's own `lean-toolchain` at verify time,
not from the constant. If you rebuild against a different Mathlib, re-verify
everything rather than mixing results files; the `unknown_err` rate in
particular will move for reasons that have nothing to do with the model.
