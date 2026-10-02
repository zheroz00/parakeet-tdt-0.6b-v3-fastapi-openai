# Transcript Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every transcript the server returns has custom-vocabulary fixes applied and spoken numbers written as digits, without changing any client.

**Architecture:** A new pure-Python package `text_cleanup/` (stdlib only) exposes `clean()` and `clean_segments()`. `app.py` calls `clean_segments()` once after transcription, before output formatting. The vocabulary lives in `config/vocabulary.txt`, bind-mounted read-only into the container and re-read when it changes.

**Tech Stack:** Python 3.10 (Docker image), Flask + waitress (existing), pytest (dev only, run in a `python:3.10-slim` container because the host has no pytest).

**Spec:** `docs/superpowers/specs/2026-10-02-transcript-cleanup-design.md`

## Global Constraints

- Branch: `feature/transcript-cleanup` (cut from `my-setup`). Never commit to `main`; never push to `origin` (that is the upstream author's repo). The backup remote is `fork`.
- No new runtime dependencies. `text_cleanup/` uses the standard library only. `pytest>=8.0` goes in `requirements-dev.txt`, not `requirements.txt`.
- Run tests with `scripts/test.sh` (created in Task 1). Extra args pass through to pytest.
- Unit tests use synthetic sentences only. Real transcripts are private dictation and must never be committed (the fork is public). The archive used for review lives outside the repo.
- `config/vocabulary.txt` is personal and gitignored. Only `config/vocabulary.example.txt` (placeholder entries) is committed.
- Cleanup must never lose a transcript: `clean()` catches every exception and returns the raw text.
- Log only changed spans (`heard -> written`), never a full transcript.
- No em dashes or en dashes in any committed prose, comments or commit messages; plain hyphens are fine.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NauotMQJMMpsaYGvCm16v2
  ```

## Review Focus

1. **Number words in ordinary prose** ("zero in on", "test one two" → "test 12", "cloud nine"): expected to stay readable. Pinned by `test_leaves_alone` (Task 1) and by the owner reviewing the full archive run (Task 4 gate) before deploy.
2. **Mixed case and odd spacing** ("TWENTY FOUR", "four  point\ntwo"): expected to convert like normal text. Pinned in Task 1's `test_converts` cases.
3. **Vocabulary file edited or broken while the server runs** (half-written file, bad UTF-8, deleted file): expected to keep serving with the last good rules and log once. Pinned by `test_unreadable_file_keeps_previous_rules`, `test_missing_file_means_no_rules`, `test_reloads_when_file_changes` (Task 2).
4. **A bug in a rule** raising mid-request: expected to return the raw transcript, not a 500. Pinned by `test_never_raises` (Task 3).
5. **Client asks for raw text** (`cleanup=false`) or cleanup disabled server-wide (`TRANSCRIPT_CLEANUP=false`): expected raw model output. Pinned by the end-to-end checks in Task 7 (the request handler is not unit-testable because `app.py` loads the model at import).

## File Structure

| Path | Responsibility |
|---|---|
| `text_cleanup/__init__.py` | `clean()`, `clean_segments()`, `CleanResult`; error safety |
| `text_cleanup/numbers.py` | spoken numbers → digits, fraction repair |
| `text_cleanup/vocabulary.py` | vocabulary parsing, hot reload, replacement |
| `tests/test_numbers.py`, `tests/test_vocabulary.py`, `tests/test_clean.py` | unit tests |
| `scripts/test.sh` | run pytest in Python 3.10 container |
| `scripts/review_cleanup.py` | dry run over a private transcript archive |
| `config/vocabulary.example.txt` | committed template |
| `config/vocabulary.txt` | personal word list (gitignored) |
| `requirements-dev.txt` | pytest |
| `app.py`, `Dockerfile.cpu`, `Dockerfile.gpu`, `docker-compose.yml`, `.gitignore`, `DOCKER.md`, `CLAUDE.md` | wiring and docs |

---

### Task 1: Number rules

**Files:**
- Create: `text_cleanup/__init__.py` (one-line docstring stub; Task 3 fills it in)
- Create: `text_cleanup/numbers.py`
- Create: `tests/test_numbers.py`
- Create: `requirements-dev.txt`
- Create: `scripts/test.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: `text_cleanup.numbers.convert_numbers(text: str) -> tuple[str, list[tuple[str, str]]]` returning `(new_text, [(spoken_span, written)])` in text order (word conversions first, then digit-fraction repairs). Never mutates input.

- [ ] **Step 1: Create the package stub, dev requirements and test runner**

`text_cleanup/__init__.py`:
```python
"""Post-transcription cleanup: custom vocabulary, then spoken numbers to digits."""
```

`requirements-dev.txt`:
```
pytest>=8.0
```

`scripts/test.sh` (then `chmod +x scripts/test.sh`):
```bash
#!/usr/bin/env bash
# Run the test suite in the same Python as the Docker image (3.10).
# Extra arguments go to pytest, e.g. scripts/test.sh tests/test_numbers.py -k fraction
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker run --rm -u "$(id -u)" -e HOME=/tmp -v "$PWD":/src -w /src python:3.10-slim \
  sh -c 'pip install -q --user -r requirements-dev.txt 2>/dev/null && python -m pytest -q -p no:cacheprovider "$@"' -- "$@"
```

- [ ] **Step 2: Write the failing tests**

`tests/test_numbers.py`:
```python
import pytest

from text_cleanup.numbers import convert_numbers


def converted(text):
    return convert_numbers(text)[0]


@pytest.mark.parametrize("spoken, written", [
    # decimals
    ("zero point one five millimeters", "0.15 millimeters"),
    ("four point two volts", "4.2 volts"),
    ("zero point one zero millimeters", "0.10 millimeters"),
    ("thirty eight point three tests", "38.3 tests"),
    ("three point twenty five", "3.25"),
    # plain numbers, units kept as spoken
    ("twenty four volts and thirty seven percent", "24 volts and 37 percent"),
    ("two seconds, two options", "2 seconds, 2 options"),
    ("wait thirty seconds", "wait 30 seconds"),
    ("one hundred ninety seven millimeters", "197 millimeters"),
    ("one hundred percent", "100 percent"),
    ("two thousand twenty six", "2026"),
    ("thirty-two bits", "32 bits"),
    ("Windows ten", "Windows 10"),
    ("Two options here.", "2 options here."),
    ("TWENTY FOUR volts", "24 volts"),
    ("four  point\ntwo", "4.2"),
    # numbers spoken in chunks
    ("a four seventy cap", "a 470 cap"),
    ("an eighteen six fifty cell", "an 18650 cell"),
    ("fifty six hundred", "5600"),
    ("one ninety seven", "197"),
    ("five six seven eight", "5678"),
    ("thirty-six zero eight", "3608"),
    # fractions
    ("one eighth of the way", "1/8 of the way"),
    ("a three sixteenth inch bit", "a 3/16 inch bit"),
    ("a one thirty second inch bit", "a 1/32 inch bit"),
    ("five thirty seconds", "5/32"),
    ("an eighth inch", "1/8 inch"),
    ("two thirds of it", "2/3 of it"),
    ("seven eighths", "7/8"),
    ("fifteen sixteenths", "15/16"),
    # IPv4
    ("one ninety two dot one sixty eight dot one dot twenty", "192.168.1.20"),
    ("ten dot ten dot ten dot one fifty eight", "10.10.10.158"),
    ("zero dot zero dot zero dot zero", "0.0.0.0"),
    ("ten dot zero dot five", "10.0.5"),
])
def test_converts(spoken, written):
    assert converted(spoken) == written


@pytest.mark.parametrize("text", [
    "one of the things",
    "One more thing.",
    "the first one is better",
    "one second please",
    "at that point two things",
    "point being",
    "point two five zero spring",
    "the three dot menu",
    "the red dot in the corner",
    "ten dot five",
    "three hundred dot three hundred dot one dot one",
    "September twenty ninth",
    "on the twenty third",
    "twenty eighth",
    "a third option",
    "a half hour",
    "a hundred times",
    "one one-off",
    "five-volt rail",
    "Non-zero status",
    "someone, everyone, none, often",
])
def test_leaves_alone(text):
    assert converted(text) == text


@pytest.mark.parametrize("written, repaired", [
    ("a 132 inch bit", "a 1/32 inch bit"),
    ("a 1.32nd inch bit", "a 1/32 inch bit"),
    ("use a 1 32nd bit", "use a 1/32 bit"),
    ("3 16ths deep", "3/16 deep"),
    ("a 316 inch bit", "a 3/16 inch bit"),
    ("5 8ths", "5/8"),
    ("1564 inch", "15/64 inch"),
])
def test_repairs_fractions_the_model_wrote_in_digits(written, repaired):
    assert converted(written) == repaired


@pytest.mark.parametrize("text", [
    "an 18 inch board",
    "a 65 inch TV",
    "132 inches long",
    "a 232 inch run",
    "the 32nd time",
    "2.4 network",
])
def test_leaves_real_digit_numbers_alone(text):
    assert converted(text) == text


def test_reports_each_change():
    text, changes = convert_numbers("Set it to four point two volts, then two more.")
    assert text == "Set it to 4.2 volts, then 2 more."
    assert changes == [("four point two", "4.2"), ("two", "2")]


def test_punctuation_breaks_a_number():
    assert converted("one, two, three") == "one, 2, 3"


def test_empty_and_numberless_text():
    assert convert_numbers("") == ("", [])
    assert convert_numbers("Nothing to see here.") == ("Nothing to see here.", [])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `scripts/test.sh tests/test_numbers.py`
Expected: collection error, `ModuleNotFoundError: No module named 'text_cleanup.numbers'`.

- [ ] **Step 4: Implement the number rules**

`text_cleanup/numbers.py`:
```python
"""Spoken numbers to digits for dictated text.

Digits for every number except a lone "one". Handles decimals ("four point
two" -> 4.2), fractions ("one thirty second" -> 1/32), numbers spoken in
chunks ("four seventy" -> 470) and dotted IPv4 addresses. Unit words are left
as spoken. Full rules: docs/superpowers/specs/2026-10-02-transcript-cleanup-design.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
SCALES = {"hundred", "thousand"}
STARTERS = {**UNITS, **TEENS, **TENS}  # words that can begin a number
NUMBER_WORDS = set(STARTERS) | SCALES

# "<numerator> <denominator>" -> fraction, e.g. "three sixteenths" -> 3/16.
DENOMINATORS = {
    "half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4,
    "eighth": 8, "eighths": 8, "sixteenth": 16, "sixteenths": 16,
}
# "<numerator> thirty second(s)" -> n/32, "<numerator> sixty fourth(s)" -> n/64.
COMPOUND_DENOMINATORS = {
    ("thirty", "second"): 32, ("thirty", "seconds"): 32,
    ("sixty", "fourth"): 64, ("sixty", "fourths"): 64,
}
# "a"/"an" count as 1 only before these, so "a third option" and
# "a half hour" stay as words while "an eighth inch" becomes 1/8.
ARTICLE_DENOMINATORS = {"eighth": 8, "sixteenth": 16}

ORDINALS = {
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth",
    "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth",
    "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth", "seventieth",
    "eightieth", "ninetieth", "hundredth", "thousandth",
}

_WORD = re.compile(r"[A-Za-z]+")

Change = Tuple[str, str]


@dataclass(frozen=True)
class _Tok:
    low: str
    start: int
    end: int


def _joined(text: str, a: _Tok, b: _Tok) -> bool:
    """True when two words are separated only by whitespace or one hyphen."""
    gap = text[a.end:b.start]
    return gap == "-" or (gap != "" and gap.strip() == "")


def _parse_groups(words: List[str]) -> Tuple[List[int], int]:
    """Split number words into spoken groups.

    "eighteen six fifty" -> [18, 6, 50]; "one hundred ninety seven" -> [197].
    Returns (groups, words_used); parsing stops at a scale word that cannot
    apply ("hundred hundred"), leaving the rest for the caller.
    """
    groups: List[int] = []
    cur: Optional[int] = None
    last = ""  # kind of the last word added to cur
    for used, w in enumerate(words):
        if w in STARTERS:
            v = STARTERS[w]
            kind = "unit" if w in UNITS else "teen" if w in TEENS else "tens"
            if cur is not None and _continues(cur, last, kind, v):
                cur += v
            else:
                if cur is not None:
                    groups.append(cur)
                cur = v
            last = kind
        elif w == "hundred":
            part = cur % 1000 if cur is not None else 0
            if cur is None or last not in ("unit", "teen", "tens") or not 1 <= part <= 99:
                return _close(groups, cur), used
            cur = cur - part + part * 100
            last = "hundred"
        elif w == "thousand":
            if cur is None or last == "thousand" or not 1 <= cur <= 999:
                return _close(groups, cur), used
            cur *= 1000
            last = "thousand"
        else:
            return _close(groups, cur), used
    return _close(groups, cur), len(words)


def _continues(cur: int, last: str, kind: str, value: int) -> bool:
    if last == "tens":
        return kind == "unit" and value != 0  # "twenty six"
    if last in ("hundred", "thousand"):
        if kind == "unit":
            return value != 0
        return cur % 100 == 0  # "hundred ninety", "thousand twenty"
    return False


def _close(groups: List[int], cur: Optional[int]) -> List[int]:
    return groups + [cur] if cur is not None else groups


def _join(groups: List[int]) -> str:
    """Spoken chunks become one number ("four seventy" -> 470) when every
    chunk after the first is under 100; otherwise keep them separate."""
    if len(groups) > 1 and all(g < 100 for g in groups[1:]):
        return "".join(str(g) for g in groups)
    return " ".join(str(g) for g in groups)


def _whole(groups: List[int]) -> Optional[int]:
    joined = _join(groups)
    return int(joined) if " " not in joined else None


def _collect(text: str, toks: List[_Tok], i: int, allowed) -> List[str]:
    """Number words starting at toks[i], joined by whitespace/hyphens.

    A word hyphenated to a non-number ("one-off", "five-volt") ends the run
    and is not part of it.
    """
    words = []
    j = i
    while j < len(toks) and toks[j].low in allowed and (j == i or _joined(text, toks[j - 1], toks[j])):
        if _hyphen_compound(text, toks, j, allowed):
            break
        words.append(toks[j].low)
        j += 1
    return words


def _hyphen_compound(text: str, toks: List[_Tok], j: int, allowed) -> bool:
    return (
        j + 1 < len(toks)
        and text[toks[j].end:toks[j + 1].start] == "-"
        and toks[j + 1].low not in allowed
    )


def _next(text: str, toks: List[_Tok], j: int, prev: int) -> Optional[str]:
    """Lowercased word at toks[j] if it directly follows toks[prev]."""
    if j < len(toks) and _joined(text, toks[prev], toks[j]):
        return toks[j].low
    return None


def _match_at(text: str, toks: List[_Tok], i: int) -> Optional[Tuple[int, Optional[str]]]:
    """Try to read a number starting at toks[i].

    Returns None if no number starts here, else (tokens consumed, replacement),
    where replacement None means "leave these words as spoken".
    """
    first = toks[i].low

    if first in ("a", "an"):
        nxt = _next(text, toks, i + 1, i)
        if nxt in ARTICLE_DENOMINATORS:
            return 2, f"1/{ARTICLE_DENOMINATORS[nxt]}"
        after = _next(text, toks, i + 2, i + 1) if nxt else None
        if (nxt, after) in COMPOUND_DENOMINATORS:
            return 3, f"1/{COMPOUND_DENOMINATORS[(nxt, after)]}"
        return None

    if first not in STARTERS:
        return None

    # Hyphenated onto a preceding word ("non-zero"): part of that word.
    if i > 0 and text[toks[i - 1].end:toks[i].start] == "-" and toks[i - 1].low not in NUMBER_WORDS:
        return None

    words = _collect(text, toks, i, NUMBER_WORDS)
    if not words:
        return None  # "one-off"
    groups, k = _parse_groups(words)
    end = i + k - 1  # index of the last token in the number
    nxt = _next(text, toks, end + 1, end)

    # Right after "dot" or "point" with no number before it: ambiguous
    # ("dot three", "point two five zero"), leave it.
    if i > 0 and toks[i - 1].low in ("dot", "point") and _joined(text, toks[i - 1], toks[i]):
        return k, None

    # "one thirty second" -> 1/32: the denominator's first word was read into the run.
    if k >= 2 and (words[k - 1], nxt) in COMPOUND_DENOMINATORS:
        num_groups, _ = _parse_groups(words[: k - 1])
        num = _whole(num_groups)
        den = COMPOUND_DENOMINATORS[(words[k - 1], nxt)]
        if num is not None and 0 < num < den:
            return k + 1, f"{num}/{den}"

    # "three sixteenths" -> 3/16. A run ending in a tens word is an ordinal
    # ("twenty third"), and improper fractions are left alone.
    if nxt in DENOMINATORS and words[k - 1] not in TENS:
        num = _whole(groups)
        den = DENOMINATORS[nxt]
        if num is not None and 0 < num < den:
            return k + 1, f"{num}/{den}"

    whole = _join(groups)

    # Decimal: "four point two" -> 4.2, "zero point one zero" -> 0.10.
    if nxt == "point" and " " not in whole:
        frac_start = end + 2
        if _next(text, toks, frac_start, end + 1) in STARTERS:
            frac_words = _collect(text, toks, frac_start, STARTERS)
            frac_groups, _ = _parse_groups(frac_words)
            digits = "".join(str(g) for g in frac_groups)
            return k + 1 + len(frac_words), f"{whole}.{digits}"

    # IPv4: two or more "dot"s between numbers that are each 0-255.
    if nxt == "dot":
        ip = _read_ip(text, toks, i, groups, k)
        if ip is not None:
            return ip
        return k, None

    # "twenty ninth", "one second": an ordinal follows, keep the words.
    if nxt in ORDINALS:
        return k, None

    if k == 1 and first == "one":
        return 1, None

    return k, whole


def _read_ip(text: str, toks: List[_Tok], i: int, groups: List[int], k: int) -> Optional[Tuple[int, str]]:
    octets = [_whole(groups)]
    j = i + k  # index of the token after the current part
    while j + 1 < len(toks) and toks[j].low == "dot" and _joined(text, toks[j - 1], toks[j]) \
            and toks[j + 1].low in STARTERS and _joined(text, toks[j], toks[j + 1]):
        words = _collect(text, toks, j + 1, NUMBER_WORDS)
        part_groups, used = _parse_groups(words)
        octets.append(_whole(part_groups))
        j = j + 1 + used
    if len(octets) < 3 or any(o is None or o > 255 for o in octets):
        return None
    return j - i, ".".join(str(o) for o in octets)


# Parakeet sometimes writes a spoken fraction in digits itself and garbles it:
# "one thirty second inch" comes out as "1.32nd inch" or "132 inch".
_DIGIT_ORDINAL_FRACTION = re.compile(r"\b(\d{1,2})[ .-](8|16|32|64)(?:th|nd)s?\b")
# Run-together form only for 16/32/64 and only before "inch", so real lengths
# like "18 inch" or "65 inch" are left alone.
_DIGIT_INCH_FRACTION = re.compile(r"\b(\d{1,2})(16|32|64)(?=\s+inch\b)")


def _repair_digit_fractions(text: str) -> Tuple[str, List[Change]]:
    changes: List[Change] = []

    def _sub(match: "re.Match[str]") -> str:
        num, den = int(match.group(1)), int(match.group(2))
        if num % 2 == 0 or not 0 < num < den:
            return match.group(0)  # machinist fractions are odd over a power of two
        fraction = f"{num}/{den}"
        changes.append((match.group(0), fraction))
        return fraction

    text = _DIGIT_ORDINAL_FRACTION.sub(_sub, text)
    text = _DIGIT_INCH_FRACTION.sub(_sub, text)
    return text, changes


def convert_numbers(text: str) -> Tuple[str, List[Change]]:
    """Rewrite spoken numbers as digits. Returns (new_text, [(spoken, written)])."""
    text, changes = _convert_words(text)
    text, repaired = _repair_digit_fractions(text)
    return text, changes + repaired


def _convert_words(text: str) -> Tuple[str, List[Change]]:
    toks = [_Tok(m.group().lower(), m.start(), m.end()) for m in _WORD.finditer(text)]
    out: List[str] = []
    changes: List[Change] = []
    pos = 0
    i = 0
    while i < len(toks):
        match = _match_at(text, toks, i)
        if match is None:
            i += 1
            continue
        used, replacement = match
        if replacement is not None:
            start, end = toks[i].start, toks[i + used - 1].end
            out.append(text[pos:start])
            out.append(replacement)
            changes.append((text[start:end], replacement))
            pos = end
        i += used
    out.append(text[pos:])
    return "".join(out), changes
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `scripts/test.sh tests/test_numbers.py`
Expected: all pass (`71 passed`).

- [ ] **Step 6: Commit**

```bash
git add text_cleanup/__init__.py text_cleanup/numbers.py tests/test_numbers.py requirements-dev.txt scripts/test.sh
git commit -m "Add spoken-number to digit rules for transcript cleanup" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NauotMQJMMpsaYGvCm16v2"
```

---

### Task 2: Vocabulary

**Files:**
- Create: `text_cleanup/vocabulary.py`
- Create: `tests/test_vocabulary.py`
- Create: `config/vocabulary.example.txt`
- Modify: `.gitignore` (append one line)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `parse_vocabulary(content: str, source: str = "vocabulary") -> Rules`
  - `Rules.apply(text: str) -> tuple[str, list[tuple[str, str]]]`
  - `Vocabulary(path: str)` with attribute `path` and method `rules() -> Rules` (re-reads the file when its mtime or size changes; missing file → empty rules; unreadable file → previous rules).

- [ ] **Step 1: Write the failing tests**

`tests/test_vocabulary.py`:
```python
import logging
import os

from text_cleanup.vocabulary import Vocabulary, parse_vocabulary

SAMPLE = """
# Right spelling = misheard variants
Corkie = Corky, core key, corkey
the Corkie = the quirky
"""


def apply(content, text):
    return parse_vocabulary(content).apply(text)


def test_replaces_variants_case_insensitively():
    text, changes = apply(SAMPLE, "I opened corky and the CORE KEY.")
    assert text == "I opened Corkie and the Corkie."
    assert changes == [("corky", "Corkie"), ("CORE KEY", "Corkie")]


def test_whole_words_only():
    assert apply(SAMPLE, "corkys corkyness")[0] == "corkys corkyness"


def test_possessive_follows():
    assert apply(SAMPLE, "Corky's code tab")[0] == "Corkie's code tab"


def test_multiword_variant_tolerates_extra_spaces():
    assert apply(SAMPLE, "the core   key app")[0] == "the Corkie app"


def test_context_rule_only_fixes_in_context():
    text = "It's quirky. Check the quirky now."
    assert apply(SAMPLE, text)[0] == "It's quirky. Check the Corkie now."


def test_keeps_sentence_start_capital():
    assert apply(SAMPLE, "The quirky is up.")[0] == "The Corkie is up."


def test_longer_variant_wins():
    rules = "Big = core\nCorkie = core key"
    assert apply(rules, "the core key")[0] == "the Corkie"


def test_unchanged_text_reports_nothing():
    assert apply("Corkie = corkie", "Corkie") == ("Corkie", [])


def test_bad_lines_are_skipped_and_logged(caplog):
    content = "bad line\n = nothing on the left\nNothing on the right =\nCorkie = Corky\n"
    with caplog.at_level(logging.WARNING):
        rules = parse_vocabulary(content, source="test.txt")
    assert rules.apply("Corky")[0] == "Corkie"
    assert len([r for r in caplog.records if "skipped" in r.message]) == 3


def test_empty_file_means_no_rules():
    assert apply("# only comments\n\n", "Corky stays") == ("Corky stays", [])


def test_missing_file_means_no_rules(tmp_path, caplog):
    vocab = Vocabulary(str(tmp_path / "missing.txt"))
    with caplog.at_level(logging.WARNING):
        assert vocab.rules().apply("Corky")[0] == "Corky"
        vocab.rules()
    assert len([r for r in caplog.records if "not found" in r.message]) == 1


def test_reloads_when_file_changes(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("Corkie = Corky\n")
    vocab = Vocabulary(str(path))
    assert vocab.rules().apply("Corky core key")[0] == "Corkie core key"

    path.write_text("Corkie = Corky, core key\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert vocab.rules().apply("Corky core key")[0] == "Corkie Corkie"


def test_unreadable_file_keeps_previous_rules(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("Corkie = Corky\n")
    vocab = Vocabulary(str(path))
    assert vocab.rules().apply("Corky")[0] == "Corkie"

    path.write_bytes(b"\xff\xfe not utf-8 \xff")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert vocab.rules().apply("Corky")[0] == "Corkie"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/test_vocabulary.py`
Expected: `ModuleNotFoundError: No module named 'text_cleanup.vocabulary'`.

- [ ] **Step 3: Implement the vocabulary module**

`text_cleanup/vocabulary.py`:
```python
"""Custom vocabulary: fix words the model keeps mishearing ("Corky" -> "Corkie").

File format, one rule per line, '#' starts a comment:

    Corkie = Corky, core key, corkey
    the Corkie = the quirky

Matching is case-insensitive and whole-word; the left side is written exactly
as given. The file is re-read when it changes, so edits apply without a restart.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

Change = Tuple[str, str]


def _normalize(phrase: str) -> str:
    return " ".join(phrase.lower().split())


@dataclass(frozen=True)
class Rules:
    """Parsed vocabulary: misheard variant (normalized) -> right spelling."""

    replacements: Dict[str, str] = field(default_factory=dict)
    pattern: Optional["re.Pattern[str]"] = None

    def apply(self, text: str) -> Tuple[str, List[Change]]:
        if self.pattern is None:
            return text, []
        changes: List[Change] = []

        def _sub(match: "re.Match[str]") -> str:
            heard = match.group(0)
            right = self.replacements[_normalize(heard)]
            if heard[0].isupper() and right[0].islower():
                right = right[0].upper() + right[1:]  # "The quirky" -> "The Corkie"
            if heard != right:
                changes.append((heard, right))
            return right

        return self.pattern.sub(_sub, text), changes


EMPTY_RULES = Rules()


def parse_vocabulary(content: str, source: str = "vocabulary") -> Rules:
    """Parse vocabulary file content. Bad lines are logged and skipped."""
    replacements: Dict[str, str] = {}
    for lineno, raw in enumerate(content.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        right, sep, variants = line.partition("=")
        right = " ".join(right.split())
        heard = [_normalize(v) for v in variants.split(",") if v.strip()]
        if not sep or not right or not heard:
            log.warning("%s line %d skipped, expected 'Right = misheard, misheard': %r", source, lineno, raw)
            continue
        for variant in heard:
            if variant in replacements and replacements[variant] != right:
                log.warning("%s line %d: %r was mapped to %r, now %r", source, lineno, variant, replacements[variant], right)
            replacements[variant] = right
    if not replacements:
        return EMPTY_RULES
    # Longest first so "core key" wins over a shorter overlapping variant.
    alternatives = sorted(replacements, key=len, reverse=True)
    body = "|".join(r"\s+".join(re.escape(w) for w in v.split()) for v in alternatives)
    pattern = re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)
    return Rules(replacements, pattern)


class Vocabulary:
    """Vocabulary file on disk, reloaded whenever it changes.

    A missing file means no rules (logged once). A file that can't be read
    keeps the previously loaded rules.
    """

    def __init__(self, path: str):
        self.path = path
        self._rules = EMPTY_RULES
        self._signature: Optional[Tuple[int, int]] = None
        self._missing_logged = False
        self._lock = threading.Lock()

    def rules(self) -> Rules:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            if not self._missing_logged:
                log.warning("vocabulary file %s not found; vocabulary fixes are off until it exists", self.path)
                self._missing_logged = True
            self._rules, self._signature = EMPTY_RULES, None
            return self._rules
        signature = (st.st_mtime_ns, st.st_size)
        if signature != self._signature:
            with self._lock:
                if signature != self._signature:
                    self._reload(signature)
        return self._rules

    def _reload(self, signature: Tuple[int, int]) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            # Remember the signature so the error is logged once per file change.
            self._signature = signature
            log.error("could not read vocabulary file %s (%s); keeping previous rules", self.path, exc)
            return
        self._rules = parse_vocabulary(content, source=self.path)
        self._signature = signature
        self._missing_logged = False
        log.info("loaded %d vocabulary fixes from %s", len(self._rules.replacements), self.path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/test_vocabulary.py`
Expected: `13 passed`.

- [ ] **Step 5: Add the example file and ignore the personal one**

`config/vocabulary.example.txt`:
```
# Custom vocabulary for transcript cleanup.
# Copy to config/vocabulary.txt (gitignored) and edit. Changes apply on the
# next transcription, no restart needed.
#
# Format: Right spelling = misheard variant, misheard variant, ...
# Matching ignores case and only hits whole words. Use a longer phrase when
# the misheard version is a real word, so it is only fixed in that context.

Kubernetes = cooper netties, cuber netties
PostgreSQL = post gress, postgres equal
the Grafana = the griffon ah
```

Append to `.gitignore`:
```
# Personal transcript-cleanup word list (see config/vocabulary.example.txt)
config/vocabulary.txt
```

Verify: `git check-ignore config/vocabulary.txt` prints `config/vocabulary.txt`.

- [ ] **Step 6: Commit**

```bash
git add text_cleanup/vocabulary.py tests/test_vocabulary.py config/vocabulary.example.txt .gitignore
git commit -m "Add hot-reloading custom vocabulary for transcript cleanup" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NauotMQJMMpsaYGvCm16v2"
```

---

### Task 3: Cleanup entry point

**Files:**
- Modify: `text_cleanup/__init__.py` (replace the stub entirely)
- Create: `tests/test_clean.py`

**Interfaces:**
- Consumes: `convert_numbers` (Task 1), `Vocabulary`, `parse_vocabulary`, `Rules.apply` (Task 2).
- Produces:
  - `CleanResult(text: str, changes: tuple[tuple[str, str], ...])` (frozen dataclass)
  - `clean(text: str, vocabulary: Vocabulary | None = None) -> CleanResult` (vocabulary first, then numbers; never raises)
  - `clean_segments(segments: list[dict], vocabulary: Vocabulary | None = None) -> list[tuple[str, str]]` (rewrites each `seg["segment"]` in place; other keys untouched)
  - Re-exports `Vocabulary`, `parse_vocabulary`.

- [ ] **Step 1: Write the failing tests**

`tests/test_clean.py`:
```python
import text_cleanup
from text_cleanup import Vocabulary, clean, clean_segments


def vocab_file(tmp_path, content="Corkie = Corky, core key\n"):
    path = tmp_path / "vocabulary.txt"
    path.write_text(content)
    return Vocabulary(str(path))


def test_vocabulary_then_numbers(tmp_path):
    result = clean("Pin it to Corky at four point two volts.", vocab_file(tmp_path))
    assert result.text == "Pin it to Corkie at 4.2 volts."
    assert result.changes == (("Corky", "Corkie"), ("four point two", "4.2"))


def test_numbers_only_without_vocabulary():
    assert clean("two options").text == "2 options"


def test_never_raises(monkeypatch, caplog):
    def boom(text):
        raise RuntimeError("bug in a rule")

    monkeypatch.setattr(text_cleanup, "convert_numbers", boom)
    result = clean("four point two volts")
    assert result.text == "four point two volts"
    assert result.changes == ()
    assert "returning the raw transcript" in caplog.text


def test_clean_segments_in_place(tmp_path):
    segments = [
        {"start": 0.0, "end": 1.0, "segment": "core key has two tabs"},
        {"start": 1.0, "end": 2.0, "segment": "nothing here"},
    ]
    changes = clean_segments(segments, vocab_file(tmp_path))
    assert [s["segment"] for s in segments] == ["Corkie has 2 tabs", "nothing here"]
    assert segments[0]["start"] == 0.0
    assert changes == [("core key", "Corkie"), ("two", "2")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/test_clean.py`
Expected: `ImportError: cannot import name 'Vocabulary' from 'text_cleanup'`.

- [ ] **Step 3: Implement the entry point**

`text_cleanup/__init__.py`:
```python
"""Post-transcription cleanup: custom vocabulary, then spoken numbers to digits."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .numbers import convert_numbers
from .vocabulary import Vocabulary, parse_vocabulary

__all__ = ["CleanResult", "Vocabulary", "clean", "clean_segments", "parse_vocabulary"]

log = logging.getLogger(__name__)

Change = Tuple[str, str]


@dataclass(frozen=True)
class CleanResult:
    text: str
    changes: Tuple[Change, ...]


def clean(text: str, vocabulary: Optional[Vocabulary] = None) -> CleanResult:
    """Apply vocabulary fixes, then number rules. Never raises: on any error
    the original text comes back unchanged and the error is logged."""
    try:
        changes: List[Change] = []
        if vocabulary is not None:
            text_out, found = vocabulary.rules().apply(text)
            changes.extend(found)
        else:
            text_out = text
        text_out, found = convert_numbers(text_out)
        changes.extend(found)
        return CleanResult(text_out, tuple(changes))
    except Exception:
        log.exception("transcript cleanup failed; returning the raw transcript")
        return CleanResult(text, ())


def clean_segments(segments: List[dict], vocabulary: Optional[Vocabulary] = None) -> List[Change]:
    """Clean each segment's "segment" text in place. Returns all changes made."""
    changes: List[Change] = []
    for seg in segments:
        result = clean(seg["segment"], vocabulary)
        seg["segment"] = result.text
        changes.extend(result.changes)
    return changes
```

- [ ] **Step 4: Run the whole suite**

Run: `scripts/test.sh`
Expected: `88 passed`.

- [ ] **Step 5: Commit**

```bash
git add text_cleanup/__init__.py tests/test_clean.py
git commit -m "Add clean() entry point that never loses a transcript" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NauotMQJMMpsaYGvCm16v2"
```

---

### Task 4: Review script and owner sign-off

**Files:**
- Create: `scripts/review_cleanup.py`

**Interfaces:**
- Consumes: `clean`, `Vocabulary` (Task 3).
- Produces: CLI `python3 scripts/review_cleanup.py <transcripts.json> [--vocabulary PATH] [--show N]`; prints `<changed> of <total> transcripts changed, <n> edits`, then one line per distinct change sorted by count, then optional before/after examples.

- [ ] **Step 1: Write the script**

`scripts/review_cleanup.py`:
```python
#!/usr/bin/env python3
"""Show every change transcript cleanup would make to a set of real transcripts.

    python scripts/review_cleanup.py transcripts.json [--vocabulary config/vocabulary.txt] [--show 20]

transcripts.json is a JSON list of strings. It holds private dictation, so
keep it outside the repo.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from text_cleanup import Vocabulary, clean  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("transcripts", help="JSON file containing a list of transcript strings")
    parser.add_argument("--vocabulary", default="config/vocabulary.txt", help="vocabulary file to apply")
    parser.add_argument("--show", type=int, default=0, help="also print N changed transcripts before/after")
    args = parser.parse_args()

    with open(args.transcripts, encoding="utf-8") as fh:
        texts = json.load(fh)
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        parser.error("transcripts file must be a JSON list of strings")

    vocabulary = Vocabulary(args.vocabulary)
    counts = collections.Counter()
    changed = 0
    examples = []
    for text in texts:
        result = clean(text, vocabulary)
        if result.changes:
            changed += 1
            counts.update(result.changes)
            if len(examples) < args.show:
                examples.append((text, result.text))

    print(f"{changed} of {len(texts)} transcripts changed, {sum(counts.values())} edits\n")
    for (heard, written), n in counts.most_common():
        print(f"{n:4d}  {heard!r} -> {written!r}")
    for before, after in examples:
        print(f"\nBEFORE: {before}\nAFTER:  {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test it on a throwaway file**

```bash
printf '["Pin it to Corky at four point two volts.", "nothing here"]' > /tmp/review_smoke.json
python3 scripts/review_cleanup.py /tmp/review_smoke.json --vocabulary config/vocabulary.example.txt --show 1
```
Expected output starts with `1 of 2 transcripts changed, 1 edits` and lists `'four point two' -> '4.2'` ("Corky" is not in the example file, so it stays).

- [ ] **Step 3: Commit**

```bash
git add scripts/review_cleanup.py
git commit -m "Add review script to dry-run cleanup over a transcript archive" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NauotMQJMMpsaYGvCm16v2"
```

- [ ] **Step 4 (driver, after Task 6): Owner review gate**

Run the script over the private archive (path held by the driver, outside the repo) with the seeded vocabulary and `--show 15`. Send the owner the summary. Do not start Task 7 until the owner approves the change list or asks for rule changes.

---

### Task 5: Wire cleanup into the server

**Files:**
- Modify: `app.py` (three insertions, shown with their anchor lines)
- Modify: `Dockerfile.cpu:31-35`, `Dockerfile.gpu:45-49`
- Modify: `docker-compose.yml` (both `volumes:` lists)
- Modify: `DOCKER.md` (environment table), `CLAUDE.md`

**Interfaces:**
- Consumes: `Vocabulary`, `clean_segments` (Task 3).
- Produces: form field `cleanup` on `POST /v1/audio/transcriptions` (`false`/`0`/`no`/`off` returns raw text); env `TRANSCRIPT_CLEANUP` (default `true`) and `VOCABULARY_PATH` (default `config/vocabulary.txt`); log line `[<job id>] Cleanup: heard -> written; ...`.

- [ ] **Step 1: Imports and logging setup in `app.py`**

Directly after the line `from pathlib import Path` (line 29), insert:
```python
import logging

from text_cleanup import Vocabulary, clean_segments

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
```

- [ ] **Step 2: Cleanup configuration in `app.py`**

Directly after the line `progress_tracker = {}` (line 101), insert:
```python

# Transcript cleanup: custom vocabulary, then spoken numbers to digits.
FALSE_VALUES = ("false", "0", "no", "off")
CLEANUP_ENABLED = os.environ.get("TRANSCRIPT_CLEANUP", "true").strip().lower() not in FALSE_VALUES
vocabulary = Vocabulary(os.environ.get("VOCABULARY_PATH", "config/vocabulary.txt"))
print(f"Transcript cleanup: {'on' if CLEANUP_ENABLED else 'off'} (vocabulary: {vocabulary.path})")
```

- [ ] **Step 3: Apply cleanup in `transcribe_audio`**

Find these lines (around line 640):
```python
        # Update progress to complete
        progress_tracker[unique_id]["status"] = "complete"
        progress_tracker[unique_id]["progress_percent"] = 100
```
Directly after them insert:
```python

        wants_cleanup = request.form.get("cleanup", "true").strip().lower() not in FALSE_VALUES
        if CLEANUP_ENABLED and wants_cleanup:
            cleanup_changes = clean_segments(all_segments, vocabulary)
            if cleanup_changes:
                print(f"[{unique_id}] Cleanup: " + "; ".join(f"{heard} -> {written}" for heard, written in cleanup_changes))
```
(`full_text`, SRT and VTT are all built from `all_segments` after this point, so every format gets the cleaned text. The `parakeet_srt_words` token list is built from `all_words` and stays raw by design.)

Verify: `python3 -m py_compile app.py` exits 0.

- [ ] **Step 4: Dockerfiles copy the package and create the config dir**

In both `Dockerfile.cpu` and `Dockerfile.gpu`, after `COPY templates/ templates/` add:
```dockerfile
COPY text_cleanup/ text_cleanup/
```
and change `RUN mkdir -p temp_uploads models && \` to:
```dockerfile
RUN mkdir -p temp_uploads models config && \
```

- [ ] **Step 5: Mount the vocabulary read-only in `docker-compose.yml`**

In both services, under `volumes:` after `- parakeet-models:/app/models`, add:
```yaml
      - ./config:/app/config:ro
```

- [ ] **Step 6: Document it**

In `DOCKER.md`, append these rows to the Environment Variables table (after the `HF_HUB_CACHE` row):
```markdown
| `INFERENCE_DEVICE` | `cpu` | `cpu` or `gpu`. `gpu` uses CUDA when available, else CPU |
| `PARAKEET_MODEL` | `nemo-parakeet-tdt-0.6b-v3` | onnx-asr model name. `nemo-parakeet-tdt-0.6b-v2` is English-only and more accurate on English |
| `PARAKEET_QUANTIZATION` | `int8` | `int8` or `none` (fp32). Same CPU speed, fp32 uses ~2 GB more RAM |
| `TRANSCRIPT_CLEANUP` | `true` | Spoken numbers to digits plus custom vocabulary. `false` returns raw model text |
| `VOCABULARY_PATH` | `config/vocabulary.txt` | Word list file (see `config/vocabulary.example.txt`). Re-read on change |
```

In `CLAUDE.md`, under `## Commands` after the smoke-test block, add:
```markdown
Tests (pytest in a Python 3.10 container, no host install needed): `scripts/test.sh`, or `scripts/test.sh tests/test_numbers.py -k fraction` for a subset. Dry-run the cleanup over a private transcript archive with `python3 scripts/review_cleanup.py <transcripts.json> --show 10`.
```
and add a final bullet under `## Architecture notes that span the file`:
```markdown
- **Transcript cleanup** (`text_cleanup/`, stdlib only) runs once per request after transcription via `clean_segments()`: vocabulary fixes from `config/vocabulary.txt` (gitignored, bind-mounted read-only, re-read on change), then spoken numbers to digits. Rules and their rationale are in `docs/superpowers/specs/2026-10-02-transcript-cleanup-design.md`. `clean()` never raises; on error the raw text is returned. Opt out per request with form field `cleanup=false` or server-wide with `TRANSCRIPT_CLEANUP=false`.
```
Also in `CLAUDE.md`, replace the sentence "There is no test suite, linter, or build step." with "There is no linter or build step; the only tests cover `text_cleanup/`."

- [ ] **Step 7: Verify the image builds with the package**

Run: `docker compose build parakeet-cpu && docker run --rm --entrypoint python parakeet-tdt:cpu -c "from text_cleanup import clean; print(clean('four point two volts').text)"`
Expected: build succeeds, prints `4.2 volts`. (Do not restart the running container yet; that is Task 7.)

- [ ] **Step 8: Commit**

```bash
git add app.py Dockerfile.cpu Dockerfile.gpu docker-compose.yml DOCKER.md CLAUDE.md
git commit -m "Run transcript cleanup on every transcription" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NauotMQJMMpsaYGvCm16v2"
```

---

### Task 6 (driver): Seed the personal vocabulary

**Files:**
- Create: `config/vocabulary.txt` (gitignored, never committed)

Done by the driving session, not a subagent: it needs the private archive and judgment about what counts as a mishearing.

- [ ] **Step 1: Start the file with the confirmed Corkie fixes**

```
# Personal vocabulary. Format: Right spelling = misheard, misheard
Corkie = Corky, core key, corkey
the Corkie = the quirky
```

- [ ] **Step 2: Search the archive for other misheard names**

For each name the owner uses (Corkie, whizpurr, brainBoard, droidCarl, frameGrep, Gumshoe, Hermes, Onefinity, jakku, naboo, hank, Parakeet, n8n, llama-swap), list near-miss spellings in the archive with a fuzzy match (`difflib.get_close_matches` over the archive's words and two-word phrases, cutoff 0.75), read the surrounding text of each hit, and add a line only for variants that are clearly that name. Real words that are sometimes a mishearing (like "quirky") get a context phrase, not a bare entry.

- [ ] **Step 3: Confirm it loads**

Run: `python3 -c "from text_cleanup import Vocabulary; v=Vocabulary('config/vocabulary.txt'); print(len(v.rules().replacements))"`
Expected: a count matching the number of variants written, and no "skipped" warnings.

Then run the Task 4 Step 4 owner review gate.

---

### Task 7: Deploy and verify end to end

**Files:** none changed.

- [ ] **Step 1: Restart the container on the new image**

Run: `docker compose up -d parakeet-cpu`, then poll `curl -s localhost:5092/health` until it answers (fp32 model load takes up to ~60 s).
Expected: health JSON, and `docker logs parakeet-cpu 2>&1 | grep -E "Transcript cleanup|vocabulary"` shows `Transcript cleanup: on (vocabulary: config/vocabulary.txt)` and `loaded N vocabulary fixes`.

- [ ] **Step 2: Synthesize a known sentence with the local TTS server**

```bash
curl -s -o /tmp/e2e.wav localhost:8880/v1/audio/speech -H 'Content-Type: application/json' \
  -d '{"model":"tts-1","voice":"ryan","response_format":"wav","input":"I have two options here. Set it to four point two volts."}'
```

- [ ] **Step 3: Cleaned vs raw**

```bash
curl -s -F file=@/tmp/e2e.wav -F response_format=text localhost:5092/v1/audio/transcriptions; echo
curl -s -F file=@/tmp/e2e.wav -F response_format=text -F cleanup=false localhost:5092/v1/audio/transcriptions; echo
docker logs parakeet-cpu 2>&1 | grep "Cleanup:" | tail -1
```
Expected: the first output has digits where the second has number words (the model itself sometimes writes digits for clear TTS audio; if both are identical, change the input sentence until the raw output contains a spelled-out number), and the log line lists exactly those changes.

- [ ] **Step 4: Vocabulary hot reload on the live server**

Append `Testword = tango whiskey` to `config/vocabulary.txt`, synthesize `"Say tango whiskey twice."`, transcribe it, and confirm the output contains `Testword` with no restart. Then remove the line.

- [ ] **Step 5: Push the branch to the backup remote**

Run: `git push -u fork feature/transcript-cleanup`

- [ ] **Step 6: Hand off to the owner** for a real dictation test from the dictation app, then merge `feature/transcript-cleanup` into `my-setup` once approved.
