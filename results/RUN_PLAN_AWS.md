# AWS run plan — the full trajectory-level run, against $180 of credits

**Nothing has been provisioned.** This box has no AWS CLI and no credentials
(`aws: command not found`), so the plan below is the deliverable; execution needs
credentials supplied separately. Prices are published on-demand `us-east-1` rates
from memory and **must be confirmed with `aws pricing get-products` before
launch** — treat every dollar figure here as ±20%.

---

## Summary: the credits are not the binding constraint, and the bottleneck is the other one

| | brief's premise | measured |
|---|---|---|
| workload size | 23,948 step-proofs | **18,130** — Design C (77+78) was accepted, superseding 100+100 |
| GPU to match | "the committed 39 GiB runs" | **22.07 GiB (NVIDIA A10)** — the 39 GiB was a *different* experiment's total memory, not consumption |
| bottleneck | "CPU is the real bottleneck… Lean took far longer than GPU generation" | **inverted: generation is 10× the cost of verification per proof** |

The whole run costs **$11–$45 of the $180**. The decision this plan actually
turns on is *wall-clock vs comparability risk*, not money.

---

## 1. GPU hours

Generation is one Goedel-Prover proof per step of the sampled trajectories.
Design C: 9,065 steps × 2 temperatures = **18,130 proofs**.

Two measured throughputs, both from committed `run_meta.json`:

| source | hardware | batching | s/proof |
|---|---|---|---|
| `traces/temp0.0_n50_1each` | A10 | 1 prompt at a time | 50 / 356.2 s = **7.12** |
| `traces/exp2_n50_k16` | A100-40GB | `num_return_sequences=16` | 800 / 592.1 s = **0.74** |

| scenario | GPU-hours |
|---|---|
| **as the code stands today** (one prompt at a time) | **35.9** |
| if multi-prompt batching is implemented | 3.7 (A100 figure; expect **6–9** on A10G) |

**The 10× gap is not a tuning flag — it is a code change that does not exist.**
`model.generate(prompt, …, num_trajectories, batch)` takes a **single** prompt and
uses `num_return_sequences=k` to draw k samples *of that same prompt*
(`model.py:146–171`). The full run needs one proof each for 9,065 **different**
steps, which the current path does one at a time. Batching across distinct
prompts requires left-padded batch tokenisation and result splitting.

## 2. CPU hours — the brief's premise is backwards

Pooled over all six committed verification files, n = 300 verifications:

| statistic | value |
|---|---|
| median | **0.033 s** |
| p75 | 0.09 s |
| p90 | 0.28 s |
| p95 | 0.70 s |
| **mean** | **0.706 s** |
| p99 | 27.7 s |
| max | 32.6 s (`VERIFY_TIMEOUT_SECONDS = 60`) |

18,130 × 0.706 s = **3.6 CPU-hours, serial.** Against 35.9 GPU-hours.

On the n50 run specifically: generation 356 s vs verification 35 s for the same
50 records — **verification was 10× faster.**

The mean is ten times the median because ~1% of proofs run to the timeout. That
tail is the only reason the figure is not ~0.2 CPU-hours.

**Why local verification nonetheless *felt* like the bottleneck** — and this is a
real effect, just not a per-proof one:

- **REPL setup is 359–645 s per process** (README, measured), and every audit
  script pays it once. Three of my scans today never got past it.
- **Vacuity-style scans multiply the work per sample.** The patched ladder runs
  11 probes plus up to 3 contradiction probes per sample — ~14 verifications
  each. The 498-problem population scan is ~7,000 verifications, ~1.4 h, not 3 s.

So the correct reading is: *setup and probe-multiplied audits* are expensive.
*Per-proof verification of the run itself* is cheap.

## 3. Does Lean verification parallelise?

**Across processes: yes. Within a process: no.** Both halves matter.

- `verify()` runs each theorem as `Command(cmd, env=self.base_env)` against a
  **read-only** shared base environment; each command returns a *new* env and
  never mutates the base (`verifier.py:401–436`). Theorems are independent, so
  there is no ordering or state dependency between them.
- But `verify_traces.py:227` constructs **one** `LeanVerifier` → one
  `LeanServer` → one REPL process, and `LeanServer.run()` is a synchronous
  request/response. **Verification is fully serialised today.**

Parallelism therefore means N worker processes, each with its own REPL and its
own Mathlib environment, sharding the trace list. That is a small change
(`multiprocessing.Pool`, one verifier per worker) with **two costs**:

1. **Per-worker setup, 359–645 s**, paid N times but concurrently.
2. **RAM per worker.** Each REPL holds a full Mathlib environment.
   ⚠️ **This figure is not measured anywhere in the repo and is the one number
   that could break the plan.** A Lean 4 REPL with all of Mathlib is typically
   3–5 GB RSS; the highest I observed locally mid-load was 434 MB, which is not a
   settled figure. **Pre-flight step 0 below measures it before sizing anything.**

