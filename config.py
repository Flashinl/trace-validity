import os

MODEL_NAME = "Goedel-LM/Goedel-Prover-SFT"
DATASET_NAME = "liuchengwu/FormalStep"
DATASET_SPLIT = "train"
NUM_SAMPLES = 50
NUM_TRAJECTORIES = 10

# ---------------------------------------------------------------------------
# Sample selection
# ---------------------------------------------------------------------------
# FormalStep is one row per CoT step, ordered by problem (~62 steps/problem,
# 500 problems in train). Taking the first 50 rows therefore samples 50 steps of
# ONE problem — the temp-0 run in traces/temp_0.jsonl is 500 trajectories over
# math_train_counting_and_probability_408 and nothing else.
#
# `distinct_problems` takes one step from each of 50 different problems,
# striding across the ordered problem list so the selection spans the split
# instead of its first 5%. Deterministic: no RNG anywhere in selection.
#
# `head` reproduces the original single-problem behaviour, kept so the earlier
# run can be regenerated exactly.
SAMPLE_STRATEGY = "distinct_problems"
PROBLEM_STRIDE = 10          # 500 problems / stride 10 -> 50 selected
STEP_SELECTION = "first"     # "first" | "median" step within each problem

# ---------------------------------------------------------------------------
# Lean pinning (issue #6) — these three MUST move together
# ---------------------------------------------------------------------------
# mathlib4 tag vX.Y.Z always declares leanprover/lean4:vX.Y.Z in its
# lean-toolchain, and lean_interact's REPL (augustepoiroux/repl @ v1.3.18)
# publishes a matching tag `v1.3.18_lean-toolchain-vX.Y.Z`. Keeping the Mathlib
# tag name equal to the Lean version is what keeps all three in lockstep.
#
# Verified: the REPL rev has 94 lean-toolchain tags, topping out at v4.32.0
# stable. There is NO v4.32.2 tag — which is precisely why a project on Mathlib
# v4.32.2 produced "unexpected token" / "unknown constant".
LEAN_VERSION = "v4.32.0"
LEAN_TOOLCHAIN = f"leanprover/lean4:{LEAN_VERSION}"
MATHLIB_REV = LEAN_VERSION
LEAN_PROJECT_DIR = os.path.join(os.path.dirname(__file__), "lean_project")

# Per-verification wall-clock budget. Exceeding it is its own outcome
# (`timeout`), never silently folded into "invalid".
VERIFY_TIMEOUT_SECONDS = 60

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
TRACES_DIR = os.path.join(os.path.dirname(__file__), "traces")

LEAN_HEADER = """import Mathlib
import Aesop

set_option maxHeartbeats 400000

"""

# ---------------------------------------------------------------------------
# FormalStep dataset fields (issue #2)
# ---------------------------------------------------------------------------
# FormalStep rows carry BOTH natural-language prose and Lean 4 source. Feeding
# the prose to a Lean prover is issue #2. Verified against the real dataset
# (liuchengwu/FormalStep, train, 30809 rows) — the schema is:
#
#   problem           str   NL problem prose      e.g. "Determine $\\sqrt[6]{...}$
#                                                       without a calculator."
#   current_step      str   NL chain-of-thought step being formalized
#   previous_steps    list  preceding NL CoT steps
#   formal_statement  str   >>> THE LEAN 4 STATEMENT <<<  ends ":= by sorry"
#   proof             str   reference Lean 4 proof (statement + tactic block)
#   ground_truth      str   final numeric answer ("101") — NOT a proof
#   problem_unique_id str   provenance id
#   level, type       str   MATH-dataset difficulty / topic
#   state             str   "Success of Proof" / etc.
#
# `formal_statement` is the prover input. `problem` is prose and must never be.
FORMAL_STATEMENT_FIELD = "formal_statement"
INFORMAL_STEP_FIELD = "current_step"
REFERENCE_PROOF_FIELD = "proof"

# Fields whose absence is a hard error — generation is meaningless without them.
REQUIRED_DATASET_FIELDS = (FORMAL_STATEMENT_FIELD,)

# ---------------------------------------------------------------------------
# Goedel-Prover-SFT prompt template (issue #3)
# ---------------------------------------------------------------------------
# VERBATIM from the official evaluation script:
#   https://github.com/Goedel-LM/Goedel-Prover  ->  eval/step1_inference.py
# which is the repository linked from the HuggingFace model card for
# Goedel-LM/Goedel-Prover-SFT. The model card itself documents no prompt
# template, and the `chat_template` in the model's tokenizer_config.json is an
# inherited DeepSeek-Coder "AI programming assistant" chat template that has
# nothing to do with theorem proving — do NOT use it.
#
# This is a *prefix-completion* prompt, not a chat prompt: it deliberately ends
# in the middle of an unterminated ```lean4 fence. The model continues the Lean
# source and emits the closing fence itself.
#
# Do not edit without re-checking upstream.
GOEDEL_LEAN4_HEADER = (
    "import Mathlib\nimport Aesop\n\n"
    "set_option maxHeartbeats 0\n\n"
    "open BigOperators Real Nat Topology Rat\n\n"
)

PROMPT_TEMPLATE = (
    "Complete the following Lean 4 code with explanatory comments preceding "
    "each line of code:\n\n```lean4\n{header}{informal_prefix}{formal_statement}"
)

# Regex the official script uses to recover the finished Lean file from
# (prompt + completion). Kept here so prompt and extraction stay in sync.
LEAN4_BLOCK_PATTERN = r"```lean4\n(.*?)\n```"

# Official SamplingParams from eval/step1_inference.py.
TOP_P = 0.95

# ---------------------------------------------------------------------------
# Token budget (issue #4)
# ---------------------------------------------------------------------------
# From the model's own config.json (Goedel-LM/Goedel-Prover-SFT):
#   max_position_embeddings = 4096
#   rope_scaling            = null      <- no context extension of any kind
# and tokenizer_config.json: model_max_length = 4096.
#
# So the TOTAL context (prompt + generation) is 4096 tokens. The previous
# MAX_NEW_TOKENS = 20000 was ~5x the entire context window.
#
# The official eval script runs vLLM with max_model_len=4096 and
# SamplingParams(max_tokens=2048), so 2048 new tokens is the documented budget.
MODEL_MAX_CONTEXT = 4096
MAX_NEW_TOKENS = 2048
# Leave room so a long prompt can never push prompt+generation past the window.
PROMPT_TOKEN_SAFETY_MARGIN = 8

# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------
# Goedel-Prover-SFT is a ~6.9B-parameter Llama-architecture model. In fp16 the
# weights alone are ~13.8 GB, plus ~2.0 GB of KV cache at the full 4096-token
# context. Target device is a single 24 GB L4. Never silently offload to CPU.
VRAM_SAFETY_MARGIN_BYTES = 768 * 1024 * 1024
