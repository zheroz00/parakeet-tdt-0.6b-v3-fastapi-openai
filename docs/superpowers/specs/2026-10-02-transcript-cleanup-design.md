# Transcript cleanup: numbers as digits + custom vocabulary

Date: 2026-10-02
Status: approved design, pending implementation plan

## Goal

Dictation mostly goes to AI agents and is often not proofread. Two recurring
transcription problems cause confusing agent replies:

1. Numbers come back spelled out ("zero point five degrees") when digits are wanted.
2. Project names and jargon come back misspelled ("Corky", "core key" instead of "Corkie").

Add a post-processing step to this server so every client (dictation app, voice
chat) gets corrected text, with no change to the clients.

**Success:** across the existing archive of ~1,800 real transcripts, the review
run shows the intended conversions and no damage to ordinary prose; the
owner signs off on that list before deploy.

## Rejected approaches (measured 2026-10-02)

- **NVIDIA `nemo_text_processing` inverse normalization.** Built for lowercase,
  unpunctuated ASR output. On real punctuated dictation more than half of its
  284 edits were damage: "first" → "1st" (64x), "for example" → "e.g.",
  "at all. That" → "@all.That", "one thirty second inch" → "01:30 2nd inch".
  Also needs ~150 MB of grammar dependencies plus gcc in the image.
- **`text2num` (`alpha2digit`).** No context awareness: "one of the" → "1 of the",
  "ones" → "1", "the first one" → "the 1st 1".
- **Local LLM cleanup pass.** Best at context, but adds 0.5-3 s per request,
  competes for the GPU, and can silently reword dictation.

## Design

### Pipeline

`raw ASR text → vocabulary replacements → number rules → response`

Applied to the final text and to each segment's text, so `json`, `text`,
`verbose_json`, `srt` and `vtt` all get cleaned output. The legacy
`parakeet_srt_words` token list is left untouched (token timings).

### Number rules

Digits for every number except a lone "one". Unit words stay as spoken.

| Spoken | Output |
|---|---|
| zero point one five millimeters | 0.15 millimeters |
| four point two volts | 4.2 volts |
| twenty four volts / thirty seven percent | 24 volts / 37 percent |
| two seconds / two options | 2 seconds / 2 options |
| four seventy cap | 470 cap |
| eighteen six fifty cell | 18650 cell |
| fifty six hundred | 5600 |
| one ninety seven | 197 |
| one eighth of / three sixteenth inch | 1/8 of / 3/16 inch |
| one thirty second inch bit | 1/32 inch bit |
| thirty seconds | 30 seconds |
| one ninety two dot one sixty eight dot one dot twenty | 192.168.1.20 |

Unchanged:

- Lone "one": "one of the", "the first one".
- Ordinals: "first", "second", "eighth" (unless part of a fraction).
- "point" with no number word before it: "at that point", "point being",
  "point two five zero" (accepted miss, avoids "at that point two things" → ".2 things").
- "dot" unless it joins at least three numeric groups that are each 0-255:
  "three dot menu", "the red dot in" stay.
- Unit words are never abbreviated ("millimeters" stays, not "mm").

Rule details:

- **Number group:** a run of number words parsed to a value
  ("one hundred ninety seven" → 197, "twenty six" → 26).
- **Chunked numbers:** adjacent groups are concatenated when every group after
  the first is a two-digit value (10-99) or a single digit in a digit sequence
  ("four seventy" → 470, "eighteen six fifty" → 18650, "five six seven eight" → 5678).
  "X hundred" with X > 9 multiplies ("fifty six hundred" → 5600).
  Known trade-off: a spoken time "one twenty" also becomes 120.
- **Decimals:** `<number> point <digit words>` → `N.DDD`, keeping trailing
  zeros ("zero point one zero" → 0.10).
- **Fractions:** `<numerator> <denominator>` where denominator is half, third,
  quarter, eighth, sixteenth, thirty second, sixty fourth (optionally plural)
  → `n/d`. Numerator may be "a"/"an" (= 1). "thirty second"/"sixty fourth" only
  become a fraction denominator when a numerator precedes them; "thirty seconds"
  is a duration → "30 seconds".
- **IPv4:** two or more `dot` separators (three or more number groups), each group 0-255.
- Capitalized number words at sentence start convert the same way
  ("Two options" → "2 options"); "One" alone stays.
- Hyphenated forms ("thirty-two") are treated like spaced ones.

### Vocabulary (word list)

- Plain text file `config/vocabulary.txt`, mounted read-only into the container.
  Format, one rule per line, `#` comments:
  ```
  # Right spelling = misheard variants
  Corkie = Corky, core key, corkey
  the Corkie = the quirky
  ```
- Matching is case-insensitive and whole-word; possessives follow ("Corky's" →
  "Corkie's"). Output uses the left side exactly as written. Longer variants
  are matched before shorter ones.
- Context rules are just longer phrases ("the quirky"), so a real-word
  mishearing is only fixed in that context.
- Hot reload: file mtime is checked per request; edits apply on the next
  transcription without a restart.
- The real `config/vocabulary.txt` is personal and gitignored;
  `config/vocabulary.example.txt` is committed with placeholder entries.
- Initial seed: Corkie variants found in the archive, plus any project names
  the archive shows being misheard.

### Safety and visibility

- If cleanup raises, the raw transcript is returned and the error is logged.
  A transcript is never lost to cleanup.
- A malformed vocabulary line is logged and skipped; the rest still loads.
  A missing file means no vocabulary rules (logged once), numbers still apply.
- When cleanup changes text, the log records only the changed spans
  (`Corky → Corkie`, `four point two → 4.2`), never the full transcript.
- Per-request opt-out: form field `cleanup=false` returns raw text.
- Env `TRANSCRIPT_CLEANUP=false` disables it server-wide.

### Code layout

```
text_cleanup/
  __init__.py      # clean(text) -> CleanResult(text, changes); never raises
  numbers.py       # number-word parsing + the rules above
  vocabulary.py    # file parsing, hot reload, phrase replacement
config/
  vocabulary.example.txt
tests/
  test_numbers.py
  test_vocabulary.py
scripts/
  review_cleanup.py  # runs clean() over a JSON list of transcripts, prints every change
```

`app.py` gains one call site after transcription. No new runtime dependencies
(stdlib `re` only); `pytest` is a dev-only dependency. `Dockerfile.cpu` copies
`text_cleanup/`; `docker-compose.yml` mounts `./config:/app/config:ro`.

### Testing

- Unit tests: every table row above, every "unchanged" case, IP rule edge
  cases (octet > 255, two dots only), vocabulary parsing, possessives,
  case-insensitivity, malformed lines, hot reload. Synthetic sentences only.
- Review run: `scripts/review_cleanup.py` over the private transcript archive,
  output reviewed by the owner before deploy. The archive never enters the repo.
- Deploy check: rebuild, one real dictation through the dictation app, then
  watch the change log for a day or two.

## Out of scope

- Abbreviating units, times ("three thirty pm" → "3:30 pm"), dates, currency.
- Spoken punctuation ("comma", "new line").
- A UI for editing the word list.
