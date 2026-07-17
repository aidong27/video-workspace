import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class ResultCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_dir = main.RESULT_CACHE_DIR
        self.original_ttl = main.RESULT_CACHE_TTL_SECONDS
        self.original_max = main.RESULT_CACHE_MAX_ITEMS
        main.RESULT_CACHE_DIR = Path(self.tmp.name)
        main.RESULT_CACHE_TTL_SECONDS = 3600
        main.RESULT_CACHE_MAX_ITEMS = 10
        main.RESULT_KEY_LOCKS.clear()

    def tearDown(self) -> None:
        main.RESULT_CACHE_DIR = self.original_dir
        main.RESULT_CACHE_TTL_SECONDS = self.original_ttl
        main.RESULT_CACHE_MAX_ITEMS = self.original_max
        main.RESULT_KEY_LOCKS.clear()
        self.tmp.cleanup()

    def test_cache_key_ignores_output_format_and_refresh_flag(self) -> None:
        first = main.ExtractRequest(input="BV14jFvzbEvj", format="txt")
        second = main.ExtractRequest(input="BV14jFvzbEvj", format="srt", force_refresh=True)
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        self.assertEqual(main.result_cache_key(first, canonical), main.result_cache_key(second, canonical))

    def test_cache_key_separates_fast_accurate_and_video_ocr(self) -> None:
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        fast = main.ExtractRequest(input=canonical, quality="fast", source="asr")
        accurate = fast.model_copy(update={"quality": "accurate"})
        embedded = fast.model_copy(update={"embedded_subtitles": True})

        keys = {
            main.result_cache_key(fast, canonical),
            main.result_cache_key(accurate, canonical),
            main.result_cache_key(embedded, canonical),
        }

        self.assertEqual(len(keys), 3)
        self.assertEqual(main.effective_quality("fast", embedded_subtitles=True), "accurate")
        self.assertEqual(main.asr_profile("fast")["model"], main.DEFAULT_ASR_MODEL)
        self.assertEqual(main.asr_profile("accurate")["model"], main.ACCURATE_ASR_MODEL)

    def test_cached_entries_round_trip(self) -> None:
        entries = [main.SubtitleEntry(0.25, 1.5, "测试字幕")]
        metadata = {"title": "测试", "source": "asr_local"}
        main.save_cached_result("a" * 64, entries, metadata)
        loaded = main.load_cached_result("a" * 64)
        self.assertIsNotNone(loaded)
        loaded_entries, loaded_metadata, age = loaded
        self.assertEqual(loaded_entries[0].text, "测试字幕")
        self.assertEqual(loaded_metadata["title"], "测试")
        self.assertGreaterEqual(age, 0)

    def test_second_format_uses_cached_raw_entries(self) -> None:
        entries = [main.SubtitleEntry(0, 1, "第一句"), main.SubtitleEntry(1, 2, "第二句")]
        metadata = {"title": "视频", "source": "asr_local", "attempts": []}
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        with patch.object(main, "normalize_input", return_value=canonical), patch.object(
            main, "extract_subtitle_uncached", return_value=(entries, metadata)
        ) as extract:
            txt, txt_meta, _ = main.extract_subtitle(main.ExtractRequest(input=canonical, format="txt"))
            srt, srt_meta, _ = main.extract_subtitle(main.ExtractRequest(input=canonical, format="srt"))

        self.assertEqual(extract.call_count, 1)
        self.assertIn("第一句", txt)
        self.assertIn("00:00:00,000 --> 00:00:01,000", srt)
        self.assertFalse(txt_meta["cache_hit"])
        self.assertTrue(srt_meta["cache_hit"])

    def test_submission_fast_path_renders_cached_format_without_queue_work(self) -> None:
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        request = main.ExtractRequest(input=canonical, format="srt")
        key = main.result_cache_key(request, canonical)
        main.save_cached_result(
            key,
            [main.SubtitleEntry(0, 1, "缓存字幕")],
            {"title": "快速结果", "source": "asr_local", "platform": "bilibili"},
        )

        payload = main.cached_extraction_payload(request, canonical)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["format"], "srt")
        self.assertIn("00:00:00,000 --> 00:00:01,000", payload["content"])
        self.assertTrue(payload["metadata"]["cache_hit"])
        self.assertEqual(payload["metadata"]["entry_count"], 1)

    def test_submission_fast_path_never_waits_on_active_cache_writer(self) -> None:
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        request = main.ExtractRequest(input=canonical)
        key = main.result_cache_key(request, canonical)
        with main.result_key_guard(key):
            self.assertIsNone(main.cached_extraction_payload(request, canonical))
        self.assertNotIn(key, main.RESULT_KEY_LOCKS)

    def test_cleanup_enforces_item_limit(self) -> None:
        main.RESULT_CACHE_MAX_ITEMS = 2
        for index in range(3):
            path = main.RESULT_CACHE_DIR / f"{index}.json"
            path.write_text(f'{{"version":{main.RESULT_CACHE_VERSION}}}', encoding="utf-8")
            modified = time.time() - (10 - index)
            os.utime(path, (modified, modified))
        removed = main.cleanup_result_cache()
        self.assertEqual(removed, 1)
        self.assertEqual(len(list(main.RESULT_CACHE_DIR.glob("*.json"))), 2)

    def test_cleanup_removes_old_cache_version(self) -> None:
        path = main.RESULT_CACHE_DIR / "old.json"
        path.write_text('{"version":1}', encoding="utf-8")
        removed = main.cleanup_result_cache()
        self.assertEqual(removed, 1)
        self.assertFalse(path.exists())


class UploadExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_tmp = main.ASR_TMP_DIR
        self.original_cache = main.RESULT_CACHE_DIR
        main.ASR_TMP_DIR = self.root / "tmp"
        main.RESULT_CACHE_DIR = self.root / "results"
        main.ASR_TMP_DIR.mkdir(parents=True)
        main.RESULT_CACHE_DIR.mkdir(parents=True)
        main.RESULT_KEY_LOCKS.clear()
        with main.UPLOAD_RESERVATION_LOCK:
            main.UPLOAD_RESERVATIONS.clear()

    def tearDown(self) -> None:
        main.ASR_TMP_DIR = self.original_tmp
        main.RESULT_CACHE_DIR = self.original_cache
        main.RESULT_KEY_LOCKS.clear()
        with main.UPLOAD_RESERVATION_LOCK:
            main.UPLOAD_RESERVATIONS.clear()
        self.tmp.cleanup()

    def staged_request(self, token: str = "a" * 32, filename: str = "会议录像.mp4") -> main.UploadJobRequest:
        directory = main.ASR_TMP_DIR / f"asr-upload-{token}"
        directory.mkdir()
        media = directory / "source.mp4"
        media.write_bytes(b"video-data")
        with main.UPLOAD_RESERVATION_LOCK:
            main.UPLOAD_RESERVATIONS[token] = media.stat().st_size
        return main.UploadJobRequest(
            upload_token=token,
            stored_name="source.mp4",
            filename=filename,
            sha256="b" * 64,
            size=media.stat().st_size,
            format="srt",
            lang="zh",
        )

    def test_upload_job_transcribes_and_removes_staged_video(self) -> None:
        request = self.staged_request()
        directory = main.ASR_TMP_DIR / f"asr-upload-{request.upload_token}"
        updates = []
        with patch.object(main, "ensure_asr_ready"), patch.object(
            main,
            "probe_uploaded_media",
            return_value={"duration": 12.5, "format_name": "mov,mp4"},
        ), patch.object(
            main,
            "normalize_audio_for_asr",
            side_effect=lambda path, *_args, **_kwargs: path,
        ), patch.object(
            main,
            "transcribe_audio",
            return_value=([main.SubtitleEntry(0, 1.5, "测试字幕")], {"detected_language": "zh"}),
        ):
            result = main.process_queued_job(
                request.model_dump(mode="json"),
                lambda stage, progress, message: updates.append((stage, progress, message)),
            )

        self.assertEqual(result["format"], "srt")
        self.assertIn("00:00:00,000 --> 00:00:01,500", result["content"])
        self.assertEqual(result["metadata"]["platform"], "upload")
        self.assertEqual(result["metadata"]["original_filename"], "会议录像.mp4")
        self.assertFalse(directory.exists())
        self.assertNotIn(request.upload_token, main.UPLOAD_RESERVATIONS)
        self.assertTrue(any(stage == "transcribe" for stage, _, _ in updates))

    def test_upload_cache_identity_uses_content_not_filename_or_format(self) -> None:
        first = self.staged_request(token="c" * 32, filename="first.mp4")
        second = first.model_copy(update={"filename": "second.mp4", "format": "json", "force_refresh": True})
        self.assertEqual(main.upload_result_cache_key(first), main.upload_result_cache_key(second))

    def test_long_upload_filename_preserves_supported_extension(self) -> None:
        filename, extension = main.safe_upload_filename(f"{'x' * 240}.MP4")
        self.assertEqual(extension, ".mp4")
        self.assertTrue(filename.endswith(".mp4"))
        self.assertLessEqual(len(filename), 180)

    def test_media_probe_rejects_video_without_audio(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": '{"streams":[{"codec_type":"video","duration":"3"}],"format":{"duration":"3"}}',
                "stderr": "",
            },
        )()
        with patch.object(main.shutil, "which", return_value="/usr/bin/ffprobe"), patch.object(
            main.subprocess,
            "run",
            return_value=completed,
        ), self.assertRaises(main.ExtractionFailure) as raised:
            main.probe_uploaded_media(self.root / "video.mp4")
        self.assertEqual(raised.exception.reason, "upload_audio_missing")

    def test_media_probe_accepts_silent_video_for_embedded_subtitles(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": '{"streams":[{"index":0,"codec_type":"video","duration":"3"}],"format":{"duration":"3"}}',
                "stderr": "",
            },
        )()
        with patch.object(main.shutil, "which", return_value="/usr/bin/ffprobe"), patch.object(
            main.subprocess,
            "run",
            return_value=completed,
        ):
            result = main.probe_uploaded_media(self.root / "silent.mp4", require_audio=False)
        self.assertFalse(result["has_audio"])

    def test_embedded_upload_does_not_require_or_run_asr(self) -> None:
        request = self.staged_request(token="9" * 32).model_copy(
            update={"quality": "fast", "embedded_subtitles": True}
        )
        entries = [main.SubtitleEntry(0.5, 2.0, "画面字幕")]
        with patch.object(
            main,
            "probe_uploaded_media",
            return_value={"duration": 6.0, "format_name": "matroska", "has_audio": False, "subtitle_streams": []},
        ), patch.object(
            main,
            "extract_video_subtitle_pixels",
            return_value=(entries, {"subtitle_source": "embedded_text_track", "subtitle_stream_language": "zh"}),
        ), patch.object(main, "transcribe_audio") as transcribe:
            result = main.process_queued_job(request.model_dump(mode="json"), lambda *_args: None)

        transcribe.assert_not_called()
        self.assertEqual(result["metadata"]["source"], "embedded_text")
        self.assertEqual(result["metadata"]["quality"], "accurate")
        self.assertIn("画面字幕", result["content"])

    def test_embedded_upload_falls_back_to_accurate_asr_after_ocr_failure(self) -> None:
        request = self.staged_request(token="8" * 32).model_copy(
            update={"quality": "fast", "embedded_subtitles": True}
        )
        directory = main.ASR_TMP_DIR / f"asr-upload-{request.upload_token}"
        with patch.object(
            main,
            "probe_uploaded_media",
            return_value={
                "duration": 6.0,
                "format_name": "matroska",
                "has_audio": True,
                "subtitle_streams": [],
            },
        ), patch.object(
            main,
            "extract_video_subtitle_pixels",
            return_value=(
                [],
                {
                    "subtitle_source": "burned_in_ocr",
                    "ocr_failed": True,
                    "ocr_failure_reason": "ocr_failed",
                },
            ),
        ), patch.object(main, "ensure_asr_ready"), patch.object(
            main,
            "normalize_audio_for_asr",
            side_effect=lambda path, *_args, **_kwargs: path,
        ), patch.object(
            main,
            "transcribe_audio",
            return_value=([main.SubtitleEntry(0, 1.5, "ASR 补救字幕")], {"detected_language": "zh"}),
        ) as transcribe:
            result = main.process_queued_job(request.model_dump(mode="json"), lambda *_args: None)

        self.assertEqual(transcribe.call_args.args[2], "accurate")
        self.assertTrue(result["metadata"]["ocr_fallback_to_asr"])
        self.assertEqual(result["metadata"]["ocr_failure_reason"], "ocr_failed")
        self.assertIn("ASR 补救字幕", result["content"])
        self.assertFalse(directory.exists())

    def test_startup_cleanup_removes_fresh_orphaned_upload(self) -> None:
        request = self.staged_request(token="d" * 32)
        directory = main.ASR_TMP_DIR / f"asr-upload-{request.upload_token}"
        self.assertEqual(main.cleanup_stale_asr_tmp(), 1)
        self.assertFalse(directory.exists())
        self.assertNotIn(request.upload_token, main.UPLOAD_RESERVATIONS)

    def test_failed_upload_cleanup_keeps_the_reservation_visible(self) -> None:
        request = self.staged_request(token="e" * 32)
        directory = main.ASR_TMP_DIR / f"asr-upload-{request.upload_token}"
        with patch.object(main.shutil, "rmtree", side_effect=PermissionError("denied")), self.assertLogs(
            "app.main", level="ERROR"
        ):
            main.discard_upload_payload(request.model_dump(mode="json"))

        self.assertTrue(directory.exists())
        self.assertIn(request.upload_token, main.UPLOAD_RESERVATIONS)


class MediaArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original = (
            main.MEDIA_ARTIFACT_DIR,
            main.MEDIA_MAX_BYTES,
            main.MEDIA_STAGING_MAX_BYTES,
            main.MEDIA_ARTIFACT_TTL_SECONDS,
        )
        main.MEDIA_ARTIFACT_DIR = self.root / "artifacts"
        main.MEDIA_MAX_BYTES = 1024
        main.MEDIA_STAGING_MAX_BYTES = 2048
        main.MEDIA_ARTIFACT_TTL_SECONDS = 3600
        with main.MEDIA_RESERVATION_LOCK:
            main.MEDIA_RESERVATIONS.clear()

    def tearDown(self) -> None:
        (
            main.MEDIA_ARTIFACT_DIR,
            main.MEDIA_MAX_BYTES,
            main.MEDIA_STAGING_MAX_BYTES,
            main.MEDIA_ARTIFACT_TTL_SECONDS,
        ) = self.original
        with main.MEDIA_RESERVATION_LOCK:
            main.MEDIA_RESERVATIONS.clear()
        self.tmp.cleanup()

    def test_media_job_keeps_owner_scoped_artifact_until_discard(self) -> None:
        token = "f" * 32
        main.reserve_media_artifact(token)
        request = main.MediaJobRequest(
            input="https://www.bilibili.com/video/BV14jFvzbEvj",
            media_type="video",
            artifact_token=token,
            owner_id=7,
        )

        def fake_download(_request, target_dir):
            target_dir.mkdir(parents=True, exist_ok=True)
            source = target_dir / "source.mp4"
            source.write_bytes(b"source-video")
            return source, {
                "id": "BV14jFvzbEvj",
                "title": "测试视频",
                "duration": 12,
                "webpage_url": request.input,
                "source_container": "mp4",
            }

        def fake_prepare(source, _media_type, artifact_dir):
            final = artifact_dir / "artifact.mp4"
            final.write_bytes(b"final-video")
            source.unlink()
            return final, "video/mp4"

        with patch.object(main, "download_bilibili_media", side_effect=fake_download), patch.object(
            main,
            "prepare_media_output",
            side_effect=fake_prepare,
        ):
            result = main.process_queued_job(request.model_dump(mode="json"), lambda *_args: None)

        self.assertEqual(result["kind"], "media")
        self.assertEqual(result["media_type"], "video")
        self.assertEqual(result["size"], len(b"final-video"))
        path, metadata = main.load_media_artifact(token, owner_id=7)
        self.assertEqual(path.read_bytes(), b"final-video")
        self.assertEqual(metadata["owner_id"], 7)
        with self.assertRaises(HTTPException) as raised:
            main.load_media_artifact(token, owner_id=8)
        self.assertEqual(raised.exception.status_code, 404)

        main.discard_job_payload(request.model_dump(mode="json"))
        self.assertFalse(main.media_artifact_directory(token).exists())
        self.assertEqual(main.media_staging_bytes(), 0)

    def test_media_reservation_enforces_total_quota(self) -> None:
        main.MEDIA_MAX_BYTES = 10
        main.MEDIA_STAGING_MAX_BYTES = 10
        main.reserve_media_artifact("a" * 32)
        with self.assertRaises(HTTPException) as raised:
            main.reserve_media_artifact("b" * 32)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.detail["reason"], "media_storage_busy")


