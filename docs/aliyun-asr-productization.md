# Aliyun ASR Productization Upgrade

## Baseline

- Repository: `aidong27/video-workspace`
- Pre-upgrade commit: `8875c7309c6564945f9b9ae319de0a4a6de268a6`
- Feature branch: `feat/aliyun-asr-productization`
- Pre-upgrade production version: `1.0.0-beta.1`
- Production topology, backup locations, and restore commands are retained in
  private operational records and are intentionally not committed.

The pre-upgrade health check was successful with an empty queue. Local Whisper
was enabled and its persistent worker used about 562 MiB RSS after prewarm.

## Target

1. Keep Bilibili subtitles as the first and zero-cost path.
2. Use Aliyun Bailian file transcription only when an allowed ASR path is needed.
3. Provide independent Qwen and Paraformer providers behind one internal interface.
4. Disable local Whisper by default while preserving an explicit rollback option.
5. Enforce server-side lifetime, daily, monthly, user, duration, queue, and paid-use limits.
6. Support short-lived signed URLs and Bailian's 48-hour temporary-file service
   as explicit, configurable audio-delivery modes.
7. Preserve existing APIs and TXT, SRT, VTT, Markdown, and JSON exports.
8. Deploy only after mocked regression tests and a bounded real API comparison pass.

## Cost And Security Guardrails

- `ASR_ALLOW_PAID=false` by default.
- Real free quota and pricing must come from the Beijing Bailian console.
- Hard limits remain below the confirmed free quota.
- No API key, Cookie, signed URL, or credential may enter Git, frontend assets, logs, screenshots, or reports.
- No OSS, paid resource package, recharge, DNS, firewall, or unrelated service change without explicit approval.
- Provider query retries are finite. Billable task-submission POST requests are not retried automatically.
- Local temporary audio is deleted after completion, failure, cancellation, or
  expiry. Bailian temporary uploads auto-expire within 48 hours and cannot be
  revoked immediately by this application.

## Implemented

- Independent Qwen, Paraformer, and mock providers with normalized transcripts.
- Short-lived HMAC audio delivery with immediate revocation and SSRF checks.
- Official Bailian temporary-file delivery with a trusted Beijing OSS host
  allowlist, random object names, bounded uploads, and explicit resolver headers.
- SQLite usage reservations with lifetime, daily, monthly, and per-user limits.
- SQLite job state with queued-job recovery and explicit interruption of tasks
  that had already begun before a service restart.
- Raw and organized subtitle variants plus TXT, SRT, VTT, Markdown, and JSON output.
- Cloud-first UI modes, Bilibili part selection, task restoration, source/model
  metadata, privacy notice, and responsive mobile layout.
- Local Whisper remains available only through an explicit opt-in setting.

## Verification

- Mocked unit and integration suite: 165 tests passed after the temporary-file
  fallback and quota-lifecycle regression coverage were integrated.
- Python bytecode compilation and JavaScript syntax checks passed.
- Browser smoke test passed for registration, login, desktop layout, and a
  `390x844` mobile viewport with no horizontal overflow.
- Real provider comparison and production deployment results belong in private
  release records because they contain account and infrastructure context.

During production verification, Bailian's downloader reached the public audio
route with a Java user agent but was blocked by the existing edge Browser
Integrity Check before the application received the request. No DNS, proxy, or
edge-security setting was changed. The beta deployment therefore uses Bailian's
official temporary-file service; signed URL delivery remains available as the
rollback mode.

## Rollback

Restore the private pre-upgrade application/config archive and SQLite snapshot,
then restart the single application worker:

```bash
sudo systemctl daemon-reload
sudo systemctl restart <service-name>
curl -fsS http://127.0.0.1:8000/api/health
```
