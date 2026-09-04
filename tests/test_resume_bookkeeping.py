"""Gate 3: does --resume actually recover from a kill, without dropping or
duplicating records?

`"resumed": true` in a committed run_meta means a resume ran once. It does not
mean recovery is correct. A 36-hour on-demand run still risks a crash, an OOM,
or a manual stop, and the recovery path has never been exercised by an actual
interruption. Four gate-style defects in this repo were caught by making
something fail on purpose; this file does that for resume.

Everything here uses CRAFTED FILES and needs no GPU, no model and no Lean. It
tests the bookkeeping half -- key identity, partial-line recovery, dedup, and
whether the file resume leaves behind is still readable downstream -- which is
where a drop or a duplicate would actually live.

Run: python -m pytest tests/test_resume_bookkeeping.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate import JsonlWriter, load_done_keys, traj_key  # noqa: E402


def rec(sample, traj, temp=0.0, **extra):
    r = {"sample_index": sample, "trajectory_index": traj, "temperature": temp,
         "full_code": "theorem t : True := by trivial", "seed": 20260902}
    r.update(extra)
    return r


def write_lines(path, records, torn_tail=None):
    """Write complete records, optionally followed by an unterminated fragment."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
        if torn_tail is not None:
            f.write(torn_tail)          # deliberately NO trailing newline
    return path


# --------------------------------------------------------------------------- #
# 1. Key identity -- the thing dedup rests on
# --------------------------------------------------------------------------- #
def test_traj_key_is_stable_across_input_types():
    assert traj_key(3, 0.0, 1) == traj_key("3", "0.0", "1") == traj_key(3.0, 0, 1.0)


def test_traj_key_separates_temperature_arms():
    assert traj_key(3, 0.0, 1) != traj_key(3, 0.2, 1)


def test_traj_key_separates_sample_and_trajectory():
    assert traj_key(1, 0.0, 2) != traj_key(2, 0.0, 1)


def test_traj_key_tolerates_float_noise():
    # 0.2 written by one process and re-read by another must collide, or resume
    # would regenerate the entire second temperature arm.
    assert traj_key(5, 0.2, 0) == traj_key(5, 0.20000000000000001, 0)


# --------------------------------------------------------------------------- #
# 2. load_done_keys -- what counts as already done
# --------------------------------------------------------------------------- #
def test_clean_file_all_keys_found(tmp_path):
    p = write_lines(tmp_path / "t.jsonl", [rec(i, 0) for i in range(5)])
    assert len(load_done_keys(str(p))) == 5


def test_missing_file_is_empty_not_an_error(tmp_path):
    assert load_done_keys(str(tmp_path / "nope.jsonl")) == set()


def test_blank_lines_ignored(tmp_path):
    p = tmp_path / "t.jsonl"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec(0, 0)) + "\n\n   \n" + json.dumps(rec(1, 0)) + "\n")
    assert len(load_done_keys(str(p))) == 2


def test_torn_tail_is_not_counted_done(tmp_path):
    """A half-written record must be REGENERATED, not silently accepted."""
    p = write_lines(tmp_path / "t.jsonl", [rec(i, 0) for i in range(3)],
                    torn_tail='{"sample_index": 3, "trajectory_ind')
    done = load_done_keys(str(p))
    assert len(done) == 3
    assert traj_key(3, 0.0, 0) not in done


def test_complete_json_without_newline_IS_counted_done(tmp_path):
    """Killed between write() and the newline: the record is intact, so it must
    NOT be regenerated -- that would duplicate it."""
    p = write_lines(tmp_path / "t.jsonl", [rec(i, 0) for i in range(3)],
                    torn_tail=json.dumps(rec(3, 0)))
    done = load_done_keys(str(p))
    assert len(done) == 4
    assert traj_key(3, 0.0, 0) in done


def test_record_missing_key_fields_is_ignored(tmp_path):
    p = tmp_path / "t.jsonl"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec(0, 0)) + "\n")
        f.write(json.dumps({"full_code": "x"}) + "\n")       # no key fields
    assert len(load_done_keys(str(p))) == 1


# --------------------------------------------------------------------------- #
# 3. _repair_torn_tail -- the append-safety half
# --------------------------------------------------------------------------- #
def test_repair_terminates_a_torn_line(tmp_path):
    p = write_lines(tmp_path / "t.jsonl", [rec(0, 0)],
                    torn_tail='{"sample_index": 1, "traj')
    JsonlWriter._repair_torn_tail(str(p))
    assert open(p, "rb").read().endswith(b"\n")


def test_repair_is_a_noop_on_a_clean_file(tmp_path):
    p = write_lines(tmp_path / "t.jsonl", [rec(0, 0)])
    before = open(p, "rb").read()
    JsonlWriter._repair_torn_tail(str(p))
    assert open(p, "rb").read() == before


def test_repair_is_a_noop_on_empty_and_missing(tmp_path):
    empty = tmp_path / "e.jsonl"
    empty.write_bytes(b"")
    JsonlWriter._repair_torn_tail(str(empty))
    assert empty.read_bytes() == b""
    JsonlWriter._repair_torn_tail(str(tmp_path / "absent.jsonl"))   # must not raise


