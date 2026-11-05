# Workspace 1.1 upgrade

Date: 2026-11-06. Base: `56f8b09` (1.0.0-beta.6, day retention).

## Why

On 2026-11-05 every Bilibili link failed. `api.bilibili.com/x/web-interface/view`
answered the production host with HTTP 412, and so did the video web page that
yt-dlp reads. Bilibili applies this refusal (risk control) to anonymous requests
from data-centre addresses; the same request from a residential connection
succeeds. Users only saw a generic "任务处理失败" after the service had also
spent time on a yt-dlp attempt that hit the same refusal.

This release does **not** try to get around that refusal. It makes the failure
fast and explicit, keeps every other path working, and leaves the choice of a
signed-in Bilibili session to the site owner (see "Bilibili access" below).

## Backend

- `app/errors.py`: `ExtractionFailure`, the public error catalog and secret
  redaction, moved out of `main.py`. New codes: `platform_blocked` (Bilibili
  refused the server) and `platform_unreachable` (network/HTTP failure).
- `app/subtitles.py`: subtitle entry model, JSON/SRT/VTT parsers and the
  TXT/SRT/VTT/Markdown/JSON renderers.
- `app/bilibili.py`: link parsing (BV and `av` links), WBI signing with a cached
  mixin key, and `PlatformAccessGuard`.
- `app.main` re-exports the moved names, so `app.main.ExtractionFailure` and the
  other existing imports keep working.
- HTTP 412 and the risk-control API codes (-352, -412) now raise
  `platform_risk_control`. The guard then answers further Bilibili requests
  locally for `BILI_RISK_COOLDOWN_SECONDS` (default 300) instead of repeating
  refused requests; the first request after the cooldown probes again, and any
  successful response clears it. Anonymous and signed-in modes are tracked
  separately, so a refused anonymous attempt still lets a configured login state
  try once in automatic mode.
- Subtitle lookup is API-first. yt-dlp is only used for link shapes the JSON API
  cannot parse and for transient API errors, never after a refusal.
- `av` links resolve through the view API (`aid=`) instead of depending on yt-dlp.
- The WBI key is cached for `BILI_WBI_KEY_TTL_SECONDS` (default 1800) instead of
  fetching `/x/web-interface/nav` before every signed call; a rejected signature
  drops the key and re-signs once.
- `/api/public-config` and `/api/client-config` expose
  `platform_status.bilibili` (`ok` or `limited` with `retry_after_seconds`).
- Completed subtitle job details include `segments` (and `raw_segments` when a
  raw transcript exists) taken from the owner's stored entries. The jobs list and
  format exports are unchanged.
- `/api/auth/me` reports `is_admin` for the current user only.
- FastAPI lifespan replaces the deprecated `on_event` hooks.

## Web UI

- New design system shared by the workspace, sign-in and diagnostics pages:
  light and dark themes that follow the system, plus a header toggle
  (system / light / dark). `theme.js` applies the saved choice before first
  paint because the CSP forbids inline scripts.
- Two-pane layout. The left navigation rail duplicated the operation switch and
  was removed; recent history moved to a drawer with a count badge.
- Reading view: timed lines with timestamps, in-line search highlighting and
  one-click copy of a single line. The "文件" view shows the exact export for
  the chosen format; copy and download still use the export.
- A Bilibili link shows a warning before submission while the platform is
  limited, with a shortcut to the upload path. A refused task marks the status
  pill as "部分受限".
- Kept unchanged: idempotent submission, polling back-off and manual reconnect,
  restore after refresh, upload progress and cancellation, cloud-cost
  confirmation with focus trapping, guest media mode, expiry handling.
- `prefers-reduced-motion` now disables animation instead of shortening it.

## Bilibili access

Anonymous requests from this host stay refused until Bilibili lifts its block.
Options for the owner:

1. Use a dedicated, secondary Bilibili account: enable `WEB_QR_LOGIN_ENABLED`
   (or `COOKIE_ENABLED` with a cookie file) and scan the QR code from the
   workspace. Signed-in requests use the platform's normal authenticated access
   and also return platform AI subtitles, which Bilibili no longer exposes to
   anonymous visitors.
2. Download the video yourself and use "上传文件".

## Verification

- Python: 282 passed (`.venv/bin/python -m pytest -q`), ruff clean.
- Workspace UI: 41 passed in Chromium and 41 in WebKit
  (`node --test tests/workspace_ui.test.cjs`, `UI_BROWSER=webkit …`).
- Admin UI: 4 passed.
- Local end-to-end: upload with an embedded subtitle track (4 timed lines,
  every export format), Bilibili audio extraction to MP3 and download.

## Rollback

Code-only; no database or schema changes. Restore the previous `app/` files from
the release backup and restart the service. The two new environment variables
are optional and have safe defaults.

## 1.2 — invitation-only access

- Activation codes replace registration, passwords, and guest media. The gate,
  lockout rules, session binding, and member limits are described in the README
  under "Access and sharing"; the code lives in `app/access.py` and `app/auth.py`.
- The owner console (`/admin`) manages codes, devices, the gate log, runtime
  diagnostics, and the Bilibili login. Bilibili QR login is owner-only; once saved,
  every Bilibili request uses that login and signed-in calls are paced.
- Existing password sessions are cleared on first start; existing accounts keep
  their history when the owner binds a code to them
  (`python -m app.access issue --owner --username NAME --label 站长`).
- The interface was redesigned: glass panels over an animated aurora, a WebGL
  gate, a processing visualizer, a subtitle timeline strip, and a ⌘K command
  palette. All motion stops under `prefers-reduced-motion`.
