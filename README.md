# Video Workspace

A self-hosted FastAPI workspace for extracting subtitles, video, and audio from public Bilibili and Douyin links, plus subtitles from locally uploaded video files.

## Processing flow

- Bilibili: official/manual and platform AI subtitles are checked first. In the default mode, videos without a usable platform track enter local faster-whisper ASR.
- Douyin: short-link normalization, anonymous browser session, signed metadata request, platform caption when available, then the selected ASR backend.
- Upload: streamed file intake, real media validation, then local ASR or embedded/burned-in subtitle extraction. Uploaded video files are deleted after completion, failure, or queued cancellation.
- Local ASR: the baseline `auto` mode uses one on-demand `small`/int8 faster-whisper model with single heavy-task concurrency.
- Cloud ASR: explicit advanced modes use `qwen3-asr-flash-filetrans` for high accuracy or `paraformer-v2` for economy. Requests are made only by the server through separate provider adapters.
- Embedded subtitles: text tracks are extracted first, RapidOCR handles burned-in text, and audio falls back to the selected ASR backend only when OCR finds no stable captions.
- Direct media: Bilibili video up to 1080p, Douyin video, or MP3 audio. Binary results use owner-scoped temporary artifacts instead of JSON payloads and are deleted when the job expires.
- Guest media: optional signed guest sessions can expose only direct video/audio extraction without opening subtitle, upload, Cookie, or cloud-ASR access. Guest outputs use lower limits and a shorter retention window.
- Successful results are cached as normalized entries, so TXT, SRT, VTT, Markdown, and JSON conversions do not repeat transcription.
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

Open `http://127.0.0.1:8000`. Before sharing the service, set a non-empty
`INVITE_CODE_HASH`, keep `.env` private, and place the application behind an
HTTPS reverse proxy.

Guest video/audio extraction is disabled by default. To enable it, set
`GUEST_MEDIA_ENABLED=true` and generate a unique `GUEST_MEDIA_SECRET` with at
least 32 bytes. The browser receives only a signed, HttpOnly owner cookie; it
does not receive the secret.

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

Job states are `queued`, `running`, `completed`, `failed`, and `cancelled`. Completed responses contain the same `content`, `filename`, `content_type`, and `metadata` fields as the compatibility endpoint `POST /api/extract`.

Create a direct video or audio job:

```bash
curl -b session.cookie -X POST https://HOST/api/media-jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: UNIQUE-MEDIA-ID' \
  -d '{"input":"https://www.bilibili.com/video/...","media_type":"audio"}'
```

When the job completes, download the returned `download_url` with the same session cookie. Artifact URLs are opaque, account-scoped, size-limited, and expire automatically. `media_type` accepts `video` or `audio`; audio output is MP3.

When guest media is enabled, the same endpoint can be called without an account.
The successful response sets a short-lived guest cookie that must be sent while
polling and downloading:

```bash
curl -c guest.cookie -X POST https://HOST/api/media-jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: UNIQUE-GUEST-MEDIA-ID' \
  -d '{"input":"https://www.bilibili.com/video/...","media_type":"video"}'
```

Guest requests never use the server-side Bilibili Cookie, even if a client sends
`use_cookie=true`.

`POST /api/extract` and `POST /api/download` remain available for synchronous clients, but they now use the same bounded queue. The old side-effecting `GET /api/download` endpoint returns `410 Gone`. Reusing an `Idempotency-Key` for the same request returns the original job instead of starting duplicate work after a network retry; using it for a different request returns `409 Conflict`.

Upload a local video as the raw request body:

```bash
curl -b session.cookie -X POST \
  'https://HOST/api/upload-jobs?filename=meeting.mp4&format=srt&lang=zh&asr_mode=high_accuracy&cloud_consent=true' \
  -H 'Content-Type: video/mp4' \
  -H 'Idempotency-Key: UNIQUE-UPLOAD-ID' \
  --data-binary '@meeting.mp4'
```

The upload endpoint accepts common video containers up to `UPLOAD_MAX_BYTES`. `PUBLIC_UPLOAD_MAX_BYTES` can expose a lower browser-side limit when a reverse proxy or CDN rejects smaller requests (for example, use a value below the edge limit); the API's own hard limit remains `UPLOAD_MAX_BYTES`. ASR requires an audio stream; embedded-subtitle extraction also accepts silent video. The web client sends upload hotwords through the percent-encoded `X-ASR-Hotwords` header so they are not placed in the request URL. The original video is temporary; normalized subtitle entries can remain in the result cache for `RESULT_CACHE_TTL_SECONDS`, allowing the same video to be re-uploaded in another output format without repeating recognition.

Request parameters:

- `source`: `auto`, `official`, or `asr`
- `format`: `txt`, `srt`, `vtt`, `markdown`, or `json`
- `lang`: ASR language hint; defaults to `zh`, while an explicit null/empty value enables automatic detection
- `hotwords`: optional names, terms, or abbreviations for the optional local-ASR compatibility path; limited to 300 characters and represented by a hash in cache metadata
- `asr_mode`: `auto` uses the local baseline when available; `high_accuracy` and `economy` explicitly select the cloud Qwen and Paraformer modes
- `cloud_consent`: must be `true` for either explicit cloud mode; the API enforces this independently of the browser confirmation dialog
- `quality`: retained for backward compatibility with local ASR clients; defaults to `accurate`
- `embedded_subtitles`: inspect an embedded text track or OCR burned-in video text; implies accurate processing
- `allow_platform_ai`: use platform-generated captions before the selected ASR backend; defaults to `true`
- `force_refresh`: bypass the result cache
- `use_cookie`: allow the optional server-side Bilibili login state