class BilibiliSelectionTests(unittest.TestCase):
    def test_direct_video_uses_compatible_highest_dash_streams(self) -> None:
        request = main.MediaJobRequest(
            input="https://www.bilibili.com/video/BV14jFvzbEvj",
            media_type="video",
            artifact_token="1" * 32,
            owner_id=1,
        )
        play = {
            "data": {
                "dash": {
                    "video": [
                        {"height": 1080, "codecid": 12, "bandwidth": 200, "baseUrl": "https://cdn/hevc"},
                        {"height": 1080, "codecid": 7, "bandwidth": 180, "baseUrl": "https://cdn/avc"},
                        {"height": 720, "codecid": 7, "bandwidth": 100, "baseUrl": "https://cdn/720"},
                    ],
                    "audio": [
                        {"bandwidth": 64, "baseUrl": "https://cdn/audio-low"},
                        {"bandwidth": 128, "baseUrl": "https://cdn/audio-high"},
                    ],
                }
            }
        }
        selected_urls = []

        def fake_stream(urls, target, *_args, **_kwargs):
            selected_urls.append(urls[0])
            target.write_bytes(b"stream")
            return len(b"stream")

        def fake_merge(_video, _audio, target, _deadline):
            target.write_bytes(b"merged-video")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            main,
            "bili_view_context",
            return_value=(
                "BV14jFvzbEvj",
                request.input,
                {"title": "测试", "duration": 10, "owner": {"name": "UP"}},
                {"duration": 10},
                123,
            ),
        ), patch.object(main, "api_get_json", return_value=play), patch.object(
            main,
            "download_bilibili_stream",
            side_effect=fake_stream,
        ), patch.object(main, "merge_bilibili_dash", side_effect=fake_merge):
            path, metadata = main.download_bilibili_media_api(request, Path(directory))

        self.assertEqual(selected_urls, ["https://cdn/audio-high", "https://cdn/avc"])
        self.assertEqual(path.name, "source.mp4")
        self.assertEqual(metadata["media_download"], "bilibili_playurl")

    def test_normalize_preserves_selected_page(self) -> None:
        value = "https://www.bilibili.com/video/BV14jFvzbEvj?p=2&utm_source=test"
        self.assertEqual(
            main.normalize_input(value),
            "https://www.bilibili.com/video/BV14jFvzbEvj?p=2",
        )

    def test_page_is_part_of_cache_identity(self) -> None:
        request = main.ExtractRequest(input="BV14jFvzbEvj")
        first = main.normalize_input("https://www.bilibili.com/video/BV14jFvzbEvj?p=1")
        second = main.normalize_input("https://www.bilibili.com/video/BV14jFvzbEvj?p=2")
        self.assertNotEqual(main.result_cache_key(request, first), main.result_cache_key(request, second))

    def test_view_source_uses_requested_page_cid_and_duration(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "title": "分P测试",
                "duration": 30,
                "owner": {"name": "UP"},
                "pages": [
                    {"cid": 101, "duration": 10, "part": "第一集"},
                    {"cid": 202, "duration": 20, "part": "第二集"},
                ],
            },
        }
        with patch.object(main, "api_get_json", return_value=payload):
            bvid, canonical, data, selected, cid = main.bili_view_context(
                "https://www.bilibili.com/video/BV14jFvzbEvj?p=2"
            )
            source = main.view_source("https://www.bilibili.com/video/BV14jFvzbEvj?p=2")

        self.assertEqual(bvid, "BV14jFvzbEvj")
        self.assertEqual(canonical, "https://www.bilibili.com/video/BV14jFvzbEvj?p=2")
        self.assertEqual(cid, 202)
        self.assertEqual(selected["part"], "第二集")
        self.assertEqual(data["title"], "分P测试")
        self.assertEqual(source.duration, 20)
        self.assertIn("P2", source.title)

    def test_out_of_range_page_is_rejected(self) -> None:
        payload = {"code": 0, "data": {"pages": [{"cid": 101}]}}
        with patch.object(main, "api_get_json", return_value=payload), self.assertRaises(
            main.ExtractionFailure
        ) as raised:
            main.bili_view_context("https://www.bilibili.com/video/BV14jFvzbEvj?p=2")
        self.assertEqual(raised.exception.reason, "invalid_page")

    def test_language_alias_prefers_requested_chinese_track(self) -> None:
        tracks = [
            main.SubtitleTrack("official", "en", "json", "https://example.invalid/en"),
            main.SubtitleTrack("official", "zh-Hans", "json", "https://example.invalid/zh"),
        ]
        selected = main.choose_track(tracks, "zh", allow_platform_ai=True)
        self.assertEqual(selected.language, "zh-Hans")

    def test_default_language_beats_source_type(self) -> None:
        tracks = [
            main.SubtitleTrack("official", "en", "json", "https://example.invalid/en"),
            main.SubtitleTrack("platform_ai", "zh-CN", "json", "https://example.invalid/zh"),
        ]
        selected = main.choose_track(tracks, None, allow_platform_ai=True)
        self.assertEqual(selected.language, "zh-CN")

    def test_expired_download_deadline_is_terminal_for_attempt(self) -> None:
        with self.assertRaises(main.ExtractionFailure) as raised:
            main.remaining_before(time.monotonic() - 1, "download")
        self.assertEqual(raised.exception.status_code, 504)


