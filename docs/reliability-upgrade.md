# Reliability and Result Workflow Upgrade

## Scope

Baseline: `97fe3ce9cadb1bfc474c9ae5fe33d40f051882eb`.
Branch: `codex/reliability-workspace-upgrade`.

The audit followed job submission, ownership, persistence, cancellation, process
cleanup, OCR frames, result caching, and browser recovery/export. Existing local
ASR profiles, cloud consent and cost protection, guest media access, and all
platform adapters are retained. No model, dependency, database schema, billing,
DNS, firewall, or unrelated service changes are required.

## Confirmed Issues and Fixes

- SQLite's connection context commits/rolls back but does not close the
  connection. Auth, jobs and usage now explicitly close on success and failure,
  preserving each module's transaction and autocommit settings.
- Cancelled IDs could accumulate in the transport queue behind a long job.
  Queue IDs, cancellation and dispatch now share one lock and a condition;
  cancelled IDs are removed immediately and shutdown wakes idle workers.
  FIFO position uses the actual queue, not wall-clock ordering of records.
- An exception other than timeout, or output-capture thread startup failure,
  could leave a subprocess alive. Managed commands now stop/reap it before
  closing the output pipes on these paths too.
- Non-UTF-8 cache files and non-finite timestamps could break result rendering.
  Such entries now cause cache invalidation and recomputation, not partial output.
- OCR now reuses results only for byte-identical consecutive JPEG frames while
  preserving every timeline sample. Failed recognition is not reused. FFmpeg
  decoding, filtering and encoding threads are bounded by the OCR setting (up
  to four); a nonzero decode exit cannot return a successful partial transcript.
- Temporary polling failures (network/timeout, 408, 429, 5xx, invalid payload)
  retain the owned job ID. Polls have a 12-second timeout and bounded backoff;
  after six failures automatic polling pauses. Reconnect performs GET only.
  404/410/expired guest sessions clear obsolete local state.
- Manual retry of an uncertain submission retains its Idempotency-Key.
  Health checks cannot overlap indefinitely or switch an active media operation
  to subtitles after a transient outage. Hidden tabs poll less frequently.
- A stale Bilibili part lookup can no longer erase the latest video's choices.
- Changing a completed result's format no longer creates another task.
  Search is debounced, and narrow-screen result tools keep stable dimensions.

## Result Export API

`GET /api/jobs/{job_id}/result?format=txt|srt|vtt|json|markdown|md`

This read-only endpoint requires login and the original job owner. Completed
jobs store private normalized entries alongside the existing rendered result.
Export does not touch the recognition queue, source media, provider, or cache.
Raw and organized versions are both supported. Responses use `private, no-store`
and the same public metadata filter as ordinary results. Private entry fields,
model/runtime details and provider task IDs are not sent to the browser.

Jobs created by older versions may lack normalized entries. They return
`410 result_unavailable`; the browser retains its current preview instead of
silently starting a potentially paid transcription. Incomplete tasks return
`409 job_not_ready`. Other users receive the existing not-found response.

## Verification

- Baseline Python suite: 231 passed, five existing deprecation warnings.
- Upgraded Python suite: 247 passed, the same five warnings.
- Chromium: 26 workspace interaction tests plus four admin UI unit tests pass.
- WebKit is also exercised with the same suite, including 320/390px layouts.
- Python compilation, JavaScript syntax, and diff whitespace checks pass.
- Automated tests use mocks/controlled media, not live platform downloads,
  cloud billing or model downloads. Regression coverage includes transactions,
  queue churn, concurrent workers, process interruption, OCR reuse/failure,
  corrupted caches, export ownership, all six formats, raw results, persistence,
  polling recovery, refresh, guest expiry, idempotency and stale part responses.

Browser WebKit checks are not a substitute for physical iPhone testing. Actual
Bilibili/Douyin availability, long-video throughput and sustained memory use
still require production observation; this upgrade does not claim a new ASR
accuracy score or a measured end-to-end transcription speedup.

## Resources and Rollback

ASR/OCR concurrency, resident model policy and cloud limits are unchanged.
Cancelled queue storage now follows live pending work; database connections
are not retained for garbage collection. Repeated-frame OCR saves inference
only on exactly identical frames. Each completed subtitle job stores one extra
normalized-entry list, bounded by existing job retention/count limits.

Before deployment, verify production code hashes, idle queue, free disk space,
and a complete checksum-verified backup. Preserve the existing environment and
service. Deploy code atomically per file with automatic rollback on failed
smoke/health checks. Restart only this application's service.

No schema migration or cache version bump is required. Rollback restores code
and removes the newly added database helper; do not replace a live database
just to roll back code. Extra JSON fields in job records are backward compatible.
Private backup paths, host identifiers and runtime reports are intentionally
excluded from this public document.
