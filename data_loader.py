import re

from datasets import load_dataset
from torch.utils.data import DataLoader

from config import (
    DATASET_NAME,
    DATASET_SPLIT,
    NUM_SAMPLES,
    FORMAL_STATEMENT_FIELD,
    INFORMAL_STEP_FIELD,
    REFERENCE_PROOF_FIELD,
    REQUIRED_DATASET_FIELDS,
    SAMPLE_STRATEGY,
    PROBLEM_STRIDE,
    STEP_SELECTION,
)


class DatasetFieldError(RuntimeError):
    """The dataset does not carry the Lean source we need. Never fall back."""


_DECL = re.compile(r"\b(?:theorem|lemma|example)\b")
_TRAILING_SORRY = re.compile(r"\bsorry\s*\Z")


def _counts(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def normalize_formal_statement(statement, index=None):
    """Turn a FormalStep `formal_statement` into a Goedel-Prover prompt suffix.

    FormalStep ships statements terminated with ``:= by sorry``. The Goedel eval
    data (datasets/*.jsonl in the upstream repo) terminates them with ``:= by``
    and a newline, leaving the proof body for the model to write. Handing the
    model a statement that already ends in ``sorry`` gives it a syntactically
    complete file, so it just closes the fence and proves nothing.
    """
    where = "" if index is None else f" (sample {index})"

    if statement is None:
        raise DatasetFieldError(
            f"{FORMAL_STATEMENT_FIELD} is None{where}. Refusing to substitute "
            "natural-language prose for a Lean statement."
        )
    text = statement.strip()
    if not text:
        raise DatasetFieldError(
            f"{FORMAL_STATEMENT_FIELD} is empty{where}. Refusing to substitute "
            "natural-language prose for a Lean statement."
        )
    if not _DECL.search(text):
        raise DatasetFieldError(
            f"{FORMAL_STATEMENT_FIELD}{where} contains no theorem/lemma/example "
            f"declaration, so it is not a Lean 4 statement. Got: {text[:200]!r}"
        )

    text = _TRAILING_SORRY.sub("", text).rstrip()
    if text.endswith(":="):
        text = text + " by"
    elif not re.search(r"\bby\Z", text):
        text = text + " := by"
    return text + "\n"


def select_rows(problem_ids, num_samples, strategy, stride, step_selection):
    """Choose which dataset rows to sample. Returns (row_indices, metadata).

    FormalStep is ordered by problem, one row per CoT step, ~62 steps per
    problem. `head` — the original behaviour — therefore takes `num_samples`
    steps of a SINGLE problem: the first 50 rows are all
    math_train_counting_and_probability_408. Every generated trace then shares
    one problem, one ground_truth ("101"), and one topic, which is not a sample
    of the dataset in any useful sense.

    `distinct_problems` takes one step from each of `num_samples` DIFFERENT
    problems, striding across the ordered problem list so the selection spans
    the whole split rather than a contiguous block at its head. The stride is
    deterministic — no RNG — so a run is reproducible from
    (strategy, stride, step_selection, num_samples) alone.

    Note: the train split holds 500 problems and is entirely "Counting &
    Probability", so there is no topic axis to stratify over. Level is spread
    by construction, not by design; the realised distribution is recorded in the
    run metadata.
    """
    if strategy == "head":
        if num_samples > len(problem_ids):
            raise DatasetFieldError(
                f"Requested {num_samples} samples but the split has "
                f"{len(problem_ids)} rows."
            )
        rows = list(range(num_samples))
        return rows, {
            "strategy": "head",
            "distinct_problems_in_selection": len(set(problem_ids[i] for i in rows)),
        }

    if strategy != "distinct_problems":
        raise DatasetFieldError(
            f"Unknown sample strategy {strategy!r}; expected 'distinct_problems' "
            "or 'head'."
        )

    if step_selection not in ("first", "median"):
        raise DatasetFieldError(
            f"Unknown step selection {step_selection!r}; expected 'first' or 'median'."
        )
    if stride < 1:
        raise DatasetFieldError(f"stride must be >= 1, got {stride}.")

    rows_by_problem = {}
    for i, pid in enumerate(problem_ids):
        rows_by_problem.setdefault(pid, []).append(i)
    ordered_problems = list(rows_by_problem)  # insertion order == dataset order

    picked_problems = ordered_problems[::stride][:num_samples]
    if len(picked_problems) < num_samples:
        raise DatasetFieldError(
            f"Requested {num_samples} distinct problems at stride {stride}, but "
            f"only {len(picked_problems)} are reachable "
            f"({len(ordered_problems)} problems in the split). Lower the stride "
            "or the sample count — never silently return fewer samples."
        )

    rows = []
    for pid in picked_problems:
        steps = rows_by_problem[pid]
        rows.append(steps[0] if step_selection == "first" else steps[len(steps) // 2])

    return rows, {
        "strategy": "distinct_problems",
        "stride": stride,
        "step_selection": step_selection,
        "problems_in_split": len(ordered_problems),
        "distinct_problems_in_selection": len(set(picked_problems)),
    }


class FormalStepDataset:
    def __init__(
        self,
        name=DATASET_NAME,
        split=DATASET_SPLIT,
        num_samples=NUM_SAMPLES,
        strategy=SAMPLE_STRATEGY,
        stride=PROBLEM_STRIDE,
        step_selection=STEP_SELECTION,
    ):
        full_ds = load_dataset(name, split=split)

        missing = [f for f in REQUIRED_DATASET_FIELDS if f not in full_ds.column_names]
        if missing:
            raise DatasetFieldError(
                f"Dataset {name}:{split} is missing required field(s) {missing}. "
                f"Available columns: {full_ds.column_names}. "
                "This pipeline feeds Lean 4 source to a Lean 4 prover; there is "
                "no natural-language fallback."
            )

        if num_samples > len(full_ds):
            raise DatasetFieldError(
                f"Requested {num_samples} samples but {name}:{split} has "
                f"{len(full_ds)}."
            )

        self.row_indices, self.selection = select_rows(
            full_ds["problem_unique_id"], num_samples, strategy, stride, step_selection
        )
        self.dataset = full_ds.select(self.row_indices)
        self.columns = full_ds.column_names
        self.name = name
        self.split = split
        # datasets' content hash of the loaded split. Private attribute, so it
        # is recorded when available and omitted rather than faked when not.
        self.fingerprint = getattr(full_ds, "_fingerprint", None)
        self.num_rows_in_split = len(full_ds)

        # Anything downstream that reports on this run needs the realised
        # selection, not the requested one.
        self.selection = dict(
            self.selection,
            num_samples=len(self.row_indices),
            dataset_rows=list(self.row_indices),
            problem_unique_ids=list(self.dataset["problem_unique_id"]),
            levels=_counts(self.dataset["level"]),
            types=_counts(self.dataset["type"]),
            states=_counts(self.dataset["state"]),
        )

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        """Return the full record. `formal_statement` is the prover input."""
        item = self.dataset[idx]
        return {
            "index": idx,
            # Row in the underlying split, so any trace can be traced back to
            # the exact dataset record it came from.
            "dataset_row": self.row_indices[idx],
            "formal_statement": normalize_formal_statement(
                item.get(FORMAL_STATEMENT_FIELD), index=idx
            ),
            "formal_statement_raw": item.get(FORMAL_STATEMENT_FIELD),
            "informal_step": item.get(INFORMAL_STEP_FIELD) or "",
            "reference_proof": item.get(REFERENCE_PROOF_FIELD) or "",
            # Metadata only. `problem` is NL prose and must never reach the model
            # as the thing to prove (issue #2); `ground_truth` is a final numeric
            # answer, not a proof.
            "problem": item.get("problem") or "",
            "ground_truth": item.get("ground_truth") or "",
            "problem_unique_id": item.get("problem_unique_id") or "",
            # The dataset's own claim about whether this step's statement was
            # proved. Carried into every trace record so provability does not
            # have to be re-derived from `reference_proof` downstream.
            "state": item.get("state") or "",
            "level": item.get("level") or "",
            "type": item.get("type") or "",
        }

    def get_dataloader(self, batch_size=1, shuffle=False):
        return DataLoader(self.dataset, batch_size=batch_size, shuffle=shuffle)