class BilibiliCookiePersistenceTests(unittest.TestCase):
    def test_qr_cookie_is_written_to_service_owned_runtime_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_path = main.BILI_COOKIE_PATH
            original_values = {
                key: os.environ.get(key)
                for key in ("BILI_COOKIE", "BILI_SESSDATA", "BILI_JCT", "BILI_BUVID3")
            }
            main.BILI_COOKIE_PATH = Path(directory) / "auth" / "bili-cookie.txt"
            try:
                main.save_bili_cookie("SESSDATA=test; bili_jct=value")
                self.assertEqual(main.configured_cookie_header(), "SESSDATA=test; bili_jct=value")
                self.assertEqual(main.BILI_COOKIE_PATH.stat().st_mode & 0o777, 0o600)
            finally:
                main.BILI_COOKIE_PATH = original_path
                for key, original in original_values.items():
                    if original is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original


class BilibiliCookieFallbackTests(unittest.TestCase):
    def test_auto_asr_fallback_keeps_requested_cookie(self) -> None:
        request = main.ExtractRequest(input="BV14jFvzbEvj", source="auto", use_cookie=True)
        anonymous_failure = main.ExtractionFailure(
            404,
            "No anonymous subtitle.",
            "no_official_subtitle",
            can_try_asr=True,
        )
        cookie_failure = main.ExtractionFailure(
            404,
            "No cookie subtitle.",
            "no_official_subtitle",
            can_try_asr=True,
        )
        entries = [main.SubtitleEntry(0, 1, "识别字幕")]
        metadata = {"source": "asr_local", "attempts": []}

        with patch.object(main, "cookie_allowed", return_value=True), patch.object(
            main,
            "official_subtitle",
            side_effect=[anonymous_failure, cookie_failure],
        ), patch.object(main, "asr_subtitle", return_value=(entries, metadata)) as asr:
            result_entries, result_metadata = main.extract_subtitle_uncached(request)

        asr.assert_called_once_with(
            request,
            allow_cookie=True,
            prior_note=cookie_failure.detail,
        )
        self.assertEqual(result_entries, entries)
        self.assertEqual(
            [attempt["source"] for attempt in result_metadata["attempts"]],
            ["official_no_cookie", "official_with_cookie"],
        )


