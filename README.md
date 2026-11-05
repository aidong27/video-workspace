# Video Workspace

A self-hosted FastAPI workspace for extracting subtitles, video, and audio from public Bilibili and Douyin links, plus subtitles from locally uploaded video files.

## Processing flow

- Bilibili: official/manual and platform AI subtitles are checked first. In the default mode, videos without a usable platform track enter local faster-whisper ASR.
- Bilibili refusals: when Bilibili refuses this server (HTTP 412 or a risk-control API code), the task fails fast with `platform_blocked`, the UI warns before the next Bilibili submission, and further Bilibili requests are answered locally for `BILI_RISK_COOLDOWN_SECONDS`. The service does not try to get around the refusal; see [Workspace 1.1 upgrade](docs/workspace-1.1-upgrade.md) for the supported options.
- Douyin: short-link normalization, anonymous browser session, signed metadata request, platform caption when available, then the selected ASR backend.
- Upload: streamed file intake, real media validation, then local ASR or embedded/burned-in subtitle extraction. Uploaded video files are deleted after completion, failure, or queued cancellation.
- Local ASR: the baseline `auto` mode uses one on-demand `small`/int8 faster-whisper model with single heavy-task concurrency and a balanced decoding profile.
- Cloud ASR: explicit advanced modes use `qwen3-asr-flash-filetrans` for high accuracy or `paraformer-v2` for economy. Requests are made only by the server through separate provider adapters.
- Embedded subtitles: text tracks are extracted first, RapidOCR handles burned-in text, and audio falls back to the selected ASR backend only when OCR finds no stable captions.
- Direct media: Bilibili video up to 1080p, Douyin video, or MP3 audio. Binary results use owner-scoped temporary artifacts instead of JSON payloads and are deleted when the job expires.
- Access: invitation only. Every visitor enters an activation code at `/login`; nothing else (pages, APIs, scripts) is reachable without a session. See [Access and sharing](#access-and-sharing).
- Successful results are cached as normalized entries, so TXT, SRT, VTT, Markdown, and JSON conversions do not repeat transcription.
- Completed jobs can export another format directly from their owned result via
  `GET /api/jobs/{job_id}/result?format=srt`, without another queue submission or
  cloud call. Temporary browser disconnections retain the job and use bounded
  reconnect attempts. See [reliability upgrade notes](docs/reliability-upgrade.md).
- Work runs through a bounded queue so platform subtitles can finish while another job uses ASR. ASR and OCR share one heavy-work slot; cloud submissions, Chromium, downloads, and temporary media remain bounded for 4C/4G operation.
- Job state is stored in a small local SQLite database. Queued link jobs can resume after an unclean restart; any job that was already running returns an explicit interruption error so a cloud task is never submitted twice after a crash.
- Cache hits bypass the worker queue and are rendered in the requested format immediately. The web UI remembers an active job per account and reconnects after a refresh or short network interruption.

The Douyin adapter is pinned to an audited upstream commit. See `THIRD_PARTY_NOTICES.md`.

## Quick start

Requirements: Python 3.12 and FFmpeg. An HTTPS public origin and Aliyun Bailian project key are needed only when cloud ASR is enabled.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
playwright install chromium
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Issue the first (owner) activation code, then open `http://127.0.0.1:8000` and
enter it. Everyone else gets a code from the owner console at `/admin`:

```bash
python -m app.access issue --owner --label 站长 --username YOUR_ACCOUNT_NAME
```

Keep `.env` private and place the application behind an HTTPS reverse proxy
before sharing it.

## Job API

Log in once and keep the returned session cookie:

```bash
curl -c session.cookie -X POST https://HOST/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"FRIEND","password":"ACCOUNT_PASSWORD"}'
```

Create a job:

```bash
curl -b session.cookie -X POST https://HOST/api/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: UNIQUE-REQUEST-ID' \
  -d '{"input":"https://www.douyin.com/video/...","source":"auto","asr_mode":"auto","lang":"zh","format":"srt"}'
```

Poll or cancel it:

```bash
curl -b session.cookie https://HOST/api/jobs/JOB_ID
curl -b session.cookie -X DELETE https://HOST/api/jobs/JOB_ID
```

Job states are `queued`, `running`, `completed`, `failed`, and `cancelled`. Completed responses contain the same `content`, `filename`, `content_type`, and `metadata` fields as the compatibility endpoint `POST /api/extract`. Completed subtitle jobs also carry `segments` (`start`, `end`, `text`) for timed reading views.

Create a direct video or audio job:

```bash
curl -b session.cookie -X POST https://HOST/api/media-jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: UNIQUE-MEDIA-ID' \
  -d '{"input":"https://www.bilibili.com/video/...","media_type":"audio"}'
```

When the job completes, download the returned `download_url` with the same session cookie. Artifact URLs are opaque, account-scoped, size-limited, and expire automatically. `media_type` accepts `video` or `audio`; audio output is MP3.

## Runtime limits

```env
JOB_QUEUE_MAX_PENDING=4
JOB_WORKER_COUNT=2
BILI_RISK_COOLDOWN_SECONDS=300
BILI_WBI_KEY_TTL_SECONDS=1800
TRANSCRIPT_RETENTION_DAYS=1
JOB_RESULT_TTL_SECONDS=86400
JOB_STATE_DB_PATH=./var/cache/jobs.db
CLOUD_ASR_ENABLED=false
LOCAL_ASR_ENABLED=true
ASR_ENABLED=false
ASR_CONCURRENCY_LIMIT=1
ASR_QUEUE_WAIT_SECONDS=1800
DASHSCOPE_API_KEY=
DASHSCOPE_WORKSPACE_ID=
DASHSCOPE_BASE_URL=https://WORKSPACE.cn-beijing.maas.aliyuncs.com/api/v1
ASR_DEFAULT_MODEL=qwen3-asr-flash-filetrans
ASR_ECONOMY_MODEL=paraformer-v2
ASR_ALLOW_PAID=false
ASR_MONTHLY_FREE_SECONDS=36000
ASR_MONTHLY_HARD_LIMIT_SECONDS=32400
ASR_TOTAL_HARD_LIMIT_SECONDS=32400
ASR_DAILY_HARD_LIMIT_SECONDS=3600
ASR_USER_DAILY_HARD_LIMIT_SECONDS=1800
ASR_ECONOMY_FALLBACK_ENABLED=false
CLOUD_ASR_TIMEOUT_SECONDS=1800
CLOUD_ASR_HTTP_TIMEOUT_SECONDS=30
CLOUD_ASR_MAX_FILE_BYTES=268435456
CLOUD_ASR_AUDIO_DELIVERY=signed_url
CLOUD_ASR_UPLOAD_TIMEOUT_SECONDS=300
ASR_USAGE_DB_PATH=./var/cache/cloud-usage.db
AUDIO_SIGNING_SECRET=RANDOM_SECRET_AT_LEAST_32_BYTES
PUBLIC_BASE_URL=https://caption.example.com
TEMP_AUDIO_TTL_SECONDS=1800
ASR_DOWNLOAD_TIMEOUT_SECONDS=300
ASR_MAX_AUDIO_SECONDS=3600
ASR_AUDIO_QUALITY=best
ASR_AUDIO_FILTER=
BILI_MAX_DOWNLOAD_BYTES=1000000000
UPLOAD_MAX_BYTES=536870912
PUBLIC_UPLOAD_MAX_BYTES=536870912
UPLOAD_STAGING_MAX_BYTES=2147483648
MEDIA_MAX_BYTES=1000000000
MEDIA_MAX_DURATION_SECONDS=21600
MEDIA_STAGING_MAX_BYTES=8000000000
MEDIA_ARTIFACT_TTL_SECONDS=3600
MEDIA_FRAGMENT_CONCURRENCY=2
OCR_TIMEOUT_SECONDS=1800
OCR_SAMPLE_FPS=1.5
OCR_CROP_TOP_RATIO=0.45
OCR_MIN_CONFIDENCE=0.55
OCR_CPU_THREADS=1
OCR_MAX_FRAMES=12000
MIN_FREE_DISK_BYTES=2147483648
MIN_FREE_DISK_RATIO=0.05
PROCESS_ERROR_OUTPUT_BYTES=16384
RESULT_CACHE_TTL_SECONDS=86400
RESULT_CACHE_MAX_ITEMS=100
LEGACY_WAIT_TIMEOUT_SECONDS=1200
OMP_NUM_THREADS=3
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

`ASR_ALLOW_PAID=false` is the required default. These cloud limits are infrastructure safety controls, not account plans: all signed-in beta accounts may choose an advanced mode while the provider is available, but the server still refuses unbounded or potentially paid calls. It reserves predicted audio seconds in SQLite before submitting a provider task, enforces lifetime, global daily/monthly, and per-user daily limits atomically, and records provider-reported seconds after completion. Provider submission `POST` requests are never retried automatically, avoiding duplicate billable jobs when a response is lost. Prices are configurable estimates only; the Aliyun bill remains authoritative.

Cloud input is converted to a bounded mono MP3 only after media validation. `CLOUD_ASR_AUDIO_DELIVERY=signed_url` exposes it through a random HMAC-signed HTTPS URL for at most `TEMP_AUDIO_TTL_SECONDS`; the token is revoked immediately when the task ends and the task directory is removed.

`CLOUD_ASR_AUDIO_DELIVERY=aliyun_temp` uses Bailian's official temporary-file upload and submits the returned `oss://` URL. This is useful when an edge security policy blocks Bailian's Java downloader and is appropriate for the conservative, single-concurrency beta deployment. The local task file is still deleted immediately, while the provider-side temporary copy expires automatically within 48 hours. For higher-volume production, prefer a private OSS bucket or an explicit edge exception after a separate cost and security review.

`ASR_AUDIO_FILTER` is opt-in because filtering can damage quiet consonants. A conservative A/B candidate is `highpass=f=70,lowpass=f=7800,loudnorm=I=-20:TP=-2:LRA=11`; compare it against an empty filter on real source audio before enabling it in production.

Cloud ASR diagnostics keep the provider/model, task ID, reported seconds, latency, estimated standard-price cost, raw segments, and normalized segments on the service side. Browser responses use a strict metadata allowlist and expose only task-facing fields such as source, language, duration, cache status, and elapsed time. The web result view can switch between raw and organized transcript text without receiving provider task IDs or runtime diagnostics.

Uploads, media downloads, ASR normalization, and OCR preparation check both the absolute and proportional free-disk thresholds before starting. FFmpeg and ffprobe output is continuously drained but capped at `PROCESS_ERROR_OUTPUT_BYTES`, and timed-out processes are terminated, killed if necessary, and reaped.

Run exactly one Uvicorn application worker. The heavy-work semaphore and signed-audio registry are process-local; multiple Uvicorn workers would bypass the global concurrency limit and invalidate task-local signed audio state.

The administrator UI regression checks use Node.js's built-in test runner:
`node --test tests/admin_ui.test.cjs`. Node.js is only needed for development
checks, not for the production application.

Workspace browser regressions use Playwright as a development-only dependency:
`npm install --no-save --package-lock=false playwright`, then
`npx playwright install chromium webkit`. Run
`node --test tests/workspace_ui.test.cjs` and
`UI_BROWSER=webkit node --test tests/workspace_ui.test.cjs`.
All platform and recognition requests are mocked; these tests do not download
videos or invoke paid APIs. Set `UI_SCREENSHOT_DIR` to retain review screenshots.

Public `GET /api/health` returns only `{"status":"ok"}`. Signed-in clients use `GET /api/client-config` for a deliberately small capability document containing user-facing availability and upload constraints; neither endpoint returns queue totals, process or disk metrics, model names, provider usage, paths, API keys, workspace IDs, Cookie values, users, or environment variables. Reading either endpoint never invokes a provider or initializes a local model.

Without a session only `/login`, its own assets, `/robots.txt`, `/api/health` and
`POST /api/auth/activate` respond; everything else redirects to the gate, returns
401, or 404 for static files. Assets for signed-in pages are sent as
`Cache-Control: private` so a CDN never serves them to visitors without a session.
Temporary media responses remain `private, no-store`; a CDN must not cache or
publicly proxy artifact downloads.

The local faster-whisper and OCR implementation is the default baseline. On a 4C/4G host, keep `ASR_CONCURRENCY_LIMIT=1`, use the same `small`/int8 model key for all quality profiles, and leave `ASR_PREWARM=false` so the idle web service does not preload the model. The default `balanced` profile uses beam 3 with VAD and cross-window context; `accurate` keeps beam 5 for explicit API callers and OCR fallback. Automatic second-pass correction is limited by `ASR_CONTEXT_RETRY_MAX_AUDIO_SECONDS` so a difficult long video does not silently double its processing time. Model loading checks the local cache before attempting a network request; once the production cache is seeded, set `ASR_MODEL_DOWNLOAD_ENABLED=false` to fail quickly instead of waiting on an unavailable model host. With `ASR_WORKER_EXIT_ON_IDLE=true`, `ASR_MODEL_IDLE_SECONDS=900` exits the entire ASR child after 15 idle minutes and the next task rebuilds it automatically. Set the idle value to `0` to keep it resident, or set the exit flag to `false` to restore the older model-unload-only behavior.

Local ASR avoids re-encoding validated mono 16 kHz PCM WAV input when no audio
filter is configured. It rejects overlong decoded audio and skips model startup
only for exact digital silence, not quiet speech. Conversion uses bounded decoder
and filter threads. Recognition progress comes from processed segment timestamps
and is throttled to at most one update per second; progress delivery cannot block
inference. Optional quality correction starts only with enough remaining task
time and retains the first result if the second pass raises an error. The parent
process still enforces the hard timeout; an OOM kill cannot recover an in-memory
partial result. Existing result caches remain compatible with these changes.

## Douyin runtime

```env
DOUYIN_ENABLED=true
DOUYIN_COOKIE_STATE_PATH=./var/douyin/cookies.json
DOUYIN_COOKIE_TTL_SECONDS=1800
DOUYIN_DETAIL_CACHE_TTL_SECONDS=600
DOUYIN_BROWSER_WAIT_MS=6000
DOUYIN_BROWSER_LOCK_TIMEOUT_SECONDS=90
DOUYIN_MAX_DOWNLOAD_BYTES=1000000000
PLAYWRIGHT_BROWSERS_PATH=./var/playwright
```

The service creates a fresh anonymous Douyin browser session when its cached cookies expire. Cookie values stay in the service-owned `var` directory and are never returned by the API.

## Access and sharing

The site is invitation only. The owner hands each person an activation code: 20
Crockford base32 characters (100 random bits), shown exactly once and stored only
as an HMAC under a server-side pepper (`var/auth/access-pepper`, or
`ACCESS_CODE_PEPPER`). Entering a code at `/login` creates a session bound to that
code, kept in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie with the `__Host-`
prefix. Revoking, resetting, disabling, or expiring a code ends every session it
opened on the next request.

The gate counts failed attempts per client address: 5 failures within 15 minutes
lock the address for 15 minutes, 10 within a day for an hour, 20 for a day. A
successful entry clears the address. Add an edge rate limit for
`/api/auth/activate` as well.

The owner console at `/admin` issues, resets, edits, disables, and deletes codes,
shows each person's devices and usage, signs devices out, lists recent gate events
with locked addresses (and can unlock them), shows runtime diagnostics, and holds
the Bilibili login. Limits for members, which never apply to the owner:

```env
ACCESS_MAX_DEVICES=3          # signed-in browsers per person; the oldest is signed out
ACCESS_OWNER_MAX_DEVICES=10
MEMBER_DAILY_JOB_LIMIT=30     # tasks per China-time day; 0 = unlimited
MEMBER_MAX_ACTIVE_JOBS=2      # queued + running tasks per person
```

Codes can also be managed from the command line on the server (run as the service
user, with the service's `AUTH_DB_PATH`):

```bash
python -m app.access issue --label 小王 --days 90
python -m app.access list
```

Keep hostnames, certificates, cloud configuration, and operational reports in a
separate private deployment repository.

## Bilibili login state

Bilibili refuses anonymous API requests from many datacenter addresses (HTTP 412).
The owner can sign a Bilibili account in from the console (`/admin` → B站账号) by
scanning a QR code with the Bilibili app. The resulting cookie is stored in
`BILI_COOKIE_PATH` (mode 600, service-owned) and is then used for every Bilibili
request: subtitles, page lists, and media downloads. Signed-in API calls are
spaced by `BILI_MIN_INTERVAL_SECONDS` and run one job at a time. The console shows
which account is in use and can sign it out, which also ends the session at
Bilibili. Cookie values are never returned by any API.

Keep `.env`, the authentication database and its pepper, activation codes, Bilibili and Douyin cookie state, tokens, and authorization headers out of logs and reports.

## License

Released under the [MIT License](LICENSE). Third-party components retain their
own licenses; see `THIRD_PARTY_NOTICES.md`.
