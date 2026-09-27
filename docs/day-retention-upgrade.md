# One-Day Retention and Workspace Workflow

Baseline: `68bd55bdabaa40810df0ce7f8be90b992b96a553`.
Branch: `codex/day-retention-workspace`.

## Retention Contract

- `TRANSCRIPT_RETENTION_DAYS=1` gives subtitle job results a maximum lifetime of
  24 hours after completion. Failed/cancelled records use their last update.
- `RESULT_CACHE_TTL_SECONDS=86400` is capped by the transcript retention setting.
  Cache expiry is measured from the stored creation timestamp. Read access only
  affects capacity-based LRU eviction; it cannot extend TTL.
- `JOB_RESULT_TTL_SECONDS=86400` remains the fallback for non-subtitle records.
  Media jobs expire no later than their artifact. Default registered media TTL
  remains 3600 seconds and guest media TTL 1800 seconds.
- Request-time checks reject expired results immediately. A single maintenance
  thread checks jobs, caches and artifacts every 60 seconds even without traffic.
  Filesystem cleanup runs on a best-effort basis and retries on later cycles;
  errors are logged by exception type without paths or credentials.
- Running/queued jobs are not removed by result retention. Existing capacity and
  disk guards remain: completed records or cache entries may be evicted sooner
  when limits are reached. This is a maximum retention period, not guaranteed
  permanent storage or a forensic erasure promise.
- Downloaded user copies and external backups are outside this online retention
  policy. No backup, model, credential, account or billing data is deleted here.

## Workflow and Compatibility

`GET /api/jobs?limit=20` requires a registered session and returns only that
user's summaries, with `Cache-Control: private, no-store`. It accepts limits
from 1 to 50. Each terminal job has an additive `expires_at` Unix timestamp.
Existing submission, polling, export and guest media APIs remain compatible.

Recent tasks now come from the existing SQLite-backed JobManager, not locally
stored request parameters. Opening a row performs GET only. Upload results are
also discoverable, and completed records survive an application restart within
the existing restore/count limits. Failed history refreshes can be retried;
expired rows cannot overwrite a result already open in the workspace.

The browser clears expired output and checks expiry before copying, downloading
or changing formats. It removes obsolete local history keys and does not persist
transcript bodies in localStorage. Active-job recovery retains the existing
ownership and not-found checks.

The desktop layout has a wider history rail and a compact composer. Link/upload
controls remain paired, while language/default format move into advanced
settings with a visible value summary. Mobile has a separate history dialog.
Cloud consent, local ASR, platform captions, OCR and guest media are unchanged.

## Validation

The baseline suite passed 247 Python tests. Added regressions cover absolute
expiry, read access, media TTL compatibility, malformed timestamps/results,
database cleanup beyond the restore window, owner isolation, list/export expiry,
independent maintenance and browser expiry/recovery. Browser tests exercise
Chromium and WebKit, including 320/390px layouts and a GET-only history workflow.
Tests use mocks and do not invoke paid cloud ASR or real platform downloads.

Local verification: 260 Python tests passed (five pre-existing deprecation
warnings), plus 40 Chromium and 40 WebKit checks. Python compilation, JavaScript
syntax and Git whitespace checks passed. The repository has no separate lint
configuration; no formatter or production dependency was introduced.

Physical iPhone testing, real Bilibili/Douyin availability and long-duration
memory/throughput measurements remain separate checks. No ASR accuracy or
end-to-end speed improvement is claimed by this change.

## Upgrade and Rollback

Existing environment values override new defaults. After a verified backup, set
`TRANSCRIPT_RETENTION_DAYS=1`, `RESULT_CACHE_TTL_SECONDS=86400` and
`JOB_RESULT_TTL_SECONDS=86400` in the existing private environment file. Preserve
all other settings and existing short media TTLs. Restart only this application,
with the existing single Uvicorn application process.

The shorter policy applies to existing online results immediately. Expired
records are pruned at startup and by subsequent maintenance. There is no schema
migration, dependency upgrade, cache format change or model change.

Rollback restores the pre-upgrade code and the three prior environment values,
then restarts the application. The additional JSON fields are backward
compatible. Rolling back code cannot revive already expired records; recovering
those requires the verified pre-upgrade backup and a deliberate data restore.
Do not overwrite live user data as part of a routine code rollback.