**Amdahl says keep N small.** With 3.6 CPU-h of work and ~8 min of per-worker
setup, 4 workers give ~54 min of work + 8 min setup ≈ **1 hour**; 16 workers give
~13 min + 8 min ≈ 21 min but need ~64 GB of RAM to hold 16 Mathlib envs. Saving
40 minutes is not worth a second instance.

**So the credits do not go to a big CPU box.** A `c7i.24xlarge` (96 vCPU,
~$4.28/h) would spend more on its own Mathlib build (~26 min) than it saves on a
3.6-hour serial workload.

## 4. GPU choice, and the 39 GiB deviation

**The brief asks to match "the committed 39 GiB runs". Those are not the runs the
pilot rests on, and 39 GiB was never a consumption figure.**

| run | GPU | `gpu_total_gib` | what it is |
|---|---|---|---|
| `temp0.0_n50_1each`, `temp0.2_n50_1each` | **NVIDIA A10** | **22.07** | the n50 traces the entire two-axis pilot uses |
| `exp2_n50_k16` (branch `exp/gpu-tactic-recovery`) | A100-SXM4-40GB | 39.49 | the best-of-16 experiment, a different study |

39.49 GiB is that box's **total** memory and 39.08 GiB its **free memory at
start** — neither measures what the model used. The model ran fine in 22.07 GiB.

**Match the A10, not the A100.** On AWS that is the **G5** family (NVIDIA A10G,
24 GiB):

| instance | GPU | vCPU | RAM | local NVMe | ~$/h |
|---|---|---|---|---|---|
| `g5.xlarge` | 1× A10G 24 GiB | 4 | 16 GiB | 250 GB | 1.006 |
| **`g5.2xlarge`** ← recommended | 1× A10G 24 GiB | **8** | **32 GiB** | 450 GB | **1.212** |
| `g6.xlarge` | 1× L4 24 GiB | 4 | 16 GiB | 250 GB | 0.805 |
| `p4d.24xlarge` | 8× A100 40 GiB | 96 | 1152 GiB | 8 TB | **32.77** |

`g5.2xlarge` over `g5.xlarge` buys 8 vCPU and 32 GiB, which is what lets
verification workers run **on the same box** alongside generation (§6) and
removes the need for a second instance entirely.

**Do not take `p4d.24xlarge` to "match the A100."** It is 8 GPUs for a
single-GPU job and would consume the entire $180 in 5.5 hours.

A10G is not bit-identical to A10, so record the actual `nvidia-smi` string in
`run_meta.json` (the tooling already captures `environment.gpu`) rather than
asserting equivalence. **No quantisation**, per the brief — fp16 as committed.

## 5. Setup cost, counted separately

Not free, and the filesystem lesson generalises.

| item | cost | frequency |
|---|---|---|
| `lake exe cache get` (8,639 files, multi-GB) | ~5–10 min on EC2 network | once per machine |
| full setup from clean clone, cache warm | **1,574 s ≈ 26 min** (measured) | once per clone |
| REPL up + Mathlib env per process | **359–645 s** (env alone 134–162 s) | once per worker process |
| HF model download (Goedel-Prover-SFT, 7B fp16 ≈ 14 GB) | ~5 min | once per machine |

**The Defender lesson, translated to Linux.** The finding was not really about
Defender: it was that *anything intercepting reads of ~8,600 small `.olean`
files* destroys load time — measured at **7 KB/s at 0% CPU, never completing**,
versus ~182 s with exclusions. A 2.6× effect, larger than the environment
snapshot's ~6%. The AWS analogues, in order of danger:

1. **Never put the Mathlib tree on EFS/NFS.** 8,600 small files over a network
   filesystem is precisely the pathology. This is the #1 way to waste the credits.
2. **Use the instance-store NVMe** (`/dev/nvme1n1`, 450 GB on `g5.2xlarge`) for
   `lean_project/.lake`, `~/.cache/mathlib` and the HF cache. It is local,
   free with the instance, and fast.
3. If EBS instead, **gp3 with provisioned IOPS ≥ 3000 and ≥ 250 MB/s**, not the
   burst-limited default.
4. **Leave RAM headroom for page cache** — after first load the `.olean`s are
   cached; this is much of why worker 2..N start faster than worker 1.
5. No `auditd`/eBPF file scanners or container security agents on the Mathlib path.

**Toolchain pinning is already correct and must not be touched.** Lean
`v4.32.0` / Mathlib `v4.32.0` / REPL `v1.3.18`, pinned end-to-end in the
committed `lean_project/lakefile.toml` and `lean-toolchain`. The repo's own note
records why: Mathlib `v4.32.2` against a REPL with no matching tag produced
`unexpected token` / `unknown constant`. Do not bump any of the three
independently.

**Bake an AMI after setup.** This is the single best optimisation here: build
once, snapshot the volume, and every subsequent launch (the second temperature
arm, a resumed spot instance, a re-run) skips all 26 minutes. Snapshot storage is
~$0.05/GB-month — a rounding error.

## 6. Configuration, wall-clock and dollars