class RenderingTests(unittest.TestCase):
    def test_unicode_filename_is_preserved_and_sanitized(self) -> None:
        self.assertEqual(main.safe_filename("标题：测试/01", "markdown"), "标题：测试_01.md")

    def test_invalid_transcription_result_becomes_public_failure(self) -> None:
        with self.assertRaises(main.ExtractionFailure) as raised:
            main.parse_transcription_result({"ok": False, "error": "decode failed"})
        self.assertEqual(raised.exception.reason, "asr_failed")

    def test_invalid_input_keeps_structured_error(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            main.extract_subtitle_data(main.ExtractRequest(input="not-a-video"))
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["reason"], "invalid_input")

    def test_srt_parser_accepts_numbered_cues(self) -> None:
        entries = main.parse_subtitle_text(
            "1\n00:00:01,250 --> 00:00:03,500\n第一句\n\n2\n00:00:04,000 --> 00:00:05,000\n第二句\n",
            "srt",
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].start, 1.25)
        self.assertEqual(entries[1].text, "第二句")

    def test_vtt_parser_accepts_cue_settings(self) -> None:
        entries = main.parse_subtitle_text(
            "WEBVTT\n\n00:01.000 --> 00:03.200 align:start\nHello\n",
            "vtt",
        )
        self.assertEqual(len(entries), 1)
        self.assertAlmostEqual(entries[0].end, 3.2)

    def test_douyin_json_utterances_use_milliseconds(self) -> None:
        entries = main.parse_json_subtitle(
            '{"utterances":[{"start_time":1250,"end_time":2750,"text":"测试"}]}'
        )
        self.assertEqual(entries[0].start, 1.25)
        self.assertEqual(entries[0].end, 2.75)

    def test_douyin_input_is_detected(self) -> None:
        value = "https://www.douyin.com/video/6961737553342991651"
        self.assertEqual(main.normalize_input(value), value)
        self.assertEqual(main.detect_platform(value), "douyin")

    def test_qrcode_key_is_redacted_from_urls(self) -> None:
        redacted = main.redact_sensitive("https://example.test/poll?qrcode_key=abc123&next=1")
        self.assertNotIn("abc123", redacted)
        self.assertIn("qrcode_key=<redacted>", redacted)


