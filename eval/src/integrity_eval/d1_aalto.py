"""D1: the Aalto 136M Keystrokes dataset (Dhakal et al., CHI 2018), read straight from Keystrokes.zip.

Licence (readme.txt): "free to use this data for non-commercial use in your own research or
projects with attribution to the authors". The data and anything derived from it stay under the
data folder, outside the repository.

Per participant file (tab-separated): PARTICIPANT_ID, TEST_SECTION_ID, SENTENCE, USER_INPUT,
KEYSTROKE_ID, PRESS_TIME, RELEASE_TIME (ms), LETTER, KEYCODE (JavaScript keyCode). LETTER or the
sentences can themselves contain tabs, so press/release are found from the right: the last field
is KEYCODE, and PRESS/RELEASE are the last two consecutive integer fields before it.

A sentence is the keystrokes of one TEST_SECTION_ID, ordered by press time. Keystrokes whose
release is missing or earlier than the press are dropped and counted.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from integrity_ml.keystroke import Keystroke

MEMBER = re.compile(r"(?:^|/)(\d+)_keystrokes\.txt$")
_INT = re.compile(r"^-?\d+$")


@dataclass
class ParseStats:
    lines: int = 0
    malformed: int = 0
    bad_release: int = 0
    keycode_out_of_range: int = 0


@dataclass
class Participant:
    pid: int
    sentences: list[list[Keystroke]] = field(default_factory=list)   # ordered by first press time
    stats: ParseStats = field(default_factory=ParseStats)


def parse_line(line: str) -> tuple[int, int, int, int] | None:
    """(test_section_id, press_ms, release_ms, keycode) or None if malformed."""
    fields = line.rstrip("\r\n").split("\t")
    if len(fields) < 9 or not _INT.match(fields[-1]) or not _INT.match(fields[1]):
        return None
    for i in range(len(fields) - 2, 1, -1):
        if _INT.match(fields[i]) and _INT.match(fields[i - 1]) and len(fields[i - 1]) >= 10:
            return int(fields[1]), int(fields[i - 1]), int(fields[i]), int(fields[-1])
    return None


def parse_participant(pid: int, text: str) -> Participant:
    p = Participant(pid)
    by_section: dict[int, list[Keystroke]] = {}
    for line in text.splitlines()[1:]:          # skip the header
        if not line.strip():
            continue
        p.stats.lines += 1
        parsed = parse_line(line)
        if parsed is None:
            p.stats.malformed += 1
            continue
        section, press, release, keycode = parsed
        if release < press or release == 0:
            p.stats.bad_release += 1
            continue
        if not 0 <= keycode <= 255:
            p.stats.keycode_out_of_range += 1
            keycode = 0
        by_section.setdefault(section, []).append(Keystroke(str(keycode), press * 1000, release * 1000))
    sentences = [sorted(ks, key=lambda k: (k.down_us, k.up_us)) for ks in by_section.values() if ks]
    p.sentences = sorted(sentences, key=lambda ks: ks[0].down_us)
    return p


def participant_members(zip_path: Path) -> list[tuple[int, str]]:
    """(participant id, member name), sorted by participant id."""
    with zipfile.ZipFile(zip_path) as z:
        found = [(int(m.group(1)), n) for n in z.namelist() if (m := MEMBER.search(n))]
    return sorted(found)


def keycode_of(code: str) -> int:
    """Keystroke.code holds the Aalto integer keycode as text."""
    return int(code)
