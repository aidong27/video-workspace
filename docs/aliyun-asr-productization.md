# Aliyun ASR Productization Upgrade

## Baseline

- Repository: `aidong27/video-workspace`
- Pre-upgrade commit: `8875c7309c6564945f9b9ae319de0a4a6de268a6`
- Feature branch: `feat/aliyun-asr-productization`
- Production service: systemd `bili-subtitle-tool`
- Application: Uvicorn on `127.0.0.1:8000`
- Public entry: Nginx and HTTPS
- Deployment directory: `/opt/bili-subtitle-tool`
- Pre-upgrade production version: `1.0.0-beta.1`
- Rollback backup: `/opt/bili-subtitle-tool/var/backups/aliyun-asr-pre-20260725T085643Z`
- Backup contents: authenticated SQLite snapshot, application/config archive, systemd/Nginx archive, SHA-256 manifest

The pre-upgrade health check was successful with an empty queue. Local Whisper
was enabled and its persistent worker used about 562 MiB RSS after prewarm.

## Target

1. Keep Bilibili subtitles as the first and zero-cost path.
2. Use Aliyun Bailian file transcription only when an allowed ASR path is needed.
3. Provide independent Qwen and Paraformer providers behind one internal interface.
4. Disable local Whisper by default while preserving an explicit rollback option.
5. Enforce server-side daily, monthly, user, duration, queue, and paid-use limits.
6. Keep audio URLs short-lived, signed, non-enumerable, owner-independent, and revocable.
7. Preserve existing APIs and TXT, SRT, VTT, Markdown, and JSON exports.
8. Deploy only after mocked regression tests and a bounded real API comparison pass.

## Cost And Security Guardrails

- `ASR_ALLOW_PAID=false` by default.
- Real free quota and pricing must come from the Beijing Bailian console.
- Hard limits remain below the confirmed free quota.
- No API key, Cookie, signed URL, or credential may enter Git, frontend assets, logs, screenshots, or reports.
- No OSS, paid resource package, recharge, DNS, firewall, or unrelated service change without explicit approval.
- Provider retries are finite and only for retryable failures.
- Temporary audio is deleted after completion, failure, cancellation, or expiry.

## Rollback

Restore the pre-upgrade archive and SQLite snapshot from the backup directory,
restore the saved runtime configuration if it changed, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bili-subtitle-tool
curl -fsS http://127.0.0.1:8000/api/health
```

The exact rollback command will be tested against a staging copy before the
production deployment.
