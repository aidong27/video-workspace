# Video Workspace

A private, shareable FastAPI workspace for extracting subtitles, video, and audio from public Bilibili and Douyin links, plus subtitles from locally uploaded video files.

## Processing flow

- Bilibili: official/manual and platform AI subtitles first. Only videos without a usable platform track enter cloud ASR.
- Douyin: short-link normalization, anonymous browser session, signed metadata request, platform caption when available, then cloud ASR fallback.
- Upload: streamed file intake, real media validation, then cloud ASR or embedded/burned-in subtitle extraction. Uploaded video files are deleted after completion, failure, or queued cancellation.
- Cloud ASR: `qwen3-asr-flash-filetrans` is the high-accuracy default and `paraformer-v2` is the explicit economy mode. Requests are made only by the server through separate provider adapters.
- Embedded subtitles: text tracks are extracted first, RapidOCR handles burned-in text, and audio falls back to the selected cloud model only when OCR finds no stable captions.
- Direct media: Bilibili video up to 1080p, Douyin video, or MP3 audio. Binary results use owner-scoped temporary artifacts instead of JSON payloads and are deleted when the job expires.
- Successful results are cached as normalized entries, so TXT, SRT, VTT, Markdown, and JSON conversions do not repeat transcription.
- Work runs through a bounded queue so platform subtitles can finish while another job uses ASR. ASR and OCR share one heavy-work slot; cloud submissions, Chromium, downloads, and temporary media remain bounded for 4C/4G operation.
- Job state is stored in a small local SQLite database. Queued link jobs can resume after an unclean restart; any job that was already running returns an explicit interruption error so a cloud task is never submitted twice after a crash.
- Cache hits bypass the worker queue and are rendered in the requested format immediately. The web UI remembers an active job per account and reconnects after a refresh or short network interruption.

The Douyin adapter is pinned to an audited upstream commit. See `THIRD_PARTY_NOTICES.md`.

## Quick start

Requirements: Python 3.12, FFmpeg, an HTTPS public origin, and an Aliyun Bailian project key when cloud ASR is enabled.

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

`POST /api/extract` and `POST /api/download` remain available for synchronous clients, but they now use the same bounded queue. The old side-effecting `GET /api/download` endpoint returns `410 Gone`. Reusing an `Idempotency-Key` for the same request returns the original job instead of starting duplicate work after a network retry; using it for a different request returns `409 Conflict`.

Upload a local video as the raw request body:

```bash
curl -b session.cookie -X POST \
  'https://HOST/api/upload-jobs?filename=meeting.mp4&format=srt&lang=zh&asr_mode=high_accuracy' \
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
- `asr_mode`: `auto`, `high_accuracy`, or `economy`; defaults to `auto`
- `quality`: retained for backward compatibility with local ASR clients; defaults to `accurate`
- `embedded_subtitles`: inspect an embedded text track or OCR burned-in video text; implies accurate processing
- `allow_platform_ai`: use platform-generated captions before cloud ASR; defaults to `true`
- `force_refresh`: bypass the result cache
- `use_cookie`: allow the optional server-side Bilibili login state

## Runtime limits

```env
JOB_QUEUE_MAX_PENDING=4
JOB_WORKER_COUNT=2
JOB_RESULT_TTL_SECONDS=3600
JOB_STATE_DB_PATH=./var/cache/jobs.db
CLOUD_ASR_ENABLED=true
LOCAL_ASR_ENABLED=false
ASR_ENABLED=false
ASR_JOB_CONCURRENCY=1
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
RESULT_CACHE_TTL_SECONDS=604800
RESULT_CACHE_MAX_ITEMS=100
LEGACY_WAIT_TIMEOUT_SECONDS=1200
OMP_NUM_THREADS=3
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

`ASR_ALLOW_PAID=false` is the required default. The server refuses to enable cloud ASR unless the free allowance and a lifetime hard limit are explicitly configured. It reserves predicted audio seconds in SQLite before submitting a provider task, enforces lifetime, global daily/monthly, and per-user daily limits atomically, and records provider-reported seconds after completion. Provider submission `POST` requests are never retried automatically, avoiding duplicate billable jobs when a response is lost. Prices are configurable estimates only; the Aliyun bill remains authoritative.

Cloud input is converted to a bounded mono MP3 only after media validation. A random HMAC-signed HTTPS URL exposes that file to the provider for at most `TEMP_AUDIO_TTL_SECONDS`; the token is revoked immediately when the task ends and the task directory is removed.

`ASR_AUDIO_FILTER` is opt-in because filtering can damage quiet consonants. A conservative A/B candidate is `highpass=f=70,lowpass=f=7800,loudnorm=I=-20:TP=-2:LRA=11`; compare it against an empty filter on real source audio before enabling it in production.

Cloud ASR metadata includes the actual provider/model, provider task ID, reported seconds, latency, estimated standard-price cost, raw segments, and normalized segments. The web result view can switch between raw and organized output.

Uploads, media downloads, ASR normalization, and OCR preparation check both the absolute and proportional free-disk thresholds before starting. FFmpeg and ffprobe output is continuously drained but capped at `PROCESS_ERROR_OUTPUT_BYTES`, and timed-out processes are terminated, killed if necessary, and reaped.

Run exactly one Uvicorn application worker. The heavy-work semaphore and signed-audio registry are process-local; multiple Uvicorn workers would bypass the global concurrency limit and invalidate task-local signed audio state.

`GET /api/health` reports queue, FFmpeg/ffprobe, cloud-provider readiness, local quota totals, process memory/swap, and disk-threshold status without returning paths, API keys, workspace IDs, Cookie values, users, or environment variables. Reading health never invokes a provider or initializes a local model.

The local faster-whisper and OCR implementation remains available for controlled fallback and offline deployments. Enable it explicitly with `LOCAL_ASR_ENABLED=true`; do not keep a Whisper model resident on the default 4C/4G cloud deployment.

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

Friends register once with a shared permanent invite code, choose their own username and password, and then use the normal login page. Passwords are hashed with `scrypt`; session tokens and the invite code are stored only as hashes. Jobs are scoped to the account that submitted them.

Generate the invite hash without placing the plaintext code in `.env`:

```bash
python3 -c 'import getpass,hashlib; print(hashlib.sha256(getpass.getpass("Invite code: ").strip().encode()).hexdigest())'
```

Set the result as `INVITE_CODE_HASH`. The relevant settings are:

```env
AUTH_DB_PATH=/opt/bili-subtitle-tool/var/auth/auth.db
AUTH_SESSION_TTL_DAYS=30
AUTH_MAX_USERS=50
AUTH_COOKIE_SECURE=true
INVITE_CODE_HASH=SHA256_HEX_ONLY
```

For an internet-facing deployment, add rate limits to login and registration,
set `AUTH_COOKIE_SECURE=true`, and terminate TLS at a maintained reverse proxy.
Keep hostnames, certificates, cloud configuration, and operational reports in a
separate private deployment repository.

## Bilibili login state

Bilibili Cookie use remains optional and disabled by default. Configure it only
through a private `.env` or a service-owned Cookie file. Do not use a primary
Bilibili account for a long-lived server Cookie, and ensure the Cookie file is
readable only by the service account.

Keep `.env`, the authentication database, invite codes, Douyin cookie state, passwords, tokens, and authorization headers out of logs and reports.
