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
