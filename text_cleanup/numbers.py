"""Spoken numbers to digits for dictated text.

Digits for every number except a lone "one". Handles decimals ("four point
two" -> 4.2), fractions ("one thirty second" -> 1/32), numbers spoken in
chunks ("four seventy" -> 470) and dotted IPv4 addresses. Unit words are left
as spoken. Full rules: docs/superpowers/specs/2026-10-02-transcript-cleanup-design.md
"""

from __future__ import annotations

import math
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
# Only in lowest terms, so "two quarters" (coins) and "four eighths" stay words.
DENOMINATORS = {
    "half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4,
    "eighth": 8, "eighths": 8, "sixteenth": 16, "sixteenths": 16,
}
# "<numerator> thirty second(s)" -> n/32, "<numerator> sixty fourth(s)" -> n/64.
COMPOUND_DENOMINATORS = {
    ("thirty", "second"): 32, ("thirty", "seconds"): 32,
    ("sixty", "fourth"): 64, ("sixty", "fourths"): 64,
}
# Singular half/third/quarter need a numerator of 1 ("one quarter"); "two third
# party vendors" is not a fraction. Plurals ("three quarters") allow any numerator.
SINGULAR_ONE_ONLY = {"half", "third", "quarter"}
# "a"/"an" count as 1 only before these, so "a third option" and
# "a half hour" stay as words while "an eighth inch" becomes 1/8.
ARTICLE_DENOMINATORS = {"eighth": 8, "sixteenth": 16}
# "a thirty second" is a fraction only before "inch" ("a thirty second timeout"
# is a duration).
ARTICLE_COMPOUND_UNITS = {"inch", "inches"}

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
        elif w == "and":
            # Only reached between "<hundred|thousand>" and a number word that
            # continues it ("one hundred and fifty"); otherwise it ends the number.
            if not _and_continues(cur, last, words[used + 1:]):
                return _close(groups, cur), used
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


def _and_continues(cur: Optional[int], last: str, rest: List[str]) -> bool:
    """True when "and" after a hundred/thousand leads into a word that adds to it."""
    if cur is None or last not in ("hundred", "thousand") or not rest or rest[0] not in STARTERS:
        return False
    kind = "unit" if rest[0] in UNITS else "teen" if rest[0] in TEENS else "tens"
    if not _continues(cur, last, kind, STARTERS[rest[0]]):
        return False
    return _scale_can_follow(cur, rest)


def _scale_can_follow(cur: int, rest: List[str]) -> bool:
    """False when the number after "and" is followed by a hundred/thousand that
    could not attach to it ("one hundred and one hundred" is two numbers)."""
    tail = []
    for w in rest:
        if w not in STARTERS:
            break
        tail.append(w)
    follow = rest[len(tail)] if len(tail) < len(rest) else None
    if follow not in SCALES:
        return True
    groups, _ = _parse_groups(tail)
    if len(groups) != 1:
        return False
    total = cur + groups[0]
    return 1 <= total % 1000 <= 99 if follow == "hundred" else 1 <= total <= 999


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


def _collect(text: str, toks: List[_Tok], i: int, allowed) -> Tuple[List[str], bool]:
    """Number words starting at toks[i], joined by whitespace/hyphens.

    "and" is kept inside the run when it links "hundred"/"thousand" to a
    following number word ("one hundred and fifty"). Returns (words, blocked):
    blocked is True when the run was cut short by a number word hyphenated to a
    non-number ("sixty-four-bit", "five-volt"); the caller leaves the whole run,
    that word included, as spoken.
    """
    words: List[str] = []
    j = i
    while j < len(toks) and (j == i or _joined(text, toks[j - 1], toks[j])):
        low = toks[j].low
        if low == "and" and words and words[-1] in SCALES and _number_follows(text, toks, j, allowed):
            words.append(low)
        elif low in allowed:
            if _hyphen_compound(text, toks, j, allowed):
                return words, True
            words.append(low)
        else:
            break
        j += 1
    return words, False


def _number_follows(text: str, toks: List[_Tok], j: int, allowed) -> bool:
    return j + 1 < len(toks) and toks[j + 1].low in allowed and _joined(text, toks[j], toks[j + 1])


def _hyphenated_to_next(text: str, toks: List[_Tok], j: int) -> bool:
    """True when toks[j] is joined to the next word by a hyphen ("half-hour")."""
    return j + 1 < len(toks) and text[toks[j].end:toks[j + 1].start] == "-"


def _hyphen_compound(text: str, toks: List[_Tok], j: int, allowed) -> bool:
    return (
        _hyphenated_to_next(text, toks, j)
        and toks[j + 1].low not in allowed
        and not _hyphenated_denominator(text, toks, j)
    )


def _hyphenated_denominator(text: str, toks: List[_Tok], j: int) -> bool:
    """True when toks[j] and the hyphenated word after it spell a fraction
    denominator the model wrote with a hyphen: "thirty-second", "sixty-fourths",
    or a number word before "quarters" in "three-quarters". A denominator that
    is itself hyphenated onward ("one-half-hour") is a compound, not a fraction."""
    nxt = toks[j + 1].low
    if (toks[j].low, nxt) in COMPOUND_DENOMINATORS:
        return True
    return nxt in DENOMINATORS and not _hyphenated_to_next(text, toks, j + 1)