class AsrWorkerTests(unittest.TestCase):
    def test_one_shot_worker_reads_result_before_joining_process(self) -> None:
        events: list[str] = []

        class FakeQueue:
            def get(self, timeout: float):
                self.timeout = timeout
                events.append("get")
                return {
                    "ok": True,
                    "entries": [(0.0, 1.0, "识别结果")],
                    "meta": {"model": "tiny"},
                }

            def close(self) -> None:
                events.append("close")

        class FakeProcess:
            exitcode = 0

            def __init__(self) -> None:
                self.alive = True

            def start(self) -> None:
                events.append("start")

            def join(self, timeout: float) -> None:
                self.timeout = timeout
                if "get" not in events:
                    raise AssertionError("joining before reading can deadlock on a full queue pipe")
                events.append("join")
                self.alive = False

            def is_alive(self) -> bool:
                return self.alive

            def kill(self) -> None:
                events.append("kill")
                self.alive = False

        fake_queue = FakeQueue()
        fake_process = FakeProcess()

        class FakeContext:
            def Queue(self, maxsize: int):
                self.maxsize = maxsize
                return fake_queue

            def Process(self, **_kwargs):
                return fake_process

        with patch.object(main, "get_context", return_value=FakeContext()):
            entries, metadata = main.transcribe_audio_once(Path("audio.wav"), "zh", "fast")

        self.assertEqual(entries[0].text, "识别结果")
        self.assertFalse(metadata["asr_worker_reused"])
        self.assertLess(events.index("get"), events.index("join"))
        self.assertIn("close", events)

    def test_one_shot_worker_closes_queue_when_process_creation_fails(self) -> None:
        closed = []

        class FakeQueue:
            def close(self) -> None:
                closed.append(True)

        class FakeContext:
            def Queue(self, maxsize: int):
                self.maxsize = maxsize
                return FakeQueue()

            def Process(self, **_kwargs):
                raise RuntimeError("process creation failed")

        with patch.object(main, "get_context", return_value=FakeContext()), self.assertRaises(RuntimeError):
            main.transcribe_audio_once(Path("audio.wav"), "zh", "fast")

        self.assertEqual(closed, [True])


