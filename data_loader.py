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
)


class DatasetFieldError(RuntimeError):
    """The dataset does not carry the Lean source we need. Never fall back."""


_DECL = re.compile(r"\b(?:theorem|lemma|example)\b")
_TRAILING_SORRY = re.compile(r"\bsorry\s*\Z")


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


class FormalStepDataset:
    def __init__(self, name=DATASET_NAME, split=DATASET_SPLIT, num_samples=NUM_SAMPLES):
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
        self.dataset = full_ds.select(range(num_samples))
        self.columns = full_ds.column_names

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        """Return the full record. `formal_statement` is the prover input."""
        item = self.dataset[idx]
        return {
            "index": idx,
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
            "state": item.get("state") or "",
        }

    def get_dataloader(self, batch_size=1, shuffle=False):
        return DataLoader(self.dataset, batch_size=batch_size, shuffle=shuffle)
