import re

from config import LEAN_HEADER


def _build_byte_decoder():
    bs = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {chr(c): b for c, b in zip(cs, bs)}


_BYTE_DECODER = _build_byte_decoder()
_ARTIFACTS = ("Ġ", "Ċ", "ĉ")

_DECL = re.compile(
    r"^[ \t]*(?:@\[[^\]]*\]\s*)?"
    r"(?:private\s+|protected\s+|noncomputable\s+)*"
    r"(?:theorem|lemma|example)\b", re.M)
_IMPORT = re.compile(r"^[ \t]*import\s+\w", re.M)
_PAIRS = (("(", ")"), ("[", "]"), ("{", "}"), ("⟨", "⟩"))


def repair_bpe(text):
    if not any(ch in text for ch in _ARTIFACTS):
        return text
    out = bytearray()
    for ch in text:
        b = _BYTE_DECODER.get(ch)
        if b is None:
            out.extend(ch.encode("utf-8"))
        else:
            out.append(b)
    return out.decode("utf-8", errors="replace")


def _strip_comments(code):
    code = re.sub(r"/-.*?-/", "", code, flags=re.S)
    code = re.sub(r"[ \t]*--[^\n]*", "", code)
    return "\n".join(l.rstrip() for l in code.split("\n") if l.strip())


def _looks_truncated(code, saw_fence):
    if saw_fence:
        return False
    if code.count("/-") > code.count("-/"):
        return True
    stripped = _strip_comments(code)
    for op, cl in _PAIRS:
        if stripped.count(op) != stripped.count(cl):
            return True
    last = stripped.rstrip().split("\n")[-1].strip() if stripped.strip() else ""
    return bool(re.search(r"(<;>|:=|,|\bby\b|\bwith\b|\bfun\b|=>)$", last))


def parse_output(raw, prompt=None, strip_comments=False, add_header=True):
    text = repair_bpe(raw)

    if prompt:
        p = repair_bpe(prompt).strip()
        i = text.find(p)
        if i != -1:
            text = text[i + len(p):]

    m = re.search(r"```(?:lean4?|Lean4?)?[ \t]*\r?\n", text)
    body = text[m.end():] if m else text

    start = _IMPORT.search(body) or _DECL.search(body)
    code = body[start.start():] if start else body.lstrip("-/` \n")

    fence = re.search(r"\n?[ \t]*```", code)
    saw_fence = fence is not None
    if saw_fence:
        code = code[:fence.start()]
    code = code.rstrip()

    if code.count("/-") > code.count("-/"):
        code = code[:code.rfind("/-")].rstrip()

    truncated = _looks_truncated(code, saw_fence)
    if strip_comments:
        code = _strip_comments(code)
    if add_header:
        code = re.sub(
            r"^import Mathlib.*?(?=\ntheorem|\nlemma|\nexample)",
            "", code, flags=re.S
        )
        code = LEAN_HEADER + "\n" + code.lstrip()

    name = re.search(r"\b(?:theorem|lemma)\s+([^\s:({\[]+)", code)
    return {
        "text": text,
        "code": code,
        "theorem_name": name.group(1) if name else None,
        "found_declaration": bool(start),
        "truncated": truncated,
        "has_sorry": bool(re.search(r"\bsorry\b", code)),
    }
