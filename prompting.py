"""Render Goedel-Prover-SFT prompts and recover Lean files from completions.

The template itself lives in config.py, copied verbatim from the upstream
eval/step1_inference.py. This module only fills it in.
"""

import re

from config import (
    GOEDEL_LEAN4_HEADER,
    PROMPT_TEMPLATE,
    LEAN4_BLOCK_PATTERN,
)


def build_informal_prefix(informal_step):
    """Wrap the FormalStep CoT step as a Lean doc-comment.

    Upstream Goedel eval records carry `informal_prefix` as a `/-- ... -/`
    doc-comment holding the natural-language description of the statement. Our
    dataset's analogue is `current_step`: the CoT step that `formal_statement`
    formalizes. The template slot is upstream's; what we put in it is our
    dataset mapping.
    """
    text = (informal_step or "").strip()
    if not text:
        return ""
    # A literal "-/" inside the prose would close the comment early.
    text = text.replace("-/", "- /").replace("/-", "/ -")
    return f"/-- {text} -/\n"


def build_prompt(record, header=GOEDEL_LEAN4_HEADER, include_informal=True):
    """Render the prompt for one dataset record.

    `record` is a dict from FormalStepDataset. Ends mid-fence by design.
    """
    formal_statement = record["formal_statement"]
    if not formal_statement.strip():
        raise ValueError("empty formal_statement reached build_prompt()")

    informal_prefix = (
        build_informal_prefix(record.get("informal_step")) if include_informal else ""
    )
    return PROMPT_TEMPLATE.format(
        header=header,
        informal_prefix=informal_prefix,
        formal_statement=formal_statement,
    )


def extract_lean4_block(prompt, completion):
    """Recover the complete Lean file from prompt + completion.

    Mirrors `extrac_code` in upstream eval/step1_inference.py: the prompt opens
    the ```lean4 fence and the model closes it, so the finished file is only
    visible when the two are concatenated. Returns None when the model never
    closed the fence (i.e. the generation was cut off).
    """
    m = re.search(LEAN4_BLOCK_PATTERN, prompt + completion, re.DOTALL)
    return m.group(1) if m else None
