import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import access, auth, main
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
        with main.JOB_MANAGER.lock:
            main.JOB_MANAGER.records.clear()
            main.JOB_MANAGER.queue.clear()
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "AUTH_DB_PATH",
                "ASR_PREWARM",
                "ASR_ENABLED",
                "LOCAL_ASR_ENABLED",
                "CLOUD_ASR_ENABLED",
                "AUTH_COOKIE_SECURE",
            )
        }
        os.environ.update(
            {
                "AUTH_DB_PATH": str(root / "auth" / "auth.db"),
                "ASR_PREWARM": "false",
                "ASR_ENABLED": "false",
                "LOCAL_ASR_ENABLED": "false",
                "CLOUD_ASR_ENABLED": "false",
                "AUTH_COOKIE_SECURE": "true",
            }
        )
        self.client_context = TestClient(main.app, base_url="https://testserver")
        self.client = self.client_context.__enter__()
        self.code = self.sign_in("integration")

    def sign_in(self, username: str, role: str = "member") -> str:
        """Issue a code for ``username`` and enter through the gate with it."""
        code, _ = access.issue_code(label=username, username=username, role=role)
        self.client.cookies.clear()
        response = self.client.post("/api/auth/activate", json={"code": code})
        self.assertEqual(response.status_code, 200, response.text)
        return code

    def member_id(self, label: str) -> int:
        return next(item["id"] for item in access.list_members() if item["label"] == label)

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

    def test_recent_jobs_are_owned_private_and_do_not_restart_work(self) -> None:
        result = main.subtitle_result_payload([main.SubtitleEntry(0, 1, "hello")],
                                             {"title": "Saved result", "platform": "bilibili"}, "txt")
        with patch.object(main, "cached_extraction_payload", return_value=result):
            job = self.client.post("/api/jobs", json={"input": "BV14jFvzbEvj"}).json()
        main.JOB_MANAGER.submit_completed({"hotwords": "private"}, result, owner_id=999)
        with patch.object(main.JOB_MANAGER, "submit") as submit:
            response = self.client.get("/api/jobs?limit=20")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "private, no-store")
            self.assertEqual(response.json()["retention_seconds"], 86400)
            self.assertEqual([item["id"] for item in response.json()["jobs"]], [job["id"]])
            self.assertEqual(job["expires_at"], job["updated_at"] + 86400)
            self.assertNotIn("hello", response.text)
            self.assertNotIn("private", response.text)
            self.assertNotIn("_entries", response.text)
            submit.assert_not_called()
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)

    def test_expired_subtitle_is_unavailable_in_list_get_and_export(self) -> None:
        owner = self.client.get("/api/auth/me").json()["user"]["id"]
        result = main.subtitle_result_payload([main.SubtitleEntry(0, 1, "expired")], {}, "txt")
        job = main.JOB_MANAGER.submit_completed({}, result, owner_id=owner)
        main.JOB_MANAGER.records[job["id"]].updated_at = time.time() - 86401
        self.assertEqual(self.client.get("/api/jobs").json()["jobs"], [])
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/result").status_code, 404)
        with main.JOB_MANAGER._connect_state() as database:
            self.assertIsNone(database.execute("SELECT job_id FROM jobs WHERE job_id = ?", (job["id"],)).fetchone())

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

    def test_completed_result_exports_without_queue_cache_or_recognition(self) -> None:
        entries = [main.SubtitleEntry(3600, 3601.25, "第一段测试。")]
        meta = {
            "title": "测试视频", "source": "asr_local", "asr_model": "hidden-model",
            "raw_entries": [{"start": 3600, "end": 3602, "text": "原始结果。"}],
        }
        result = main.subtitle_result_payload(entries, meta, "txt")
        with patch.object(main, "cached_extraction_payload", return_value=result):
            submitted = self.client.post("/api/jobs", json={"input": "BV14jFvzbEvj"})
        job_id = submitted.json()["id"]
        self.assertNotIn("_entries", submitted.json()["result"])
        self.assertEqual(
            submitted.json()["result"]["segments"],
            [{"start": 3600.0, "end": 3601.25, "text": "第一段测试。"}],
        )
        self.assertEqual(submitted.json()["result"]["raw_segments"][0]["text"], "原始结果。")
        detail = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(detail["result"]["segments"][0]["text"], "第一段测试。")
        with patch.object(main, "extract_subtitle_data") as extract, patch.object(
            main.JOB_MANAGER, "submit"
        ) as submit, patch.object(main, "load_cached_result") as cache:
            for fmt in ("txt", "srt", "vtt", "json", "markdown", "md"):
                with self.subTest(format=fmt):
                    response = self.client.get(f"/api/jobs/{job_id}/result", params={"format": fmt})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["cache-control"], "private, no-store")
                    data = response.json()
                    self.assertIn("第一段测试。", data["content"])
                    self.assertIn("原始结果。", data["raw_content"])
                    self.assertNotIn("hidden-model", response.text)
                    self.assertNotIn("_entries", data)
                    if fmt == "srt":
                        self.assertIn("01:00:00,000 --> 01:00:01,250", data["content"])
                    if fmt == "json":
                        self.assertNotIn("asr_model", json.loads(data["content"])["metadata"])
            extract.assert_not_called()
            submit.assert_not_called()
            cache.assert_not_called()
        # The same completed record survives a restart without needing the source file.
        restored = main.JobManager(lambda request, update: request, state_path=main.JOB_MANAGER.state_path)
        restored.start()
        try:
            self.assertEqual(restored.get(job_id)["result"]["_entries"][0]["text"], "第一段测试。")
        finally:
            restored.stop()
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result?format=exe").status_code, 422)
        self.sign_in("another-user")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/result").status_code, 401)

    def test_old_result_does_not_silently_start_another_recognition(self) -> None:
        with patch.object(main, "cached_extraction_payload", return_value={
            "ok": True, "format": "txt", "content": "legacy result", "metadata": {},
        }):
            job_id = self.client.post("/api/jobs", json={"input": "BV14jFvzbEvj"}).json()["id"]
        with patch.object(main, "extract_subtitle_data") as extract:
            response = self.client.get(f"/api/jobs/{job_id}/result?format=srt")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"]["code"], "result_unavailable")
        extract.assert_not_called()

    def test_completed_job_strips_runtime_metadata_from_browser_response(self) -> None:
        internal_metadata = {
            "platform": "bilibili",
            "title": "测试视频",
            "source": "asr_local",
            "language": "zh",
            "duration": 30,
            "entry_count": 1,
            "asr_model": "private-model-name",
            "asr_compute_type": "int8",
            "asr_cpu_threads": 3,
            "asr_worker_reused": True,
            "peak_rss_mb": 999,
            "provider_task_id": "private-provider-task",
            "estimated_cost_cny": 1.23,
            "raw_metadata": {"internal": "private"},
        }
        result = {
            "ok": True,
            "format": "json",
            "filename": "subtitle.json",
            "content_type": "application/json; charset=utf-8",
            "metadata": internal_metadata,
            "content": json.dumps(
                {
                    "metadata": internal_metadata,
                    "entries": [{"start": 0, "end": 1, "text": "测试"}],
                },
                ensure_ascii=False,
            ),
        }
        with patch.object(main, "cached_extraction_payload", return_value=result):
            response = self.client.post(
                "/api/jobs",
                json={"input": "BV14jFvzbEvj", "format": "json"},
            )
            download = self.client.post(
                "/api/download",
                json={"input": "BV14jFvzbEvj", "format": "json"},
                headers={"Idempotency-Key": "privacy-download-test"},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(download.status_code, 200)
        public_result = response.json()["result"]
        self.assertEqual(public_result["metadata"]["title"], "测试视频")
        self.assertEqual(public_result["metadata"]["source"], "asr_local")
        self.assertNotIn("asr_model", public_result["metadata"])
        self.assertNotIn("peak_rss_mb", public_result["metadata"])
        exported = json.loads(public_result["content"])
        self.assertEqual(exported["entries"][0]["text"], "测试")
        self.assertEqual(exported["metadata"], public_result["metadata"])
        encoded = json.dumps(response.json())
        self.assertNotIn("private-model-name", encoded)
        self.assertNotIn("private-provider-task", encoded)
        self.assertNotIn("peak_rss_mb", encoded)
        self.assertEqual(json.loads(download.text)["metadata"], public_result["metadata"])

    def test_public_file_response_and_health_work_on_new_starlette(self) -> None:
        login = self.client.get("/login")
        with patch.dict(
            os.environ,
            {
                "ASR_AUDIO_FILTER": "private-filter-value",
                "DASHSCOPE_API_KEY": "private-api-key-value",
                "DASHSCOPE_WORKSPACE_ID": "private-workspace-value",
            },
        ), patch.object(
            main,
            "runtime_memory_status",
            side_effect=AssertionError("public health must not inspect memory"),
        ), patch.object(
            main,
            "disk_space_status",
            side_effect=AssertionError("public health must not inspect disk"),
        ), patch.object(
            main,
            "cloud_usage_stats",
            side_effect=AssertionError("public health must not inspect provider usage"),
        ), patch.object(
            main,
            "douyin_adapter_status",
            side_effect=AssertionError("public health must not inspect adapters"),
        ):
            health = self.client.get("/api/health")
        self.assertEqual(login.status_code, 200)
        self.assertIn("text/html", login.headers["content-type"])
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertEqual(health.headers["cache-control"], "no-store")

        adapter = {
            "enabled": True,
            "api_adapter_ready": True,
            "playwright_ready": True,
            "chromium_ready": True,
            "cookie_cached": True,
        }
        with patch.object(main, "douyin_adapter_status", return_value=adapter):
            client_config = self.client.get("/api/client-config")
        self.assertEqual(client_config.status_code, 200)
        config = client_config.json()
        self.assertEqual(config["status"], "ok")
        self.assertEqual(config["uploads"]["max_bytes"], main.PUBLIC_UPLOAD_MAX_BYTES)
        self.assertIn("local_processing", config["features"])
        self.assertIn("cloud_enhancement", config["features"])
        self.assertIn("auto", config["asr_modes"])
        self.assertTrue(config["platforms"]["douyin"])
        encoded = json.dumps(health.json())
        encoded += json.dumps(config)
        for forbidden in (
            str(self.root),
            "AUTH_DB_PATH",
            "INVITE_CODE_HASH",
            "private-filter-value",
            "private-api-key-value",
            "private-workspace-value",
            "service_version",
            "process_rss",
            "swap_used",
            "free_bytes",
            "max_pending",
            "asr_model",
            "provider_task_id",
            "monthly_free_seconds",
            "staging_reserved_bytes",
        ):
            self.assertNotIn(forbidden, encoded)

        self.client.post("/api/auth/logout")
        unauthenticated = self.client.get("/api/client-config")
        self.assertEqual(unauthenticated.status_code, 401)

    def test_admin_diagnostics_requires_allowlisted_account_and_stays_redacted(self) -> None:
        denied = self.client.get("/api/admin/diagnostics")
        denied_page = self.client.get("/admin")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"]["reason"], "admin_required")
        self.assertEqual(denied_page.status_code, 403)

        disk = main.DiskSpaceStatus(
            total_bytes=10_000,
            free_bytes=7_500,
            free_ratio=0.75,
            minimum_free_bytes=1_000,
            required_bytes=0,
            available=True,
        )
        adapter = {
            "enabled": True,
            "api_adapter_ready": True,
            "playwright_ready": True,
            "chromium_ready": True,
            "cookie_cached": False,
            "cookie_path": "/private/cookie.json",
        }
        usage = {
            "daily_seconds": 12,
            "monthly_seconds": 34,
            "total_seconds": 56,
            "reserved_seconds": 0,
            "daily_limit_seconds": 100,
            "monthly_limit_seconds": 1000,
            "user_daily_limit_seconds": 50,
            "total_limit_seconds": 2000,
            "by_model_seconds": {"safe-model": 56},
        }
        failures = {
            "window_days": 30,
            "total": 1,
            "by_provider": {"aliyun": 1},
            "by_model": {"safe-model": 1},
            "by_code": {"asr_rate_limited": 1},
            "by_outcome": {"provider_failed": 1},
        }
        with patch.dict(
            os.environ,
            {
                "ADMIN_USERNAMES": "INTEGRATION",
                "DASHSCOPE_API_KEY": "private-api-key-value",
                "DASHSCOPE_WORKSPACE_ID": "private-workspace-value",
            },
        ), patch.object(main, "disk_space_status", return_value=disk), patch.object(
            main,
            "runtime_memory_status",
            return_value={
                "process_rss_mb": 120.0,
                "process_swap_mb": 0.0,
                "system_available_mb": 2048.0,
                "swap_total_mb": 2048.0,
                "swap_used_mb": 10.0,
            },
        ), patch.object(main, "cloud_usage_stats", return_value=usage), patch.object(
            main, "cloud_failure_stats", return_value=failures
        ), patch.object(main, "cloud_asr_ready", return_value=True), patch.object(
            main, "douyin_adapter_status", return_value=adapter
        ):
            allowed = self.client.get("/api/admin/diagnostics")
            allowed_page = self.client.get("/admin")

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["cache-control"], "private, no-store")
        self.assertEqual(allowed.headers["x-robots-tag"], main.NOINDEX)
        payload = allowed.json()
        self.assertEqual(payload["queue"]["worker_count"], main.JOB_MANAGER.worker_count)
        self.assertEqual(payload["cloud_asr"]["failures"]["total"], 1)
        self.assertEqual(payload["disk"]["free_bytes"], 7_500)
        self.assertNotIn("cookie_path", payload["platforms"]["douyin"])
        encoded = json.dumps(payload)
        self.assertNotIn("private-api-key-value", encoded)
        self.assertNotIn("private-workspace-value", encoded)
        self.assertNotIn("/private/", encoded)
        self.assertEqual(allowed_page.status_code, 200)
        self.assertEqual(allowed_page.headers["x-robots-tag"], main.NOINDEX)

        self.client.cookies.clear()
        unauthenticated = self.client.get("/api/admin/diagnostics")
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(unauthenticated.json()["detail"]["reason"], "authentication_required")

    def test_admin_diagnostics_does_not_wait_for_active_asr_task_lock(self) -> None:
        with patch.dict(os.environ, {"ADMIN_USERNAMES": "integration"}), main.ASR_WORKER_LOCK:
            response = self.client.get("/api/admin/diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["asr_worker"]["snapshot_consistent"])

    def test_gate_blocks_everything_without_a_session(self) -> None:
        self.client.cookies.clear()
        page = self.client.get("/", follow_redirects=False)
        self.assertEqual(page.status_code, 303)
        self.assertEqual(page.headers["location"], "/login")
        self.assertEqual(page.headers["x-robots-tag"], main.NOINDEX)
        self.assertEqual(self.client.get("/admin", follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get("/register", follow_redirects=False).status_code, 303)
        for path in ("/api/jobs", "/api/client-config", "/api/admin/members", "/api/public-config", "/api/auth/me"):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ("/api/auth/login", "/api/auth/register", "/api/media-jobs"):
            self.assertEqual(self.client.post(path, json={}).status_code, 401, path)
        for asset in ("app.js", "app.css", "admin.js", "fx.js", "index.html"):
            self.assertEqual(self.client.get(f"/static/{asset}").status_code, 404, asset)
        gate_asset = self.client.get("/static/gate.js?v=1")
        self.assertEqual(gate_asset.status_code, 200)
        self.assertTrue(gate_asset.headers["cache-control"].startswith("public"))
        gate = self.client.get("/login")
        self.assertEqual(gate.status_code, 200)
        self.assertIn("/static/gate.js", gate.text)
        self.assertNotIn("/static/app.js", gate.text)
        robots = self.client.get("/robots.txt")
        self.assertIn("Disallow: /", robots.text)
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})

    def test_signed_in_assets_are_never_publicly_cacheable(self) -> None:
        for path in ("/static/app.js?v=7", "/static/app.js", "/static/admin.css?v=7"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.headers["cache-control"].startswith("private"), path)
        self.assertEqual(self.client.get("/").headers["cache-control"], "private, no-cache")
        self.assertEqual(self.client.get("/login", follow_redirects=False).status_code, 303)

    def test_cross_site_writes_are_refused(self) -> None:
        refused = self.client.post(
            "/api/auth/logout-all",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["detail"]["reason"], "invalid_origin")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_activation_code_signs_in_and_bad_codes_lock_the_address(self) -> None:
        self.client.cookies.clear()
        for attempt in range(4):
            response = self.client.post("/api/auth/activate", json={"code": "ABCDE-FGHJK-MNPQR-STVWX"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"]["reason"], "invalid_code")
            self.assertEqual(response.json()["detail"]["attempts_left"], 4 - attempt)
        locked = self.client.post("/api/auth/activate", json={"code": "not-a-code"})
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(locked.json()["detail"]["reason"], "gate_locked")
        self.assertGreater(int(locked.headers["retry-after"]), 800)
        still_locked = self.client.post("/api/auth/activate", json={"code": self.code})
        self.assertEqual(still_locked.status_code, 429)
        overview = access.gate_overview()
        self.assertEqual(overview["summary"]["locked"][0]["ip"], "testclient")

        self.assertEqual(access.unlock_address("testclient"), 5)
        typed = self.code.lower().replace("-", " ")
        granted = self.client.post("/api/auth/activate", json={"code": typed})
        self.assertEqual(granted.status_code, 200)
        self.assertEqual(granted.json()["user"], {"label": "integration", "role": "member"})
        cookie = granted.headers["set-cookie"]
        self.assertIn("__Host-caption_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("samesite=lax", cookie.lower())
        self.assertNotIn("Domain=", cookie)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.headers["cache-control"], "private, no-store")
        user = me.json()["user"]
        self.assertEqual(user["label"], "integration")
        self.assertFalse(user["is_admin"])
        self.assertEqual(user["code_hint"], access.normalize_code(self.code)[-4:])
        self.assertEqual(user["quota"]["limit"], 30)
        self.assertNotIn(access.normalize_code(self.code), me.text)
        self.assertEqual(access.gate_overview()["events"][0]["kind"], "granted")

    def test_codes_are_stored_only_as_keyed_hashes(self) -> None:
        normalized = access.normalize_code(self.code)
        with auth.connect() as connection:
            stored = [bytes(row[0]) for row in connection.execute("SELECT code_hash FROM access_codes")]
        self.assertEqual(stored, [access.code_digest(normalized)])
        database = Path(os.environ["AUTH_DB_PATH"]).read_bytes()
        self.assertNotIn(normalized.encode(), database)
        self.assertNotIn(self.code.encode(), database)
        self.assertEqual(oct((Path(os.environ["AUTH_DB_PATH"]).parent / "access-pepper").stat().st_mode & 0o777), "0o600")

    def test_revoked_disabled_or_expired_codes_end_existing_sessions(self) -> None:
        member = self.member_id("integration")
        new_code = access.reset_code(member)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        old = self.client.post("/api/auth/activate", json={"code": self.code})
        self.assertEqual(old.status_code, 403)
        self.assertEqual(old.json()["detail"]["reason"], "code_revoked")
        self.assertEqual(self.client.post("/api/auth/activate", json={"code": new_code}).status_code, 200)

        access.update_member(member, active=False)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        disabled = self.client.post("/api/auth/activate", json={"code": new_code})
        self.assertEqual(disabled.json()["detail"]["reason"], "code_revoked")

        access.update_member(member, active=True)
        access.unlock_address("testclient")
        self.assertEqual(self.client.post("/api/auth/activate", json={"code": new_code}).status_code, 200)
        with auth.connect() as connection:
            connection.execute("UPDATE access_codes SET expires_at = ?", (int(time.time()) - 1,))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        expired = self.client.post("/api/auth/activate", json={"code": new_code})
        self.assertEqual(expired.json()["detail"]["reason"], "code_expired")

    def test_device_limit_evicts_the_oldest_session(self) -> None:
        access.update_member(self.member_id("integration"), max_devices=2)
        laptop = TestClient(main.app, base_url="https://testserver")
        phone = TestClient(main.app, base_url="https://testserver")
        for client in (laptop, phone):
            self.assertEqual(client.post("/api/auth/activate", json={"code": self.code}).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(laptop.get("/api/auth/me").status_code, 200)
        me = phone.get("/api/auth/me").json()["user"]
        self.assertEqual((me["active_sessions"], me["max_devices"]), (2, 2))
        logged_out = phone.post("/api/auth/logout-all")
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(laptop.get("/api/auth/me").status_code, 401)

    def test_member_daily_quota_and_active_job_limit(self) -> None:
        member = self.member_id("integration")
        access.update_member(member, daily_job_limit=1)
        result = main.subtitle_result_payload([main.SubtitleEntry(0, 1, "hello")], {"title": "quota"}, "txt")
        with patch.object(main, "cached_extraction_payload", return_value=result):
            first = self.client.post("/api/jobs", json={"input": "BV14jFvzbEvj"}, headers={"Idempotency-Key": "quota-key-0001"})
            again = self.client.post("/api/jobs", json={"input": "BV14jFvzbEvj"}, headers={"Idempotency-Key": "quota-key-0001"})
            blocked = self.client.post("/api/jobs", json={"input": "BV1xx411c7mD"})
        self.assertEqual((first.status_code, again.status_code), (202, 202))
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"]["reason"], "daily_quota_reached")
        self.assertEqual(access.quota_status(member)["used"], 1)

        access.update_member(member, daily_job_limit=0)
        with patch.object(main.JOB_MANAGER, "owner_stats", return_value={"queued": 1, "running": 1}):
            busy = self.client.post("/api/jobs", json={"input": "BV1xx411c7mD"})
        self.assertEqual(busy.status_code, 429)
        self.assertEqual(busy.json()["detail"]["reason"], "member_busy")
        self.assertEqual(access.quota_status(member)["used"], 1)

    def test_owner_console_issues_codes_once_and_protects_the_owner(self) -> None:
        self.assertEqual(self.client.get("/api/admin/members").status_code, 403)
        self.assertEqual(self.client.post("/api/admin/members", json={"label": "x"}).status_code, 403)
        self.sign_in("boss", role="owner")
        created = self.client.post(
            "/api/admin/members",
            json={"label": "小王", "expires_in_days": 7, "max_devices": 1, "daily_job_limit": 5},
        )
        self.assertEqual(created.status_code, 201)
        code = created.json()["code"]
        self.assertIsNotNone(access.normalize_code(code))
        listing = self.client.get("/api/admin/members")
        self.assertEqual(listing.headers["cache-control"], "private, no-store")
        self.assertNotIn(code, listing.text)
        self.assertNotIn(access.normalize_code(code), listing.text)
        self.assertNotIn("hash", listing.text)
        members = {item["label"]: item for item in listing.json()["members"]}
        self.assertEqual(list(members)[0], "boss")
        friend = members["小王"]
        self.assertEqual((friend["max_devices"], friend["daily_job_limit"], friend["state"]), (1, 5, "active"))
        self.assertGreater(friend["code"]["expires_at"], time.time() + 6 * 86400)
        boss = members["boss"]
        self.assertIsNone(boss["daily_job_limit"])
        protected = self.client.patch(f"/api/admin/members/{boss['id']}", json={"active": False})
        self.assertEqual(protected.status_code, 400)
        self.assertEqual(protected.json()["detail"]["reason"], "owner_protected")
        self.assertEqual(self.client.delete(f"/api/admin/members/{boss['id']}").status_code, 400)

        renamed = self.client.patch(f"/api/admin/members/{friend['id']}", json={"label": "老王", "daily_job_limit": None})
        self.assertEqual(renamed.status_code, 200)
        updated = {item["label"]: item for item in self.client.get("/api/admin/members").json()["members"]}["老王"]
        self.assertEqual(updated["daily_job_limit"], 30)
        reset = self.client.post(f"/api/admin/members/{friend['id']}/reset").json()["code"]
        self.assertNotEqual(reset, code)
        self.assertEqual(self.client.delete(f"/api/admin/members/{friend['id']}").status_code, 200)
        gate = self.client.get("/api/admin/gate").json()
        self.assertGreaterEqual(gate["summary"]["granted_24h"], 2)
        self.assertEqual(self.client.post("/api/admin/gate/unlock", json={"ip": "203.0.113.9"}).json()["cleared"], 0)

    def test_bilibili_login_is_owner_only_and_used_for_every_request(self) -> None:
        self.assertEqual(self.client.post("/api/admin/bilibili/qrcode").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/bilibili").status_code, 403)
        self.assertEqual(self.client.get("/api/login/qrcode").status_code, 404)
        self.assertFalse(main.cookie_allowed(True))
        main.BILI_COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
        main.save_bili_cookie("SESSDATA=secret-session; bili_jct=secret-csrf")
        try:
            self.assertTrue(main.cookie_allowed(False))
            config = self.client.get("/api/client-config").json()
            self.assertTrue(config["features"]["bilibili_login"])
            self.assertTrue(config["platform_status"]["bilibili"]["signed_in"])
            self.assertNotIn("secret", json.dumps(config))

            self.sign_in("boss", role="owner")
            nav = {"code": 0, "data": {"isLogin": True, "uname": "测试账号", "mid": 42,
                                       "level_info": {"current_level": 6}, "vipStatus": 1,
                                       "vip_label": {"text": "年度大会员"}}}
            with patch.object(main, "api_get_json", return_value=nav) as fetched:
                status = self.client.get("/api/admin/bilibili?refresh=true").json()
            self.assertEqual((status["state"], status["uname"], status["level"]), ("ok", "测试账号", 6))
            self.assertTrue(fetched.call_args.kwargs["allow_cookie"])
            self.assertNotIn("secret", json.dumps(status))
            with patch.object(main.httpx, "Client", side_effect=RuntimeError("offline")):
                removed = self.client.delete("/api/admin/bilibili")
            self.assertEqual(removed.json(), {"ok": True, "remote_signed_out": False})
            self.assertFalse(main.BILI_COOKIE_PATH.exists())
            self.assertFalse(main.cookie_allowed(True))
            self.assertEqual(self.client.get("/api/admin/bilibili").json()["state"], "none")
        finally:
            main.BILI_COOKIE_PATH.unlink(missing_ok=True)
            os.environ.pop("BILI_COOKIE", None)

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
            response = self.client.get("/api/client-config")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["platforms"]["douyin"])

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

    def test_upload_endpoint_defaults_to_balanced_chinese(self) -> None:
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
        self.assertEqual(request.quality, "balanced")
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

        self.sign_in("integration2")
        forbidden = self.client.get(job["result"]["download_url"])
        self.assertEqual(forbidden.status_code, 404)
        forbidden_job = self.client.get(f"/api/jobs/{job['id']}")
        self.assertEqual(forbidden_job.status_code, 404)

    def test_cloud_modes_require_explicit_server_side_consent(self) -> None:
        denied = self.client.post(
            "/api/jobs",
            json={
                "input": "BV14jFvzbEvj",
                "format": "txt",
                "asr_mode": "high_accuracy",
            },
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["detail"]["reason"], "cloud_consent_required")

        cached = {
            "ok": True,
            "format": "txt",
            "filename": "cloud.txt",
            "content_type": "text/plain; charset=utf-8",
            "metadata": {"platform": "bilibili", "source": "asr_aliyun"},
            "content": "cloud transcript",
        }
        with patch.object(main, "cached_extraction_payload", return_value=cached):
            allowed = self.client.post(
                "/api/jobs",
                json={
                    "input": "BV14jFvzbEvj",
                    "format": "txt",
                    "asr_mode": "high_accuracy",
                    "cloud_consent": True,
                },
            )
        self.assertEqual(allowed.status_code, 202)
        self.assertEqual(allowed.json()["status"], "completed")

        upload_denied = self.client.post(
            "/api/upload-jobs?filename=clip.mp4&asr_mode=economy",
            content=b"video",
        )
        self.assertEqual(upload_denied.status_code, 409)
        self.assertEqual(upload_denied.json()["detail"]["reason"], "cloud_consent_required")

    def test_versioned_static_assets_are_cacheable_but_media_is_not(self) -> None:
        versioned = self.client.get("/static/app.js?v=20260727-3")
        plain = self.client.get("/static/app.js")
        self.assertEqual(versioned.status_code, 200)
        self.assertEqual(versioned.headers["cache-control"], "private, max-age=31536000, immutable")
        self.assertEqual(plain.headers.get("cache-control"), "private, no-cache")


class FrontendRecoveryTests(unittest.TestCase):
    def test_admin_frontend_uses_safe_rendering_and_unix_seconds(self) -> None:
        page = (main.STATIC_DIR / "admin.html").read_text(encoding="utf-8")
        script = (main.STATIC_DIR / "admin.js").read_text(encoding="utf-8")

        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("innerHTML", script)
        self.assertNotRegex(page, r"\sstyle=")
        self.assertNotRegex(page, r"<script(?![^>]+\bsrc=)")
        for endpoint in ("/api/admin/members", "/api/admin/gate", "/api/admin/bilibili/qrcode", "/api/admin/diagnostics"):
            self.assertIn(endpoint, script)
        self.assertIn("new Date(timestamp * 1000)", script)
        self.assertIn('id="code-value"', page)
        self.assertIn("只显示这一次", page)

    def test_frontend_defaults_to_local_balanced_chinese_with_platform_subtitles(self) -> None:
        page = (main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('name="asr-mode" value="auto" checked', page)
        self.assertIn('name="asr-mode" value="high_accuracy"', page)
        self.assertIn('name="asr-mode" value="economy"', page)
        self.assertIn('id="allow-platform-ai" type="checkbox" role="switch" checked', page)
        self.assertIn('<option value="zh" selected>中文</option>', page)
        self.assertIn('asr_mode: selectedAsrMode()', script)
        self.assertIn('return "balanced"', script)
        self.assertIn('payload.allow_platform_ai !== false', script)
        self.assertIn('X-ASR-Hotwords', script)
        self.assertIn("本地均衡", page)
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

        self.assertIn('class="beta-badge">Private<', page)
        for element_id in (
            "health-trigger",
            "health-popover",
            "mobile-tab-compose",
            "mobile-tab-result",
            "retry-accurate",
            "stage-track",
            "result-search",
            "toggle-wrap",
            "new-task",
            "open-history",
            "history-drawer",
            "theme-toggle",
            "view-segments",
            "view-source",
            "segment-list",
            "platform-notice",
            "account-popover",
            "account-quota",
            "open-command",
            "signal-canvas",
            "segment-timeline",
            "cloud-mode-zone",
            "cloud-confirm-dialog",
            "link-input-panel",
            "upload-input-panel",
        ):
            self.assertIn(f'id="{element_id}"', page)
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("function renderOutputContent()", script)
        self.assertIn("function updateStageTrack(", script)
        self.assertIn("function retryAccurate()", script)
        self.assertIn("function submitCurrentForm()", script)
        for retired in ("guest", "changeAccountPassword", "/api/public-config", "use_cookie", "/api/login/"):
            self.assertNotIn(retired, script)
            self.assertNotIn(retired, page)
        self.assertIn("/static/app.js?v=20261106-2", page)
        self.assertIn("/static/fx.js?v=20261106-2", page)
        self.assertIn("/static/theme.js?v=20261106-2", page)
        self.assertIn('id="result-format"', page)
        self.assertIn("function setHistoryDrawer(", script)
        self.assertIn("function renderSegments(", script)
        local_ready_block = script.split("function isLocalAsrReady()", 1)[1].split(
            "function syncPrecisionOptions", 1
        )[0]
        self.assertIn("state.capabilities.features.local_processing", local_ready_block)
        self.assertIn('autoBackend === "local"', script)
        self.assertIn('state.capabilities.asr_modes.auto.available', script)
        self.assertIn('apiFetch("/api/client-config"', script)
        self.assertIn("cloud_consent: true", script)
        submit_block = script.split("function submitCurrentForm()", 1)[1].split(
            "elements.form.addEventListener", 1
        )[0]
        self.assertLess(submit_block.index("validateInput()"), submit_block.index("requestCloudConfirmation"))
        self.assertLess(submit_block.index("validateUpload()"), submit_block.index("requestCloudConfirmation"))
        self.assertIn("uploads.max_bytes", script)
        self.assertIn("body.dialog-open", css)
        self.assertNotRegex(script, r"\bstate\.health\b")
        self.assertNotIn("meta.asr_model", script)
        self.assertNotIn("asr_provider_seconds", script)
        self.assertNotIn("estimated_cost_cny", script)
        self.assertNotIn("4C / 4G", page)
        self.assertNotIn("单机任务队列", page)
        for internal_field in (
            "free_bytes",
            "process_rss_mb",
            "swap_used_mb",
            "asr_worker_warm",
            "staging_reserved_bytes",
        ):
            self.assertNotIn(internal_field, script)

        example = (main.STATIC_DIR.parent.parent / ".env.example").read_text(encoding="utf-8")
        for setting in ("MEMBER_DAILY_JOB_LIMIT=", "MEMBER_MAX_ACTIVE_JOBS=", "ACCESS_MAX_DEVICES=",
                        "BILI_MIN_INTERVAL_SECONDS="):
            self.assertIn(setting, example)
        for retired in ("GUEST_", "INVITE_CODE_HASH", "WEB_QR_LOGIN_ENABLED"):
            self.assertNotIn(retired, example)

    def test_user_preferences_exclude_links_and_hotwords(self) -> None:
        script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
        preference_block = script.split("function savePreferences()", 1)[1].split(
            "function removeLegacyHistory", 1
        )[0]
        active_job_block = script.split("function saveActiveJob()", 1)[1].split(
            "function restoreForm", 1
        )[0]

        self.assertNotIn("elements.input", preference_block)
        self.assertNotIn("hotwords", preference_block)
        self.assertIn("delete persistedPayload.hotwords", active_job_block)

    def test_gate_page_is_self_contained_and_only_talks_to_activate(self) -> None:
        page = (main.STATIC_DIR / "gate.html").read_text(encoding="utf-8")
        script = (main.STATIC_DIR / "gate.js").read_text(encoding="utf-8")

        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotRegex(page, r"\sstyle=")
        self.assertNotRegex(page, r"<script(?![^>]+\bsrc=)")
        self.assertIn('id="code"', page)
        self.assertIn('name="robots" content="noindex, nofollow"', page)
        assets = set(re.findall(r'(?:src|href)="(/static/[^"?]+)', page))
        self.assertEqual(assets, set(main.GATE_STATIC) - {"/static/theme.js"})
        self.assertEqual(re.findall(r'fetch\("([^"]+)"', script), ["/api/auth/activate"])
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("localStorage", script)


if __name__ == "__main__":
    unittest.main()
