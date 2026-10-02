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
