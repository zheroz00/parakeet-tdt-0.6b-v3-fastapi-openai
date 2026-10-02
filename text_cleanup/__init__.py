"""Post-transcription cleanup: custom vocabulary, then spoken numbers to digits."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

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
    """Apply vocabulary fixes, then number rules. Never raises: a stage that
    fails is logged and skipped (its input text comes back unchanged), so one
    broken stage cannot disable the other."""
    changes: List[Change] = []
    if vocabulary is not None:
        text = _run_stage("vocabulary", lambda t: vocabulary.rules().apply(t), text, changes)
    text = _run_stage("number", convert_numbers, text, changes)
    return CleanResult(text, tuple(changes))


def _run_stage(name: str, stage: Callable[[str], Tuple[str, List[Change]]], text: str, changes: List[Change]) -> str:
    """Run one cleanup stage. On failure, log it and return the text unchanged."""
    try:
        text_out, found = stage(text)
    except Exception:
        log.exception("transcript cleanup (%s stage) failed; skipping it", name)
        return text
    changes.extend(found)
    return text_out


def clean_segments(segments: List[dict], vocabulary: Optional[Vocabulary] = None) -> List[Change]:
    """Clean each segment's "segment" text in place. Returns all changes made."""
    changes: List[Change] = []
    for seg in segments:
        result = clean(seg["segment"], vocabulary)
        seg["segment"] = result.text
        changes.extend(result.changes)
    return changes