class VideoSubtitleOcrTests(unittest.TestCase):
    def test_rapidocr_numpy_style_boxes_are_accepted(self) -> None:
        class ArrayLike:
            def __iter__(self):
                return iter([[[10, 20], [120, 20], [120, 52], [10, 52]]])

            def __bool__(self):
                raise ValueError("array truth value is ambiguous")

        result = type(
            "RapidResult",
            (),
            {"txts": ("测试字幕",), "scores": (0.99,), "boxes": ArrayLike()},
        )()

        lines = main.ocr_lines_from_result(result)

        self.assertEqual(lines[0]["text"], "测试字幕")

    def test_ocr_timeline_filters_static_watermark_and_merges_frames(self) -> None:
        frames = []
        for index in range(20):
            caption = "第一句字幕" if index < 10 else "第二句字幕"
            frames.append(
                {
                    "time": index / 2,
                    "lines": [
                        {"text": caption, "score": 0.92, "x": 120, "y": 80},
                        {"text": "@fixed-watermark", "score": 0.99, "x": 10, "y": 120},
                    ],
                }
            )

        entries = main.build_ocr_entries(frames, sample_fps=2)

        self.assertEqual([entry.text for entry in entries], ["第一句字幕", "第二句字幕"])
        self.assertNotIn("watermark", "".join(entry.text for entry in entries))
        self.assertLess(entries[0].start, entries[0].end)
        self.assertLessEqual(entries[0].end, entries[1].start)

    def test_ocr_timeline_keeps_a_single_long_lived_caption(self) -> None:
        frames = [
            {
                "time": index / 2,
                "lines": [{"text": "请阅读这条长时间字幕", "score": 0.98, "x": 120, "y": 80}],
            }
            for index in range(20)
        ]

        entries = main.build_ocr_entries(frames, sample_fps=2)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].text, "请阅读这条长时间字幕")

    def test_embedded_text_track_prefers_requested_language(self) -> None:
        media_info = {
            "subtitle_streams": [
                {"index": 3, "codec_name": "subrip", "language": "en", "title": "English"},
                {"index": 5, "codec_name": "ass", "language": "zh", "title": "Chinese"},
            ]
        }

        def fake_run(command, **_kwargs):
            target = Path(command[-1])
            target.write_text("1\n00:00:00,000 --> 00:00:01,000\n中文字幕\n", encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stderr": ""})()

        with tempfile.TemporaryDirectory() as directory, patch.object(
            main.shutil,
            "which",
            return_value="/usr/bin/ffmpeg",
        ), patch.object(main.subprocess, "run", side_effect=fake_run) as run:
            result = main.extract_embedded_text_subtitle(
                Path(directory) / "video.mkv",
                media_info,
                Path(directory),
                "zh",
            )

        self.assertIsNotNone(result)
        entries, metadata = result
        self.assertEqual(entries[0].text, "中文字幕")
        self.assertEqual(metadata["subtitle_stream_index"], 5)
        self.assertIn("0:5", run.call_args.args[0])
        self.assertIn(main.LOCAL_MEDIA_PROTOCOL_WHITELIST, run.call_args.args[0])

    def test_burned_subtitle_worker_does_not_pipe_ffmpeg_stderr(self) -> None:
        class EmptyStream:
            def read(self, _size: int) -> bytes:
                return b""

        class FakeProcess:
            pid = 321
            stdout = EmptyStream()

            def wait(self, timeout: float) -> int:
                self.timeout = timeout
                return 0

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                pass

        class FakeQueue:
            def __init__(self) -> None:
                self.messages = []

            def put(self, value) -> None:
                self.messages.append(value)

        class FakeRapidOcr:
            def __init__(self, **_kwargs) -> None:
                pass

        fake_module = type("RapidOcrModule", (), {"RapidOCR": FakeRapidOcr})()
        queue = FakeQueue()
        with patch.dict("sys.modules", {"rapidocr": fake_module}), patch.object(
            main.subprocess,
            "Popen",
            return_value=FakeProcess(),
        ) as popen:
            main.burned_subtitle_ocr_worker("video.mp4", 2.0, queue)

        command = popen.call_args.args[0]
        self.assertIn(main.LOCAL_MEDIA_PROTOCOL_WHITELIST, command)
        self.assertEqual(popen.call_args.kwargs["stderr"], main.subprocess.DEVNULL)
        self.assertTrue(any(message.get("ok") for message in queue.messages if message.get("kind") == "result"))

    def test_ocr_failure_falls_back_when_video_has_audio(self) -> None:
        failure = main.ExtractionFailure(502, "OCR failed", "ocr_failed")
        with patch.object(main, "extract_embedded_text_subtitle", return_value=None), patch.object(
            main,
            "extract_burned_subtitles",
            side_effect=failure,
        ):
            entries, metadata = main.extract_video_subtitle_pixels(
                Path("video.mp4"),
                {"duration": 3.0, "has_audio": True, "subtitle_streams": []},
                Path("."),
                "zh",
            )

        self.assertEqual(entries, [])
        self.assertTrue(metadata["ocr_failed"])
        self.assertEqual(metadata["ocr_failure_reason"], "ocr_failed")

    def test_ocr_failure_is_terminal_when_video_has_no_audio(self) -> None:
        failure = main.ExtractionFailure(502, "OCR failed", "ocr_failed")
        with patch.object(main, "extract_embedded_text_subtitle", return_value=None), patch.object(
            main,
            "extract_burned_subtitles",
            side_effect=failure,
        ), self.assertRaises(main.ExtractionFailure) as raised:
            main.extract_video_subtitle_pixels(
                Path("video.mp4"),
                {"duration": 3.0, "has_audio": False, "subtitle_streams": []},
                Path("."),
                "zh",
            )

        self.assertEqual(raised.exception.reason, "ocr_failed")

    def test_ocr_releases_shared_slot_when_process_creation_fails(self) -> None:
        class FakeSemaphore:
            def __init__(self) -> None:
                self.releases = 0

            def acquire(self, **_kwargs) -> bool:
                return True

            def release(self) -> None:
                self.releases += 1

        semaphore = FakeSemaphore()
        with patch.object(main, "ASR_SEMAPHORE", semaphore), patch.object(
            main.shutil,
            "which",
            return_value="/usr/bin/ffmpeg",
        ), patch.object(main.importlib.util, "find_spec", return_value=object()), patch.object(
            main,
            "get_context",
            side_effect=RuntimeError("spawn unavailable"),
        ), self.assertRaises(RuntimeError):
            main.extract_burned_subtitles(Path("video.mp4"), 2.0)

        self.assertEqual(semaphore.releases, 1)


if __name__ == "__main__":
    unittest.main()
