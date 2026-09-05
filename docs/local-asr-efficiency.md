# Local ASR efficiency update

## Scope

Keep the existing local small/int8 model, balanced decoding defaults, single
ASR/OCR heavy-task slot and optional cloud enhancement. No dependency, billing,
authentication, UI or production environment-variable changes are required.
Existing caches remain usable, including cloud results.

## Changes

- Validated mono 16 kHz, 16-bit PCM WAV can use a separate hard link instead of
  FFmpeg when no filter is configured. Cross-filesystem copying reserves disk
  space and removes partial output. Removing the source does not remove the
  normalized input. Stereo, malformed and truncated WAV do not use this shortcut.
- Conversion limits decoder/filter threads and stops at the local duration cap
  plus one second, rejecting and cleaning overlong output before inference.
- Only exact all-zero PCM bypasses model startup. Quiet nonzero audio still
  reaches speech recognition. Input is checked in bounded chunks.
- Segment timestamps drive throttled recognition progress through the existing
  worker result queue. Stale task messages and malformed progress are ignored;
  a full progress queue drops updates instead of blocking inference.
- Optional context correction needs enough remaining task time. A second-pass
  exception or segment-boundary timeout preserves the first successful result.
  The generator is closed and logs contain only an exception class, not input.
- Worker request submission has a bounded wait and resets a nonresponsive child.

## Verification

Baseline: 216 Python tests passed. After this update: 231 Python tests passed,
including 15 additional regression tests in `tests/test_local_asr_efficiency.py`.
Python compilation and the 4 administrator UI tests also passed. Existing
FastAPI/Starlette deprecation warnings remain; dependencies were not changed.

Tests use generated minimal WAV fixtures and mocked inference, not cloud calls,
real platform requests or model downloads. Production verification is recorded
separately in private deployment evidence; this document does not imply that
mocked tests establish recognition accuracy or long-video throughput.

## Limits

This does not accelerate the model's native decoding algorithm. The shortcut
only helps already-normalized WAV, not typical compressed platform audio.
Progress advances when decoded segments become available, not continuously
during model loading or native inference. Parent hard timeouts and OOM kills
cannot recover an in-memory partial result. Long speech, music, dialects and
noisy recordings still require representative quality/throughput testing.

## Rollback

There is no database migration or configuration change. Restore the previous
`app/main.py` from the verified pre-upgrade backup and restart the single
application service. Keep the private environment file, models, databases and
existing cached results intact. Production backup and restart safety gates in
`docs/production-upgrade-runbook.md` still apply.
