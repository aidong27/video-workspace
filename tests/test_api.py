import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.original_paths = (
            main.ASR_TMP_DIR,
            main.ASR_MODEL_DIR,
            main.ASR_CACHE_DIR,
            main.RESULT_CACHE_DIR,
            main.BILI_COOKIE_PATH,
            main.MEDIA_ARTIFACT_DIR,
        )
        self.original_upload_limits = (main.UPLOAD_MAX_BYTES, main.UPLOAD_STAGING_MAX_BYTES)
        self.original_media_limits = (
            main.MEDIA_MAX_BYTES,
            main.MEDIA_STAGING_MAX_BYTES,
            main.MEDIA_ARTIFACT_TTL_SECONDS,
        )
        main.ASR_TMP_DIR = root / "tmp"
        main.ASR_MODEL_DIR = root / "models"
        main.ASR_CACHE_DIR = root / "cache"
        main.RESULT_CACHE_DIR = root / "results"
        main.BILI_COOKIE_PATH = root / "auth" / "bili-cookie.txt"
        main.MEDIA_ARTIFACT_DIR = root / "media-artifacts"
        main.MEDIA_MAX_BYTES = 1024
        main.MEDIA_STAGING_MAX_BYTES = 2048
        main.MEDIA_ARTIFACT_TTL_SECONDS = 3600
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "AUTH_DB_PATH",
                "INVITE_CODE_HASH",
                "ASR_PREWARM",
                "ASR_ENABLED",
                "AUTH_COOKIE_SECURE",
            )
        }
        invite = "integration-invite"
        os.environ.update(
            {
                "AUTH_DB_PATH": str(root / "auth" / "auth.db"),
                "INVITE_CODE_HASH": hashlib.sha256(invite.encode()).hexdigest(),
                "ASR_PREWARM": "false",
                "ASR_ENABLED": "false",
                "AUTH_COOKIE_SECURE": "true",
            }
        )
        self.client_context = TestClient(main.app, base_url="https://testserver")
        self.client = self.client_context.__enter__()
        response = self.client.post(
            "/api/auth/register",
            json={"username": "integration", "password": "strong-pass", "invite_code": invite},
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        (
            main.ASR_TMP_DIR,
            main.ASR_MODEL_DIR,
            main.ASR_CACHE_DIR,
            main.RESULT_CACHE_DIR,
            main.BILI_COOKIE_PATH,
            main.MEDIA_ARTIFACT_DIR,
        ) = self.original_paths
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        main.RESULT_KEY_LOCKS.clear()
        with main.UPLOAD_RESERVATION_LOCK:
            main.UPLOAD_RESERVATIONS.clear()
        with main.MEDIA_RESERVATION_LOCK:
            main.MEDIA_RESERVATIONS.clear()
        main.UPLOAD_MAX_BYTES, main.UPLOAD_STAGING_MAX_BYTES = self.original_upload_limits
        (
            main.MEDIA_MAX_BYTES,
            main.MEDIA_STAGING_MAX_BYTES,
            main.MEDIA_ARTIFACT_TTL_SECONDS,
        ) = self.original_media_limits
        self.tmp.cleanup()

    def test_job_submission_is_idempotent_and_legacy_get_is_retired(self) -> None:
        result = {
            "ok": True,
            "format": "txt",
            "filename": "cached.txt",
            "content_type": "text/plain; charset=utf-8",
            "metadata": {"platform": "bilibili"},
            "content": "cached subtitle",
        }
        headers = {"Idempotency-Key": "integration-request-1"}
        request = {"input": "BV14jFvzbEvj", "format": "txt"}
        with patch.object(main, "cached_extraction_payload", return_value=result):
            first = self.client.post("/api/jobs", json=request, headers=headers)
            repeated = self.client.post("/api/jobs", json=request, headers=headers)
            conflicting = self.client.post(
                "/api/jobs",
                json={"input": "BV1xx411c7mD", "format": "txt"},
                headers=headers,
            )
            legacy = self.client.post(
                "/api/extract",
                json=request,
                headers={"Idempotency-Key": "integration-request-2"},
            )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(repeated.status_code, 202)
        self.assertEqual(first.json()["id"], repeated.json()["id"])
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.json()["detail"]["reason"], "idempotency_conflict")
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()["content"], "cached subtitle")
        retired = self.client.get("/api/download?input=BV14jFvzbEvj")
        self.assertEqual(retired.status_code, 410)

    def test_public_file_response_and_health_work_on_new_starlette(self) -> None:
        login = self.client.get("/login")
        health = self.client.get("/api/health")
        self.assertEqual(login.status_code, 200)
        self.assertIn("text/html", login.headers["content-type"])
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["extraction_modes"]["fast"]["model"], main.DEFAULT_ASR_MODEL)
        self.assertEqual(health.json()["extraction_modes"]["accurate"]["model"], main.ACCURATE_ASR_MODEL)
        self.assertIn("enabled", health.json()["ocr"])
        self.assertIn("available", health.json()["disk"])
        self.assertIn("ffmpeg_available", health.json())
        encoded = json.dumps(health.json())
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn("AUTH_DB_PATH", encoded)
        self.assertNotIn("INVITE_CODE_HASH", encoded)

    def test_unknown_job_reports_restart_or_expiry(self) -> None:
        response = self.client.get(f"/api/jobs/{'0' * 32}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "job_expired")
        self.assertTrue(response.json()["detail"]["retryable"])

    def test_disabled_douyin_is_not_reported_ready(self) -> None:
        adapter = {
            "enabled": False,
            "api_adapter_ready": True,
            "playwright_ready": True,
            "chromium_ready": True,
            "cookie_cached": True,
        }
        with patch.object(main, "douyin_adapter_status", return_value=adapter):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["platforms"]["douyin"]["status"], "disabled")

    def test_raw_video_upload_creates_idempotent_cached_job_and_cleans_file(self) -> None:
        result = {
            "ok": True,
            "format": "txt",
            "filename": "upload.txt",
            "content_type": "text/plain; charset=utf-8",
            "metadata": {"platform": "upload", "title": "upload"},
            "content": "uploaded subtitle",
        }
        headers = {"Idempotency-Key": "upload-integration-1", "Content-Type": "video/mp4"}
        with patch.object(main, "cached_upload_payload", return_value=result) as cache:
            first = self.client.post(
                "/api/upload-jobs?filename=clip.mp4&format=txt&lang=zh&quality=accurate&embedded_subtitles=true",
                content=b"fake-video-content",
                headers=headers,
            )
            repeated = self.client.post(
                "/api/upload-jobs?filename=clip.mp4&format=txt&lang=zh&quality=accurate&embedded_subtitles=true",
                content=b"fake-video-content",
                headers=headers,
            )
            conflicting = self.client.post(
                "/api/upload-jobs?filename=clip.mp4&format=srt&lang=zh",
                content=b"fake-video-content",
                headers=headers,
            )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["status"], "completed")
        self.assertEqual(first.json()["platform"], "upload")
        self.assertEqual(first.json()["id"], repeated.json()["id"])
        self.assertTrue(repeated.json()["reused"])
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.json()["detail"]["reason"], "idempotency_conflict")
        self.assertEqual(cache.call_count, 1)
        upload_request = cache.call_args.args[0]
        self.assertEqual(upload_request.quality, "accurate")
        self.assertTrue(upload_request.embedded_subtitles)
        self.assertEqual(list(main.ASR_TMP_DIR.glob("asr-upload-*")), [])
        self.assertEqual(main.upload_staging_bytes(), 0)

    def test_upload_rejects_unsupported_extension_and_oversized_body(self) -> None:
        unsupported = self.client.post(
            "/api/upload-jobs?filename=notes.txt&format=txt",
            content=b"not-video",
            headers={"Idempotency-Key": "upload-integration-2"},
        )
        self.assertEqual(unsupported.status_code, 415)
        self.assertEqual(unsupported.json()["detail"]["reason"], "unsupported_upload_format")

        main.UPLOAD_MAX_BYTES = 4
        main.UPLOAD_STAGING_MAX_BYTES = 8
        oversized = self.client.post(
            "/api/upload-jobs?filename=large.mp4&format=txt",
            content=b"12345",
            headers={"Idempotency-Key": "upload-integration-3"},
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()["detail"]["reason"], "upload_too_large")
        self.assertEqual(list(main.ASR_TMP_DIR.glob("asr-upload-*")), [])

    def test_media_job_is_idempotent_and_download_is_owner_scoped(self) -> None:
        def fake_media_result(request: main.MediaJobRequest) -> dict:
            directory = main.media_artifact_directory(request.artifact_token)
            directory.mkdir(parents=True, mode=0o700)
            final = directory / "artifact.mp4"
            final.write_bytes(b"downloadable-video")
            return main.finalize_media_artifact(
                request,
                final,
                "video/mp4",
                {
                    "id": "BV14jFvzbEvj",
                    "title": "集成测试视频",
                    "duration": 9,
                    "webpage_url": request.input,
                    "source_container": "mp4",
                },
                time.monotonic(),
            )

        request = {
            "input": "BV14jFvzbEvj",
            "media_type": "video",
        }
        headers = {"Idempotency-Key": "media-integration-1"}
        with patch.object(main, "media_extraction_payload", side_effect=fake_media_result):
            first = self.client.post("/api/media-jobs", json=request, headers=headers)
            self.assertEqual(first.status_code, 202)
            deadline = time.monotonic() + 2
            job = first.json()
            while job["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
                time.sleep(0.01)
                job = self.client.get(f"/api/jobs/{job['id']}").json()

        self.assertEqual(job["status"], "completed")
        repeated = self.client.post("/api/media-jobs", json=request, headers=headers)
        conflicting = self.client.post(
            "/api/media-jobs",
            json={"input": "BV14jFvzbEvj", "media_type": "audio"},
            headers=headers,
        )
        self.assertEqual(repeated.json()["id"], job["id"])
        self.assertTrue(repeated.json()["reused"])
        self.assertEqual(conflicting.status_code, 409)

        download = self.client.get(job["result"]["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"downloadable-video")
        self.assertIn("attachment", download.headers["content-disposition"])
        ranged = self.client.get(
            job["result"]["download_url"],
            headers={"Range": "bytes=0-3"},
        )
        self.assertIn(ranged.status_code, {200, 206})
        self.assertEqual(
            ranged.content,
            b"down" if ranged.status_code == 206 else b"downloadable-video",
        )

        self.client.post("/api/auth/logout")
        second = self.client.post(
            "/api/auth/register",
            json={"username": "integration2", "password": "strong-pass-2", "invite_code": "integration-invite"},
        )
        self.assertEqual(second.status_code, 200)
        forbidden = self.client.get(job["result"]["download_url"])
        self.assertEqual(forbidden.status_code, 404)
        forbidden_job = self.client.get(f"/api/jobs/{job['id']}")
        self.assertEqual(forbidden_job.status_code, 404)


class FrontendRecoveryTests(unittest.TestCase):
    def test_expired_backend_job_clears_saved_frontend_state(self) -> None:
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
        finish_block = script.split("function finishWithError", 1)[1].split("function handleJob", 1)[0]
        poll_block = script.split("async function pollJob", 1)[1].split("function submissionKey", 1)[0]

        self.assertIn("clearActiveJob();", finish_block)
        self.assertIn("finishWithError(data, response.status);", poll_block)


if __name__ == "__main__":
    unittest.main()