def _follows_scale_and(text: str, toks: List[_Tok], i: int, converted_end: int) -> bool:
    """True when toks[i] sits right after "<hundred|thousand> and" and that
    scale word was not itself part of a converted number."""
    return (
        i >= 2
        and converted_end < i - 2
        and toks[i - 1].low == "and"
        and toks[i - 2].low in SCALES
        and _joined(text, toks[i - 2], toks[i - 1])
        and _joined(text, toks[i - 1], toks[i])
    )


def _is_fraction(num: Optional[int], word: str, den: int) -> bool:
    """Is "<num> <word>" a fraction? Lowest terms, proper, and a numerator of 1
    for the singular half/third/quarter."""
    if num is None or not 0 < num < den or math.gcd(num, den) != 1:
        return False
    return num == 1 or word not in SINGULAR_ONE_ONLY


def _next(text: str, toks: List[_Tok], j: int, prev: int) -> Optional[str]:
    """Lowercased word at toks[j] if it directly follows toks[prev]."""
    if j < len(toks) and _joined(text, toks[prev], toks[j]):
        return toks[j].low
    return None


def _match_at(text: str, toks: List[_Tok], i: int, converted_end: int = -1) -> Optional[Tuple[int, Optional[str]]]:
    """Try to read a number starting at toks[i].

    converted_end is the index of the last token already rewritten as digits.
    Returns None if no number starts here, else (tokens consumed, replacement),
    where replacement None means "leave these words as spoken".
    """
    first = toks[i].low

    if first in ("a", "an"):
        nxt = _next(text, toks, i + 1, i)
        if nxt in ARTICLE_DENOMINATORS:
            return 2, f"1/{ARTICLE_DENOMINATORS[nxt]}"
        after = _next(text, toks, i + 2, i + 1) if nxt else None
        if (nxt, after) in COMPOUND_DENOMINATORS and _next(text, toks, i + 3, i + 2) in ARTICLE_COMPOUND_UNITS:
            return 3, f"1/{COMPOUND_DENOMINATORS[(nxt, after)]}"
        return None

    if first not in STARTERS:
        return None

    # Hyphenated onto a preceding word ("non-zero"): part of that word.
    if i > 0 and text[toks[i - 1].end:toks[i].start] == "-" and toks[i - 1].low not in NUMBER_WORDS:
        return None

    words, blocked = _collect(text, toks, i, NUMBER_WORDS)
    if blocked:
        return len(words) + 1, None  # "sixty-four-bit", "one-off": all stays as spoken
    groups, k = _parse_groups(words)
    end = i + k - 1  # index of the last token in the number
    nxt = _next(text, toks, end + 1, end)

    # "a hundred and fifty": the number before "and" did not convert, so
    # converting only the tail would split it ("a hundred and 50").
    if _follows_scale_and(text, toks, i, converted_end):
        return k, None

    # Right after "dot" or "point" with no number before it: ambiguous
    # ("dot three", "point two five zero"), leave it.
    if i > 0 and toks[i - 1].low in ("dot", "point") and _joined(text, toks[i - 1], toks[i]):
        return k, None

    # "one thirty second" -> 1/32: the denominator's first word was read into the run.
    if k >= 2 and (words[k - 1], nxt) in COMPOUND_DENOMINATORS and not _hyphenated_to_next(text, toks, end + 1):
        num_groups, _ = _parse_groups(words[: k - 1])
        den = COMPOUND_DENOMINATORS[(words[k - 1], nxt)]
        if _is_fraction(_whole(num_groups), nxt, den):
            return k + 1, f"{_whole(num_groups)}/{den}"

    # "four thirty-seconds": hyphenated compound denominator that is not a
    # fraction, so the phrase stays as spoken.
    if (words[k - 1], nxt) in COMPOUND_DENOMINATORS and text[toks[end].end:toks[end + 1].start] == "-":
        return k + 1, None

    # "three sixteenths" -> 3/16. A run ending in a tens word is an ordinal
    # ("twenty third"); "half-hour" and "quarter-inch" are not denominators.
    if nxt in DENOMINATORS and words[k - 1] not in TENS and not _hyphenated_to_next(text, toks, end + 1):
        num = _whole(groups)
        den = DENOMINATORS[nxt]
        if _is_fraction(num, nxt, den):
            return k + 1, f"{num}/{den}"

    # "two-quarters": hyphenated denominator that is not a fraction, so the
    # whole phrase stays as spoken.
    if nxt in DENOMINATORS and text[toks[end].end:toks[end + 1].start] == "-":
        return k, None

    whole = _join(groups)

    # Decimal: "four point two" -> 4.2, "zero point one zero" -> 0.10.
    if nxt == "point" and " " not in whole:
        frac_start = end + 2
        if _next(text, toks, frac_start, end + 1) in STARTERS:
            frac_words, frac_blocked = _collect(text, toks, frac_start, STARTERS)
            if frac_blocked:  # "four point two-bit"
                return k + 1 + len(frac_words) + 1, None
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
        words, blocked = _collect(text, toks, j + 1, NUMBER_WORDS)
        if blocked:
            return None
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
    converted_end = -1
    while i < len(toks):
        match = _match_at(text, toks, i, converted_end)
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
            converted_end = i + used - 1
        i += used
    out.append(text[pos:])
    return "".join(out), changes
