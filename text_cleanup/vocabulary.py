"""Custom vocabulary: fix words the model keeps mishearing ("Corky" -> "Corkie").

File format, one rule per line, '#' starts a comment (at line start or after
whitespace, so "C# = see sharp" is a rule):

    Corkie = Corky, core key, corkey
    the Corkie = the quirky

Matching is case-insensitive and whole-word; the left side is written exactly
as given, except that a lowercase name is capitalized at the start of a
sentence (never mid-sentence, never camelCase spellings like "iPhone"). The
file is re-read when it changes, so edits apply without a restart.
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


_COMMENT = re.compile(r"(?:^|\s)#.*")


def _normalize(phrase: str) -> str:
    return " ".join(phrase.lower().split())


_SENTENCE_START = re.compile(r"(?:\A|[.!?]\s+)\Z")


def _starts_sentence(match: "re.Match[str]") -> bool:
    """True at the very start of the text or right after ". ", "! " or "? "."""
    return _SENTENCE_START.search(match.string[: match.start()]) is not None


def _can_capitalize(right: str) -> bool:
    """A lowercase first letter may be capitalized, unless the spelling has
    capitals after it (camelCase brands such as "iPhone" keep their spelling)."""
    return right[0].islower() and not any(c.isupper() for c in right.split()[0][1:])


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
            right = self.replacements.get(_normalize(heard))
            if right is None:  # case folding the regex allows but .lower() does not ("İ")
                return heard
            if _starts_sentence(match) and heard[0].isupper() and _can_capitalize(right):
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
        line = _COMMENT.sub("", raw).strip()
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
    or stat'ed keeps the previously loaded rules.
    """

    def __init__(self, path: str):
        self.path = path
        self._rules = EMPTY_RULES
        self._signature: Optional[Tuple[int, int]] = None
        self._missing_logged = False
        self._stat_error: Optional[str] = None
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
        except OSError as exc:
            # Keep the previous rules; log once per distinct error.
            if self._stat_error != str(exc):
                self._stat_error = str(exc)
                log.error("could not read vocabulary file %s (%s); keeping previous rules", self.path, exc)
            return self._rules
        self._stat_error = None
        signature = (st.st_mtime_ns, st.st_size)
        if signature != self._signature:
            with self._lock:
                if signature != self._signature:
                    self._reload(signature)
        return self._rules

    def _reload(self, signature: Tuple[int, int]) -> None:
        try:
            with open(self.path, encoding="utf-8-sig") as fh:
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