def test_repair_then_append_does_not_glue_records(tmp_path):
    """Without the repair, the next record is glued onto the fragment and BOTH
    lines become unparseable -- an interrupt would cost two trajectories."""
    p = write_lines(tmp_path / "t.jsonl", [rec(0, 0)],
                    torn_tail='{"sample_index": 1, "traj')
    w = JsonlWriter(str(p))
    w.write(rec(2, 0))
    w.close() if hasattr(w, "close") else None
    lines = [l for l in open(p, encoding="utf-8").read().splitlines() if l.strip()]
    good = [l for l in lines if _parses(l)]
    assert len(good) == 2, lines          # rec 0 and rec 2 both readable
    assert any(json.loads(l)["sample_index"] == 2 for l in good)


def _parses(line):
    try:
        json.loads(line)
        return True
    except json.JSONDecodeError:
        return False


# --------------------------------------------------------------------------- #
# 4. End-to-end: kill at a random point, resume, check the ledger
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cut_frac", [0.13, 0.37, 0.5, 0.76, 0.94])
def test_kill_at_arbitrary_byte_then_resume_loses_nothing_and_duplicates_nothing(
        tmp_path, cut_frac):
    """Simulates a kill at an arbitrary byte offset, which is what an interrupted
    process actually leaves -- not a tidy record boundary."""
    WANT = [(s, 0) for s in range(20)]
    full = tmp_path / "full.jsonl"
    write_lines(full, [rec(s, t) for s, t in WANT])
    blob = open(full, "rb").read()

    part = tmp_path / "traces.jsonl"
    cut = int(len(blob) * cut_frac)
    part.write_bytes(blob[:cut])                       # the interrupted file

    done = load_done_keys(str(part))                   # what resume believes
    writer = JsonlWriter(str(part))                    # repairs the torn tail
    regenerated = []
    for s, t in WANT:
        if traj_key(s, 0.0, t) in done:
            continue
        writer.write(rec(s, t))
        regenerated.append((s, t))

    keys = []
    for line in open(part, encoding="utf-8"):
        if line.strip() and _parses(line):
            r = json.loads(line)
            keys.append(traj_key(r["sample_index"], r["temperature"],
                                 r["trajectory_index"]))

    expected = {traj_key(s, 0.0, t) for s, t in WANT}
    assert set(keys) == expected, "resume DROPPED trajectories"
    assert len(keys) == len(expected), f"resume DUPLICATED: {len(keys)} rows"
    assert len(regenerated) == len(WANT) - len(done)


def test_resume_of_a_complete_file_regenerates_nothing(tmp_path):
    WANT = [(s, 0) for s in range(10)]
    p = write_lines(tmp_path / "t.jsonl", [rec(s, t) for s, t in WANT])
    done = load_done_keys(str(p))
    assert all(traj_key(s, 0.0, t) in done for s, t in WANT)
    assert len(done) == len(WANT)


def test_two_temperature_arms_do_not_collide(tmp_path):
    """T=0.0 and T=0.2 share sample/trajectory indices; only the key separates
    them. A collision would silently skip the whole second arm."""
    p = write_lines(tmp_path / "t.jsonl", [rec(s, 0, temp=0.0) for s in range(5)])
    done = load_done_keys(str(p))
    assert not any(traj_key(s, 0.2, 0) in done for s in range(5))


# --------------------------------------------------------------------------- #
# 5. THE CROSS-COMPONENT BUG: is the file resume leaves behind still readable?
# --------------------------------------------------------------------------- #
# Resume deliberately KEEPS the unparseable fragment: _repair_torn_tail only
# terminates it with a newline, and load_done_keys skips it. So after any
# interruption the trace file permanently contains one garbage line.
#
# verify_traces.load_done() guards json.loads with try/except.
# verify_traces.main() -- the path that reads the TRACES -- did not.
def _read_traces_like_verify_traces_main(path):
    """Mirror of the read loop in verify_traces.main()."""
    from verify_traces import _load_trace_records
    return _load_trace_records(path)


def test_downstream_verifier_can_read_a_resumed_trace_file(tmp_path):
    """The file a real interruption leaves must still be verifiable.

    Before the fix this raised json.JSONDecodeError, so a spot interruption 30
    hours into a run produced traces that the verifier refused to read at all.
    """
    p = write_lines(tmp_path / "traces.jsonl", [rec(i, 0) for i in range(3)],
                    torn_tail='{"sample_index": 3, "trajectory_ind')
    JsonlWriter(str(p)).write(rec(4, 0))          # repair + append, as resume does

    recs = _read_traces_like_verify_traces_main(str(p))
    got = sorted(r["sample_index"] for r in recs)
    assert got == [0, 1, 2, 4], got                # the fragment is skipped, not fatal


def test_downstream_reader_skips_only_the_garbage(tmp_path):
    p = write_lines(tmp_path / "traces.jsonl", [rec(i, 0) for i in range(6)],
                    torn_tail='{"sample_ind')
    JsonlWriter(str(p))
    recs = _read_traces_like_verify_traces_main(str(p))
    assert len(recs) == 6