## Runtime limits

```env
JOB_QUEUE_MAX_PENDING=4
JOB_WORKER_COUNT=2
JOB_RESULT_TTL_SECONDS=3600
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
GUEST_MEDIA_ENABLED=false
GUEST_MEDIA_SECRET=
GUEST_SESSION_TTL_SECONDS=86400
GUEST_MEDIA_MAX_BYTES=262144000
GUEST_MEDIA_MAX_DURATION_SECONDS=1800
GUEST_MEDIA_MAX_VIDEO_HEIGHT=720
GUEST_MEDIA_AUDIO_BITRATE_KBPS=160
GUEST_MEDIA_ARTIFACT_TTL_SECONDS=1800
GUEST_MEDIA_MAX_ACTIVE=1
GUEST_MEDIA_SESSION_HOURLY_LIMIT=6
GUEST_MEDIA_GLOBAL_HOURLY_LIMIT=24
OCR_TIMEOUT_SECONDS=1800
OCR_SAMPLE_FPS=1.5
OCR_CROP_TOP_RATIO=0.45
OCR_MIN_CONFIDENCE=0.55
OCR_CPU_THREADS=1
OCR_MAX_FRAMES=12000
MIN_FREE_DISK_BYTES=2147483648
MIN_FREE_DISK_RATIO=0.05
PROCESS_ERROR_OUTPUT_BYTES=16384
RESULT_CACHE_TTL_SECONDS=604800
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

Public `GET /api/health` returns only `{"status":"ok"}`. Signed-in clients use `GET /api/client-config` for a deliberately small capability document containing user-facing availability and upload constraints; neither endpoint returns queue totals, process or disk metrics, model names, provider usage, paths, API keys, workspace IDs, Cookie values, users, or environment variables. Reading either endpoint never invokes a provider or initializes a local model.

Unauthenticated clients use `GET /api/public-config`, which exposes only guest
media availability and public limits. Temporary media responses remain
`private, no-store`. A CDN may cache the versioned CSS and JavaScript files, but
must not cache or publicly proxy artifact downloads; this keeps owner isolation
intact and avoids treating a general CDN as a video-delivery service.

The local faster-whisper and OCR implementation is the default baseline. On a 4C/4G host, keep `ASR_CONCURRENCY_LIMIT=1`, use the same `small`/int8 model key for both quality profiles, and leave `ASR_PREWARM=false` so the idle web service does not preload the model. Model loading checks the local cache before attempting a network request; once the production cache is seeded, set `ASR_MODEL_DOWNLOAD_ENABLED=false` to fail quickly instead of waiting on an unavailable model host. `ASR_MODEL_IDLE_SECONDS=900` releases the model after 15 idle minutes while retaining the worker process; set it to `0` only when lower cold-start latency matters more than idle memory.

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

## Sharing and HTTPS

Friends can extract video or audio without an account when guest media is enabled.
Subtitle extraction, uploads, cloud enhancement, and optional Bilibili Cookie use
still require an account. Friends register once with a shared permanent invite
code, choose their own username and password, and then use the normal login page.
Passwords are hashed with `scrypt`; session tokens and the invite code are stored
only as hashes. Jobs are scoped to the account or signed guest session that
submitted them. Signed-in users can change their password, which revokes all older
sessions, or explicitly log out every device from the account menu.

Generate the invite hash without placing the plaintext code in `.env`:

```bash
python3 -c 'import getpass,hashlib; print(hashlib.sha256(getpass.getpass("Invite code: ").strip().encode()).hexdigest())'
```

Set the result as `INVITE_CODE_HASH`. The relevant settings are:

```env
AUTH_DB_PATH=/opt/bili-subtitle-tool/var/auth/auth.db
AUTH_SESSION_TTL_DAYS=30
AUTH_MAX_USERS=50
AUTH_MAX_SESSIONS_PER_USER=8
AUTH_COOKIE_SECURE=true
INVITE_CODE_HASH=SHA256_HEX_ONLY
```

For an internet-facing deployment, add edge rate limits to login and registration,
set `AUTH_COOKIE_SECURE=true`, and terminate TLS at a maintained reverse proxy.
Keep hostnames, certificates, cloud configuration, and operational reports in a
separate private deployment repository.

Email password recovery and third-party login are intentionally not faked by the
local account database. See `docs/account-roadmap.md` for the external services
and domain verification required to add them safely.

## Bilibili login state

Bilibili Cookie use remains optional and disabled by default. Configure it only
through a private `.env` or a service-owned Cookie file. Do not use a primary
Bilibili account for a long-lived server Cookie, and ensure the Cookie file is
readable only by the service account.

Keep `.env`, the authentication database, invite codes, Douyin cookie state, passwords, tokens, and authorization headers out of logs and reports.

## License

Released under the [MIT License](LICENSE). Third-party components retain their
own licenses; see `THIRD_PARTY_NOTICES.md`.
