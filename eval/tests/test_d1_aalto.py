"""D1 parser on hand-written SYNTHETIC lines in the Aalto format (no real data in the repo)."""

from __future__ import annotations

from integrity_eval.d1_aalto import parse_line, parse_participant

HEADER = "PARTICIPANT_ID\tTEST_SECTION_ID\tSENTENCE\tUSER_INPUT\tKEYSTROKE_ID\tPRESS_TIME\tRELEASE_TIME\tLETTER\tKEYCODE"


def row(section: int, press: int, release: int, letter: str, keycode: int, sentence: str = "Hi there") -> str:
    return f"1\t{section}\t{sentence}\t{sentence}\t{press % 9999}\t{press}\t{release}\t{letter}\t{keycode}"


def test_parse_line_plain_and_with_tabs() -> None:
    assert parse_line(row(7, 1473275372512, 1473275372663, "a", 65)) == (7, 1473275372512, 1473275372663, 65)
    # a Tab key: LETTER is itself a tab character, which adds a field
    assert parse_line(row(7, 1473275372512, 1473275372600, "\t", 9)) == (7, 1473275372512, 1473275372600, 9)
    # a tab inside the sentence
    assert parse_line(row(7, 1473275372512, 1473275372600, "b", 66, sentence="a\tb")) == (7, 1473275372512, 1473275372600, 66)


def test_parse_line_rejects_malformed() -> None:
    assert parse_line("1\t2\t3") is None
    assert parse_line(row(7, 1473275372512, 1473275372663, "a", 65).rsplit("\t", 1)[0] + "\tx") is None


def test_participant_sentences_ordering_and_bad_rows() -> None:
    t0 = 1473275372000
    text = "\n".join([
        HEADER,
        row(20, t0 + 5000, t0 + 5100, "x", 88),     # second sentence (later)
        row(10, t0 + 200, t0 + 300, "b", 66),
        row(10, t0 + 100, t0 + 180, "a", 65),      # out of order within the sentence
        row(10, t0 + 400, t0 + 350, "c", 67),      # release before press: dropped
        row(20, t0 + 5200, t0 + 5300, "?", 999),   # keycode out of range: kept as 0
        "garbage line",
    ])
    p = parse_participant(1, text)
    assert [len(s) for s in p.sentences] == [2, 2]
    assert [k.code for k in p.sentences[0]] == ["65", "66"]
    assert p.sentences[1][1].code == "0"
    assert (p.stats.lines, p.stats.malformed, p.stats.bad_release, p.stats.keycode_out_of_range) == (6, 1, 1, 1)
    assert p.sentences[0][0].down_us == (t0 + 100) * 1000
