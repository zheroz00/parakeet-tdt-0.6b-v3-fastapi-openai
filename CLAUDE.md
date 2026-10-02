# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An OpenAI-compatible speech-to-text server (`POST /v1/audio/transcriptions`) wrapping NVIDIA Parakeet TDT 0.6B via the `onnx-asr` library and ONNX Runtime (int8 quantized). Despite the repo name, it is **Flask served by waitress, not FastAPI**. Nearly all logic lives in `app.py`; `templates/index.html` is the drag-and-drop web UI and `templates/swagger.html` renders the hand-written spec from `/openapi.json`.

## Commands

```bash
# Docker (normal way to run). CPU is the default service.
docker compose up -d --build parakeet-cpu
# GPU is behind a compose profile and shares port 5092, so stop parakeet-cpu first
docker compose --profile gpu up -d --build parakeet-gpu
docker logs -f parakeet-cpu

# Local (needs ffmpeg/ffprobe on PATH). Run from the repo root: see "cwd matters" below.
pip install -r requirements.txt
python app.py            # serves on 0.0.0.0:5092, also tries to open a browser tab

# Smoke test against a running server
curl http://localhost:5092/health
curl -F file=@audio.mp3 -F response_format=text http://localhost:5092/v1/audio/transcriptions
```

There is no test suite, linter, or build step. `test_onnx_asr.py`, `test_onnx_config.py` and `inspect_model.py` are ad-hoc diagnostic scripts (print available ONNX providers / session options / model internals), not tests. `benchmark.py` POSTs files to a running server and writes to `./benchmark_results/`; its `TEST_AUDIO_DIR` is a hardcoded path that must be edited before use.

## Configuration

- Env vars: `INFERENCE_DEVICE` (`cpu` default, or `gpu`) and `PARAKEET_MODEL` (any onnx-asr hub name; default `nemo-parakeet-tdt-0.6b-v3` multilingual, `nemo-parakeet-tdt-0.6b-v2` is English-only and more accurate on English). `docker-compose.yml` currently pins v2.
- Everything else is a module-level constant at the top of `app.py`: waitress `threads`, `CHUNK_MINUTE`, and the silence-detection tuning (`SILENCE_*`, `MIN_SPLIT_GAP`). The ONNX CPU `intra_op_num_threads = 8` is a separate hardcoded value in the model-loading block.
- `Dockerfile.gpu` does **not** use `requirements.txt`; it pip-installs its own list (swapping `onnxruntime` for `onnxruntime-gpu`). Dependency changes must be made in both places.
- CPU is the deliberate default: the int8 export falls back to CPU for most of the encoder even with CUDA, so GPU gains are small (see comments in `docker-compose.yml`).

## Architecture notes that span the file

- **Model loads at import time.** The `try:` block near the top of `app.py` builds the ONNX session and calls `sys.exit()` on failure, so importing `app` anywhere loads the full model. `sys.stdout` is redirected to `sys.stderr` at startup so all `print` logging goes to stderr.
- **cwd matters.** `ROOT_DIR = os.getcwd()` and `HF_HOME`/`HF_HUB_CACHE` are overwritten to `<cwd>/models`, overriding any env value. Model downloads land there (a Docker volume at `/app/models` in containers). `temp_uploads/` is also cwd-relative.
- **Request pipeline** (`transcribe_audio`): save upload to `temp_uploads/` → ffmpeg converts to 16 kHz mono WAV → if longer than `CHUNK_MINUTE` (90 s), run ffmpeg `silencedetect` and `find_optimal_split_points` picks a split near each 90 s target inside `SILENCE_SEARCH_WINDOW`, falling back to the raw target time → ffmpeg cuts chunk WAVs → `asr_model.recognize()` runs on each chunk **sequentially** → timestamps are offset by the *planned* chunk durations (not re-probed) → output formatted → all temp files deleted in `finally`.
- **One segment per chunk.** Each chunk produces exactly one segment, so SRT/VTT cues are up to ~90 s long, not sentence-level. "Words" are actually onnx-asr subword tokens with their timestamps.
- **`model` form field is ignored** except the legacy value `parakeet_srt_words`, which returns SRT followed by the literal separator `----..----` and a JSON array of token timings. `verbose_json` hardcodes `"language": "english"` and zeroes the Whisper-specific fields.
- **Progress tracking** is an in-memory `progress_tracker` dict keyed by job UUID, never pruned. The web UI polls `/status` (returns the first job still `processing`) and `/metrics` (psutil CPU/RAM) while a request is in flight; `/progress/<job_id>` is also available, and the default JSON response returns the id in `X-Job-ID`.
