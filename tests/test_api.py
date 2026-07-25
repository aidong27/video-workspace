import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.asr.signing import SignedAudioStore


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
        self.original_upload_limits = (
            main.UPLOAD_MAX_BYTES,
            main.PUBLIC_UPLOAD_MAX_BYTES,
            main.UPLOAD_STAGING_MAX_BYTES,
        )
        self.original_media_limits = (
            main.MEDIA_MAX_BYTES,
            main.MEDIA_STAGING_MAX_BYTES,
            main.MEDIA_ARTIFACT_TTL_SECONDS,
        )
        self.original_job_state = (
            main.JOB_MANAGER.state_path,
            main.JOB_MANAGER._restored,
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
        main.JOB_MANAGER.state_path = root / "cache" / "jobs.db"
        main.JOB_MANAGER._restored = False
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "AUTH_DB_PATH",
                "INVITE_CODE_HASH",
                "ASR_PREWARM",
                "ASR_ENABLED",
                "LOCAL_ASR_ENABLED",
                "CLOUD_ASR_ENABLED",
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
                "LOCAL_ASR_ENABLED": "false",
                "CLOUD_ASR_ENABLED": "false",
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
        (
            main.UPLOAD_MAX_BYTES,
            main.PUBLIC_UPLOAD_MAX_BYTES,
            main.UPLOAD_STAGING_MAX_BYTES,
        ) = self.original_upload_limits
        (
            main.MEDIA_MAX_BYTES,
            main.MEDIA_STAGING_MAX_BYTES,
            main.MEDIA_ARTIFACT_TTL_SECONDS,
        ) = self.original_media_limits
        main.JOB_MANAGER.state_path, main.JOB_MANAGER._restored = self.original_job_state
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
        with patch.dict(
            os.environ,
            {
                "ASR_AUDIO_FILTER": "private-filter-value",
                "DASHSCOPE_API_KEY": "private-api-key-value",
                "DASHSCOPE_WORKSPACE_ID": "private-workspace-value",
            },
        ):
            health = self.client.get("/api/health")
        self.assertEqual(login.status_code, 200)
        self.assertIn("text/html", login.headers["content-type"])
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["extraction_modes"]["fast"]["model"], main.DEFAULT_ASR_MODEL)
        self.assertEqual(health.json()["extraction_modes"]["accurate"]["model"], main.ACCURATE_ASR_MODEL)
        self.assertIn("enabled", health.json()["ocr"])
        self.assertIn("available", health.json()["disk"])
        self.assertIn("process_rss_mb", health.json()["memory"])
        self.assertIn("swap_used_mb", health.json()["memory"])
        self.assertIn("ffmpeg_available", health.json())
        self.assertTrue(health.json()["asr_single_model_instance"])
        self.assertEqual(health.json()["default_request"]["quality"], "accurate")
        self.assertEqual(health.json()["default_request"]["asr_mode"], "auto")
        self.assertIn("asr_backend", health.json()["default_request"])
        self.assertIn("auto", health.json()["asr_modes"])
        self.assertTrue(health.json()["default_request"]["allow_platform_ai"])
        self.assertTrue(health.json()["asr_audio_filter_enabled"])
        self.assertIn(
            health.json()["cloud_asr"]["audio_delivery"],
            {"signed_url", "aliyun_temp"},
        )
        self.assertIn(
            "provider_temporary_retention_seconds",
            health.json()["cloud_asr"],
        )
        self.assertEqual(health.json()["uploads"]["client_max_bytes"], main.PUBLIC_UPLOAD_MAX_BYTES)
        self.assertEqual(
            health.json()["uploads"]["edge_limited"],
            main.PUBLIC_UPLOAD_MAX_BYTES < main.UPLOAD_MAX_BYTES,
        )
        encoded = json.dumps(health.json())
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn("AUTH_DB_PATH", encoded)
        self.assertNotIn("INVITE_CODE_HASH", encoded)
        self.assertNotIn("private-filter-value", encoded)
        self.assertNotIn("private-api-key-value", encoded)
        self.assertNotIn("private-workspace-value", encoded)

    def test_account_can_change_password_and_logout_all_sessions(self) -> None:
        wrong = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong-password", "new_password": "new-strong-pass"},
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"]["reason"], "current_password_invalid")

        changed = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "strong-pass", "new_password": "new-strong-pass"},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertNotIn("password", json.dumps(changed.json()).lower())
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["active_sessions"], 1)
        self.assertIn("created_at", me.json()["user"])

        self.client.post("/api/auth/logout")
        old_login = self.client.post(
            "/api/auth/login",
            json={"username": "integration", "password": "strong-pass"},
        )
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post(
            "/api/auth/login",
            json={"username": "integration", "password": "new-strong-pass"},
        )
        self.assertEqual(new_login.status_code, 200)
        logged_out = self.client.post("/api/auth/logout-all")
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_signed_provider_audio_is_public_short_lived_and_revocable(self) -> None:
        audio = main.ASR_TMP_DIR / "asr-cloud-test" / "provider-audio.mp3"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"temporary-audio")
        store = SignedAudioStore(
            root=main.ASR_TMP_DIR,
            public_base_url="https://testserver",
            secret="s" * 32,
        )
        token, url = store.register(audio)
        path = url.removeprefix("https://testserver")
        with patch.object(main, "CLOUD_SIGNED_AUDIO_STORE", store):
            head = self.client.head(path)
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b"")
            self.assertEqual(head.headers["content-length"], str(len(b"temporary-audio")))
            self.assertEqual(head.headers["accept-ranges"], "bytes")
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"temporary-audio")
            self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
            store.revoke(token)
            expired = self.client.get(path)
        self.assertEqual(expired.status_code, 410)

    def test_bilibili_pages_endpoint_returns_sanitized_page_choices(self) -> None:
        page_data = {
            "title": "合集",
            "pages": [
                {"page": 1, "cid": 11, "part": "第一集", "duration": 60},
                {"page": 2, "cid": 22, "part": "第二集", "duration": 70},
            ],
        }
        with patch.object(
            main,
            "normalize_input",
            return_value="https://www.bilibili.com/video/BV14jFvzbEvj?p=2",
        ), patch.object(
            main,
            "bili_view_context",
            return_value=(
                "BV14jFvzbEvj",
                "https://www.bilibili.com/video/BV14jFvzbEvj?p=2",
                page_data,
                page_data["pages"][1],
                22,
            ),
        ):
            response = self.client.get("/api/bilibili/pages?input=BV14jFvzbEvj%3Fp%3D2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_page"], 2)
        self.assertEqual(response.json()["pages"][1]["cid"], 22)
        self.assertNotIn("cookie", json.dumps(response.json()).lower())

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
        headers = {
            "Idempotency-Key": "upload-integration-1",
            "Content-Type": "video/mp4",
            "X-ASR-Hotwords": "%E7%89%A9%E8%81%94%E7%BD%91%2C%20MQTT",
        }
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
        self.assertEqual(upload_request.hotwords, "物联网, MQTT")
        self.assertTrue(upload_request.embedded_subtitles)
        self.assertEqual(list(main.ASR_TMP_DIR.glob("asr-upload-*")), [])
        self.assertEqual(main.upload_staging_bytes(), 0)

    def test_upload_endpoint_defaults_to_accurate_chinese(self) -> None:
        result = {
            "ok": True,
            "format": "txt",
            "filename": "upload.txt",
            "content_type": "text/plain; charset=utf-8",
            "metadata": {"platform": "upload", "title": "upload"},
            "content": "subtitle",
        }
        with patch.object(main, "cached_upload_payload", return_value=result) as cache:
            response = self.client.post(
                "/api/upload-jobs?filename=defaults.mp4",
                content=b"fake-video-content",
                headers={"Idempotency-Key": "upload-defaults-1", "Content-Type": "video/mp4"},
            )

        self.assertEqual(response.status_code, 202)
        request = cache.call_args.args[0]
        self.assertEqual(request.quality, "accurate")
        self.assertEqual(request.lang, "zh")

    def test_upload_rejects_unsupported_extension_and_oversized_body(self) -> None:
        malformed_hotwords = self.client.post(
            "/api/upload-jobs?filename=clip.mp4&format=txt",
            content=b"not-yet-staged",
            headers={
                "Idempotency-Key": "upload-integration-bad-hotwords",
                "X-ASR-Hotwords": "%ZZ",
            },
        )
        self.assertEqual(malformed_hotwords.status_code, 422)
        self.assertEqual(malformed_hotwords.json()["detail"]["reason"], "invalid_hotwords")

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
    def test_frontend_defaults_to_local_base_chinese_with_platform_subtitles(self) -> None:
        page = (main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('name="asr-mode" value="auto" checked', page)
        self.assertIn('name="asr-mode" value="high_accuracy"', page)
        self.assertIn('name="asr-mode" value="economy"', page)
        self.assertIn('id="allow-platform-ai" type="checkbox" role="switch" checked', page)
        self.assertIn('<option value="zh" selected>中文</option>', page)
        self.assertIn('asr_mode: selectedAsrMode()', script)
        self.assertIn('payload.allow_platform_ai !== false', script)
        self.assertIn('X-ASR-Hotwords', script)
        self.assertIn("本地基础", page)
        self.assertIn('id="privacy-note"', page)

    def test_expired_backend_job_clears_saved_frontend_state(self) -> None:
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
        finish_block = script.split("function finishWithError", 1)[1].split("function handleJob", 1)[0]
        poll_block = script.split("async function pollJob", 1)[1].split("function submissionKey", 1)[0]

        self.assertIn("clearActiveJob();", finish_block)
        self.assertIn("finishWithError(data, response.status);", poll_block)

    def test_beta_workspace_exposes_operational_result_controls(self) -> None:
        page = (main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
        css = (main.STATIC_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn("1.0 Beta", page)
        for element_id in (
            "health-trigger",
            "health-popover",
            "mobile-tab-compose",
            "mobile-tab-result",
            "retry-accurate",
            "stage-track",
            "result-search",
            "toggle-wrap",
            "rail-subtitle",
            "rail-video",
            "rail-audio",
            "account-popover",
            "password-dialog",
        ):
            self.assertIn(f'id="{element_id}"', page)
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("function renderOutputContent()", script)
        self.assertIn("function updateStageTrack(", script)
        self.assertIn("function retryAccurate()", script)
        self.assertIn("function changeAccountPassword(", script)
        self.assertIn("function syncRailNavigation(", script)
        local_ready_block = script.split("function isLocalAsrReady()", 1)[1].split(
            "function syncPrecisionOptions", 1
        )[0]
        self.assertIn("state.health.ffmpeg_available === true", local_ready_block)
        self.assertIn("state.health.ffprobe_available === true", local_ready_block)
        self.assertIn('autoBackend === "local" && localReady', script)
        self.assertIn('autoBackend === "cloud" && cloudReady', script)
        self.assertIn("uploads.client_max_bytes", script)
        self.assertIn("body.dialog-open", css)
        self.assertNotIn("linear-gradient", css)

    def test_user_preferences_exclude_links_and_hotwords(self) -> None:
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
        preference_block = script.split("function savePreferences()", 1)[1].split(
            "function loadHistory", 1
        )[0]
        active_job_block = script.split("function saveActiveJob()", 1)[1].split(
            "function restoreForm", 1
        )[0]

        self.assertNotIn("elements.input", preference_block)
        self.assertNotIn("hotwords", preference_block)
        self.assertIn("delete persistedPayload.hotwords", active_job_block)

    def test_auth_page_has_password_visibility_and_caps_lock_feedback(self) -> None:
        page = (main.STATIC_DIR / "auth.html").read_text(encoding="utf-8")
        script = (main.STATIC_DIR / "auth.js").read_text(encoding="utf-8")
        css = (main.STATIC_DIR / "auth.css").read_text(encoding="utf-8")

        self.assertIn("1.0 Beta", page)
        self.assertIn('id="toggle-password"', page)
        self.assertIn('id="toggle-confirm-password"', page)
        self.assertIn('id="caps-warning"', page)
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('getModifierState("CapsLock")', script)
        self.assertIn("setupPasswordToggle(", script)
        self.assertNotIn("linear-gradient", css)


if __name__ == "__main__":
    unittest.main()