**One `g5.2xlarge`. No separate CPU instance.** During generation the 8 vCPUs are
nearly idle, so verification workers consume traces as they are produced, and the
3.6 CPU-hours hide entirely inside the GPU time. Total wall-clock ≈ generation
time.

| | Scenario A — no code change | Scenario B — multi-prompt batching |
|---|---|---|
| setup (amortised via AMI) | 0.5 h | 0.5 h |
| generation | 35.9 h | 6–9 h (A10G estimate) |
| verification | pipelined, ~0 added | pipelined, ~0 added |
| **wall-clock** | **~36 h** | **~7–10 h** |
| on-demand @ $1.212/h | **~$45** | **~$11** |
| spot @ ~$0.45/h (≈63% off) | **~$17** | **~$5** |
| credits remaining of $180 | $135–163 | $169–175 |

### Recommendation: Scenario A, on spot, with `--resume`

Against the instinct to optimise the compute — because the $25 saved is not the
scarce resource and the comparability risk is real:

1. **Zero code change means zero comparability risk.** The pilot's numbers and
   the full run must sit in the same table. Multi-prompt batching means
   left-padding prompts of different lengths, which perturbs logits; that is a
   different numerical situation from `num_return_sequences=16` on a *single*
   prompt, which is all the k16 run validated. Adopting it would need its own
   equivalence study — costing more effort than the $25 it saves.
2. **Spot is safe here because resume already exists.** The k16 `run_meta.json`
   records `"resumed": true` and the CLI takes `--resume`, so an interruption
   costs the current batch, not the run. Use a persistent spot request, or
   capacity-optimized allocation, with the AMI from §5.
3. **36 h is acceptable** for a run that settles a research question, especially
   unattended.

Take Scenario B only if wall-clock is the actual constraint — and if so, budget
the equivalence check, do not skip it.

### Guardrails

- **Budget alarm at $60** (AWS Budgets action → stop instance). The plan spends
  under $45; anything approaching $60 means something is wrong, most likely the
  filesystem pathology in §5.
- **Verify pricing first.** These are recalled rates, not queried ones.
- **Two arms, one box**: T=0.0 then T=0.2 sequentially; do not launch two
  instances to parallelise two arms whose combined cost is $45.

---

## 7. Pre-flight, before provisioning anything

**Step 0 — measure the one unmeasured number.** On the first box, start a single
`LeanVerifier`, let the base env settle, and record RSS:

```bash
python -c "from verifier import LeanVerifier; v=LeanVerifier(setup=False); import os,time; time.sleep(5); print(open(f'/proc/{os.getpid()}/status').read())" &
# and watch the REPL child, not just the python parent:
ps -o pid,rss,comm -C repl
```

If RSS per REPL exceeds ~7 GB, 4 workers will not fit in 32 GiB and either the
worker count drops to 2–3 (costing ~30 min, acceptable) or the instance moves to
`g5.4xlarge` (64 GiB, ~$1.62/h, still trivial against the budget). **Nothing else
in this plan depends on an unmeasured quantity.**

**Step 1 — a 20-problem smoke run** on the provisioned box before the full 155.
Confirms throughput matches the 7.12 s/proof assumption, that the AMI is sound,
and that verification keeps up. If per-proof generation is materially slower than
7.12 s on A10G, re-cost before continuing rather than letting a 36-hour job run
on a wrong estimate.

## 8. Execution requirements, per the brief

To be satisfied when the run happens — I cannot do these without credentials:

- **`run_meta.json` carries seed and commit SHA.** Already implemented: the k16
  meta records `sampling.seed`, `git.sha`, `git.branch`, `git.dirty`, plus dataset
  fingerprint, environment, and output sha256. Requirement met by existing
  tooling; confirm `git.dirty == false` before launching.
- **Cost logged.** Record instance type, lifecycle (spot/on-demand), start and
  stop timestamps, and the Cost Explorer figure for the run's tag. Tag the
  instance (e.g. `Project=trace-validity`, `Run=designC-full`) at launch so the
  cost is attributable.
- **Instance terminated immediately on completion, API-confirmed.** Terminate,
  then confirm via API rather than assuming — `aws ec2 describe-instances
  --instance-ids <id> --query 'Reservations[].Instances[].State.Name'` returning
  `shutting-down` then `terminated`. Belt and braces: set
  `--instance-initiated-shutdown-behavior terminate` and have the run script
  `shutdown -h now` on exit, so a crashed orchestrator still stops billing.
  Also confirm the EBS volume is deleted (`DeleteOnTermination=true`) — a
  forgotten 100 GB volume quietly bills against the credits.

## 9. What I need to proceed

1. **Confirmation of the workload**: 18,130 step-proofs (Design C), not 23,948.
2. **AWS credentials** with EC2 launch rights, and confirmation of region.
3. **A decision on Scenario A vs B** (my recommendation: A, on spot).
4. Confirmation that **`g5.2xlarge` / A10G** is accepted as the match to the
   committed A10 runs, given the 39 GiB figure was not a consumption number.
