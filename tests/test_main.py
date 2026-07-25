import asyncio
import json
import os
from pathlib import Path
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.asr.base import AsrProviderError, Transcript, TranscriptSegment
from app.asr.mock import MockAsrProvider
from app.asr.signing import SignedAudioStore
from app.asr.usage import UsageLedger


class RequestDefaultsTests(unittest.TestCase):
    def test_linux_memory_parser_ignores_invalid_fields(self) -> None:
        parsed = main.parse_linux_memory_kib(
            "VmRSS: 153600 kB\nVmSwap: 2048 kB\nBroken: unavailable\n"
        )

        self.assertEqual(parsed["VmRSS"], 153600)
        self.assertEqual(parsed["VmSwap"], 2048)
        self.assertNotIn("Broken", parsed)

    def test_subtitle_requests_default_to_platform_first_local_settings(self) -> None:
        request = main.ExtractRequest(input="BV14jFvzbEvj")

        self.assertEqual(request.source, "auto")
        self.assertEqual(request.quality, "accurate")
        self.assertEqual(request.lang, "zh")
        self.assertTrue(request.allow_platform_ai)
        self.assertEqual(request.asr_mode, "auto")

    def test_auto_prefers_local_while_explicit_advanced_modes_use_cloud(self) -> None:
        with patch.object(main, "local_asr_enabled", return_value=True), patch.object(
            main,
            "cloud_asr_enabled",
            return_value=True,
        ):
            self.assertEqual(main.selected_asr_backend("auto"), "local")
            self.assertEqual(main.selected_asr_backend("high_accuracy"), "cloud")
            self.assertEqual(main.selected_asr_backend("economy"), "cloud")
        with patch.object(main, "local_asr_enabled", return_value=True), patch.object(
            main,
            "cloud_asr_enabled",
            return_value=False,
        ):
            self.assertEqual(main.selected_asr_backend("auto"), "local")
            self.assertIsNone(main.selected_asr_backend("high_accuracy"))
            self.assertIsNone(main.selected_asr_backend("economy"))
            with self.assertRaises(main.ExtractionFailure) as unavailable:
                main.ensure_selected_asr_ready("high_accuracy")
            self.assertEqual(
                unavailable.exception.reason,
                "asr_provider_not_configured",
            )

    def test_asr_dispatch_uses_selected_backend(self) -> None:
        request = main.ExtractRequest(input="BV14jFvzbEvj")
        local_result = ([main.SubtitleEntry(0, 1, "local")], {"source": "asr_local"})
        cloud_result = ([main.SubtitleEntry(0, 1, "cloud")], {"source": "asr_aliyun"})
        with patch.object(main, "local_asr_enabled", return_value=True), patch.object(
            main,
            "cloud_asr_enabled",
            return_value=True,
        ), patch.object(
            main,
            "local_asr_subtitle",
            return_value=local_result,
        ) as local, patch.object(
            main,
            "cloud_asr_subtitle",
            return_value=cloud_result,
        ) as cloud:
            self.assertEqual(main.asr_subtitle(request, False), local_result)
            local.assert_called_once()
            cloud.assert_not_called()

            advanced = request.model_copy(update={"asr_mode": "high_accuracy"})
            self.assertEqual(main.asr_subtitle(advanced, False), cloud_result)
            cloud.assert_called_once()


class CloudAsrPipelineTests(unittest.TestCase):
    def test_cloud_configuration_refuses_unbounded_free_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "CLOUD_ASR_ENABLED": "true",
                "ASR_ALLOW_PAID": "false",
                "DASHSCOPE_API_KEY": "test-key",
                "DASHSCOPE_BASE_URL": "https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1",
                "DASHSCOPE_WORKSPACE_ID": "ws-test",
                "AUDIO_SIGNING_SECRET": "s" * 32,
                "PUBLIC_BASE_URL": "https://caption.example.test",
            },
        ), patch.object(
            main, "CLOUD_ASR_MONTHLY_FREE_SECONDS", 0
        ), patch.object(
            main, "CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS", 100
        ), patch.object(
            main, "CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS", 100
        ), patch.object(
            main, "CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS", 100
        ), patch.object(
            main, "CLOUD_ASR_USAGE_DB_PATH", Path(directory) / "usage.db"
        ):
            try:
                with self.assertLogs("app.main", level="ERROR") as captured:
                    main.initialize_cloud_services()
                self.assertEqual(main.CLOUD_ASR_INIT_ERROR, "ValueError")
                self.assertIsNone(main.CLOUD_SIGNED_AUDIO_STORE)
                self.assertNotIn("test-key", "\n".join(captured.output))
            finally:
                main.CLOUD_ASR_INIT_ERROR = None
                main.CLOUD_SIGNED_AUDIO_STORE = None
                main.CLOUD_TEMP_FILE_UPLOADER = None
                main.CLOUD_USAGE_LEDGER = None

    def test_cloud_configuration_supports_aliyun_temp_without_public_audio_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "CLOUD_ASR_ENABLED": "true",
                "ASR_ALLOW_PAID": "false",
                "DASHSCOPE_API_KEY": "test-key",
                "DASHSCOPE_BASE_URL": "https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1",
                "DASHSCOPE_WORKSPACE_ID": "ws-test",
                "AUDIO_SIGNING_SECRET": "",
                "PUBLIC_BASE_URL": "",
            },
        ), patch.object(
            main, "CLOUD_ASR_AUDIO_DELIVERY", "aliyun_temp"
        ), patch.object(
            main, "CLOUD_ASR_MONTHLY_FREE_SECONDS", 1000
        ), patch.object(
            main, "CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS", 900
        ), patch.object(
            main, "CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS", 900
        ), patch.object(
            main, "CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS", 100
        ), patch.object(
            main, "CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS", 60
        ), patch.object(
            main, "CLOUD_ASR_USAGE_DB_PATH", Path(directory) / "usage.db"
        ):
            try:
                main.initialize_cloud_services()

                self.assertIsNone(main.CLOUD_ASR_INIT_ERROR)
                self.assertIsNone(main.CLOUD_SIGNED_AUDIO_STORE)
                self.assertIsNotNone(main.CLOUD_TEMP_FILE_UPLOADER)
                self.assertIsNotNone(main.CLOUD_USAGE_LEDGER)
                self.assertTrue(main.cloud_audio_delivery_ready())
            finally:
                main.close_cloud_providers()
                main.CLOUD_ASR_INIT_ERROR = None
                main.CLOUD_SIGNED_AUDIO_STORE = None
                main.CLOUD_USAGE_LEDGER = None

    def test_cloud_pipeline_records_usage_and_revokes_signed_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            store = SignedAudioStore(
                root=root,
                public_base_url="https://caption.example.test",
                secret="s" * 32,
            )
            ledger = UsageLedger(
                root / "usage.db",
                daily_limit_seconds=100,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=60,
            )
            provider = MockAsrProvider(
                Transcript(
                    provider="aliyun",
                    model="qwen3-asr-flash-filetrans",
                    language="zh",
                    duration_ms=5500,
                    provider_seconds=5.5,
                    segments=[
                        TranscriptSegment(0, 1200, "测试字幕"),
                        TranscriptSegment(1000, 1800, "测试字幕"),
                    ],
                )
            )
            with patch.object(main, "CLOUD_ASR_AUDIO_DELIVERY", "signed_url"), patch.object(
                main, "CLOUD_SIGNED_AUDIO_STORE", store
            ), patch.object(
                main, "CLOUD_USAGE_LEDGER", ledger
            ), patch.object(main, "ensure_cloud_asr_ready"), patch.object(
                main,
                "prepare_audio_for_cloud",
                return_value=(
                    audio,
                    {
                        "duration": 5.5,
                        "size": 5,
                        "format_name": "mp3",
                        "codec_name": "mp3",
                        "channels": 1,
                        "sample_rate": 16000,
                    },
                ),
            ), patch.object(
                main, "cloud_provider_for_mode", return_value=provider
            ), main.extraction_owner(7):
                entries, metadata = main.transcribe_media_with_cloud(
                    audio,
                    root,
                    language="zh",
                    mode="auto",
                )

            self.assertEqual([entry.text for entry in entries], ["测试字幕"])
            self.assertEqual(metadata["provider_seconds"], 5.5)
            self.assertEqual(metadata["asr_mode"], "high_accuracy")
            self.assertEqual(metadata["audio_delivery"], "signed_url")
            self.assertEqual(metadata["provider_temporary_retention_seconds"], 0)
            self.assertGreater(metadata["estimated_cost_cny"], 0)
            self.assertEqual(store.records, {})
            self.assertEqual(ledger.stats()["daily_seconds"], 5.5)

    def test_cloud_pipeline_rejects_before_provider_when_quota_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            store = SignedAudioStore(
                root=root,
                public_base_url="https://caption.example.test",
                secret="s" * 32,
            )
            ledger = UsageLedger(
                root / "usage.db",
                daily_limit_seconds=2,
                monthly_limit_seconds=2,
                user_daily_limit_seconds=2,
            )
            provider = MockAsrProvider(
                Transcript("aliyun", "qwen", "zh", 5000, [])
            )
            with patch.object(main, "CLOUD_ASR_AUDIO_DELIVERY", "signed_url"), patch.object(
                main, "CLOUD_SIGNED_AUDIO_STORE", store
            ), patch.object(
                main, "CLOUD_USAGE_LEDGER", ledger
            ), patch.object(main, "ensure_cloud_asr_ready"), patch.object(
                main,
                "prepare_audio_for_cloud",
                return_value=(
                    audio,
                    {
                        "duration": 5,
                        "size": 5,
                        "format_name": "mp3",
                        "codec_name": "mp3",
                        "channels": 1,
                        "sample_rate": 16000,
                    },
                ),
            ), patch.object(
                main, "cloud_provider_for_mode", return_value=provider
            ), self.assertRaises(main.ExtractionFailure) as raised:
                main.transcribe_media_with_cloud(audio, root, language="zh", mode="auto")

            self.assertEqual(raised.exception.reason, "asr_daily_limit_reached")
            self.assertEqual(provider.submissions, [])
            self.assertEqual(store.records, {})

    def test_cloud_pipeline_uses_aliyun_temporary_upload_and_releases_failures(self) -> None:
        class TemporaryUploader:
            def __init__(self, failure: AsrProviderError | None = None) -> None:
                self.failure = failure
                self.calls: list[tuple[Path, str]] = []

            def upload(self, path: Path, *, model: str) -> str:
                self.calls.append((path, model))
                if self.failure is not None:
                    raise self.failure
                return "oss://dashscope-instant/test/random.mp3"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.mp3"
            audio.write_bytes(b"audio")
            ledger = UsageLedger(
                root / "usage.db",
                daily_limit_seconds=100,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=60,
            )
            provider = MockAsrProvider(
                Transcript(
                    provider="aliyun",
                    model="qwen3-asr-flash-filetrans",
                    language="zh",
                    duration_ms=5000,
                    provider_seconds=5,
                    segments=[TranscriptSegment(0, 1200, "临时上传测试")],
                )
            )
            uploader = TemporaryUploader()
            preparation = (
                audio,
                {
                    "duration": 5,
                    "size": 5,
                    "format_name": "mp3",
                    "codec_name": "mp3",
                    "channels": 1,
                    "sample_rate": 16000,
                },
            )
            with patch.object(main, "CLOUD_ASR_AUDIO_DELIVERY", "aliyun_temp"), patch.object(
                main, "CLOUD_TEMP_FILE_UPLOADER", uploader
            ), patch.object(main, "CLOUD_SIGNED_AUDIO_STORE", None), patch.object(
                main, "CLOUD_USAGE_LEDGER", ledger
            ), patch.object(main, "ensure_cloud_asr_ready"), patch.object(
                main, "prepare_audio_for_cloud", return_value=preparation
            ), patch.object(
                main, "cloud_provider_for_mode", return_value=provider
            ):
                entries, metadata = main.transcribe_media_with_cloud(
                    audio,
                    root,
                    language="zh",
                    mode="high_accuracy",
                )

            self.assertEqual(entries[0].text, "临时上传测试")
            self.assertEqual(
                provider.submissions[0]["file_url"],
                "oss://dashscope-instant/test/random.mp3",
            )
            self.assertEqual(uploader.calls[0][1], main.CLOUD_ASR_DEFAULT_MODEL)
            self.assertEqual(metadata["audio_delivery"], "aliyun_temp")
            self.assertEqual(
                metadata["provider_temporary_retention_seconds"],
                48 * 60 * 60,
            )

            failed_uploader = TemporaryUploader(
                AsrProviderError(
                    "asr_temp_upload_failed",
                    "upload failed",
                    retryable=False,
                )
            )
            failure_ledger = UsageLedger(
                root / "failed-usage.db",
                daily_limit_seconds=100,
                monthly_limit_seconds=1000,
                user_daily_limit_seconds=60,
            )
            with patch.object(main, "CLOUD_ASR_AUDIO_DELIVERY", "aliyun_temp"), patch.object(
                main, "CLOUD_TEMP_FILE_UPLOADER", failed_uploader
            ), patch.object(main, "CLOUD_USAGE_LEDGER", failure_ledger), patch.object(
                main, "ensure_cloud_asr_ready"
            ), patch.object(
                main, "prepare_audio_for_cloud", return_value=preparation
            ), patch.object(
                main, "cloud_provider_for_mode", return_value=provider
            ), self.assertRaises(main.ExtractionFailure) as raised:
                main.transcribe_media_with_cloud(
                    audio,
                    root,
                    language="zh",
                    mode="high_accuracy",
                )

            self.assertEqual(raised.exception.reason, "asr_temp_upload_failed")
            self.assertEqual(failure_ledger.stats()["reserved_seconds"], 0)
            self.assertEqual(failure_ledger.stats()["daily_seconds"], 0)

    def test_upload_requests_use_the_same_quality_and_language_defaults(self) -> None:
        request = main.UploadJobRequest(
            upload_token="a" * 32,
            stored_name="source.mp4",
            filename="clip.mp4",
            sha256="b" * 64,
            size=123,
        )

        self.assertEqual(request.quality, "accurate")
        self.assertEqual(request.lang, "zh")
        self.assertEqual(request.asr_mode, "auto")


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

    def test_cache_key_separates_cloud_provider_modes(self) -> None:
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        high_accuracy = main.ExtractRequest(
            input=canonical,
            source="asr",
            asr_mode="high_accuracy",
        )
        economy = high_accuracy.model_copy(update={"asr_mode": "economy"})

        self.assertNotEqual(
            main.result_cache_key(high_accuracy, canonical),
            main.result_cache_key(economy, canonical),
        )

    def test_cache_key_includes_hashed_hotwords_and_audio_filter(self) -> None:
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        first = main.ExtractRequest(input=canonical, source="asr", hotwords="MQTT, ESP32")
        second = first.model_copy(update={"hotwords": "LoRa, Node-RED"})

        with patch.dict(os.environ, {"ASR_AUDIO_FILTER": ""}):
            first_key = main.result_cache_key(first, canonical)
            second_key = main.result_cache_key(second, canonical)
        with patch.dict(os.environ, {"ASR_AUDIO_FILTER": "highpass=f=70"}):
            filtered_key = main.result_cache_key(first, canonical)

        self.assertNotEqual(first_key, second_key)
        self.assertNotEqual(first_key, filtered_key)

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

    def test_corrupt_cache_file_is_deleted_before_recalculation(self) -> None:
        key = "f" * 64
        path = main.result_cache_path(key)
        path.write_text("{broken-json", encoding="utf-8")

        self.assertIsNone(main.load_cached_result(key))
        self.assertFalse(path.exists())

    def test_concurrent_force_refresh_runs_recognition_once(self) -> None:
        canonical = "https://www.bilibili.com/video/BV14jFvzbEvj"
        request = main.ExtractRequest(input=canonical, force_refresh=True)
        entered = Event()
        release = Event()
        calls = []
        results = []

        def extract(_request):
            calls.append(True)
            entered.set()
            release.wait(2)
            return [main.SubtitleEntry(0, 1, "并发结果")], {
                "title": "并发测试",
                "source": "asr_local",
                "platform": "bilibili",
            }

        def run() -> None:
            results.append(main.extract_subtitle_data(request))

        with patch.object(main, "normalize_input", return_value=canonical), patch.object(
            main, "extract_subtitle_uncached", side_effect=extract
        ):
            first = Thread(target=run)
            second = Thread(target=run)
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            time.sleep(0.05)
            release.set()
            first.join(2)
            second.join(2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(bool(meta["cache_hit"]) for _, meta in results), 1)


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
        request = self.staged_request().model_copy(update={"hotwords": "MQTT, ESP32"})
        directory = main.ASR_TMP_DIR / f"asr-upload-{request.upload_token}"
        updates = []
        with patch.object(main, "local_asr_enabled", return_value=True), patch.object(
            main, "ensure_asr_ready"
        ), patch.object(
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
        ) as transcribe:
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
        self.assertIn("会议录像", transcribe.call_args.args[3])
        self.assertEqual(transcribe.call_args.args[4], "MQTT, ESP32")

    def test_upload_cache_reuses_formats_but_includes_filename_prompt(self) -> None:
        first = self.staged_request(token="c" * 32, filename="first.mp4")
        second = first.model_copy(update={"format": "json", "force_refresh": True})
        renamed = first.model_copy(update={"filename": "different-topic.mp4"})
        self.assertEqual(main.upload_result_cache_key(first), main.upload_result_cache_key(second))
        self.assertNotEqual(main.upload_result_cache_key(first), main.upload_result_cache_key(renamed))

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
            main,
            "run_managed_process",
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
            main,
            "run_managed_process",
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
        ), patch.object(main, "local_asr_enabled", return_value=True), patch.object(
            main, "ensure_asr_ready"
        ), patch.object(
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

    def test_interrupted_stream_upload_removes_partial_file_and_reservation(self) -> None:
        class InterruptedRequest:
            headers = {"content-length": "4"}

            async def stream(self):
                yield b"ab"
                raise main.ClientDisconnect()

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                main.stage_uploaded_video(
                    InterruptedRequest(),
                    filename="clip.mp4",
                    output_format="txt",
                    lang=None,
                    quality="fast",
                    embedded_subtitles=False,
                    force_refresh=False,
                )
            )

        self.assertEqual(raised.exception.detail["reason"], "upload_interrupted")
        self.assertEqual(list(main.ASR_TMP_DIR.glob("asr-upload-*")), [])
        self.assertEqual(main.upload_staging_bytes(), 0)

    def test_cancelled_upload_request_removes_partial_file_and_reservation(self) -> None:
        class CancelledRequest:
            headers = {"content-length": "4"}

            async def stream(self):
                yield b"ab"
                raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(
                main.stage_uploaded_video(
                    CancelledRequest(),
                    filename="clip.mp4",
                    output_format="txt",
                    lang=None,
                    quality="fast",
                    embedded_subtitles=False,
                    force_refresh=False,
                )
            )

        self.assertEqual(list(main.ASR_TMP_DIR.glob("asr-upload-*")), [])
        self.assertEqual(main.upload_staging_bytes(), 0)

    def test_streaming_size_limit_removes_partial_upload(self) -> None:
        class OversizedRequest:
            headers = {}

            async def stream(self):
                yield b"12345"

        original_limits = main.UPLOAD_MAX_BYTES, main.UPLOAD_STAGING_MAX_BYTES
        main.UPLOAD_MAX_BYTES = 4
        main.UPLOAD_STAGING_MAX_BYTES = 8
        try:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    main.stage_uploaded_video(
                        OversizedRequest(),
                        filename="clip.mp4",
                        output_format="txt",
                        lang=None,
                        quality="fast",
                        embedded_subtitles=False,
                        force_refresh=False,
                    )
                )
        finally:
            main.UPLOAD_MAX_BYTES, main.UPLOAD_STAGING_MAX_BYTES = original_limits

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(list(main.ASR_TMP_DIR.glob("asr-upload-*")), [])
        self.assertEqual(main.upload_staging_bytes(), 0)


class LocalMediaFixtureTests(unittest.TestCase):
    @unittest.skipUnless(main.shutil.which("ffmpeg") and main.shutil.which("ffprobe"), "FFmpeg is unavailable")
    def test_ffprobe_validates_a_small_real_video_with_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.mp4"
            result = main.run_managed_process(
                [
                    main.shutil.which("ffmpeg") or "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=32x32:r=2:d=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=1",
                    "-shortest",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    str(path),
                ],
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            metadata = main.probe_uploaded_media(path)

        self.assertTrue(metadata["has_audio"])
        self.assertGreater(metadata["duration"], 0)


class ResourceSafetyTests(unittest.TestCase):
    def test_audio_normalization_applies_only_the_configured_filter(self) -> None:
        def fake_run(command, **_kwargs):
            Path(command[-1]).write_bytes(b"wav")
            return type("Completed", (), {"returncode": 0, "stderr": ""})()

        audio_filter = "highpass=f=70,lowpass=f=7800,loudnorm=I=-20:TP=-2:LRA=11"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"media")
            with patch.dict(os.environ, {"ASR_AUDIO_FILTER": audio_filter}), patch.object(
                main.shutil, "which", return_value="/usr/bin/ffmpeg"
            ), patch.object(main, "ensure_disk_space"), patch.object(
                main, "run_managed_process", side_effect=fake_run
            ) as run:
                normalized = main.normalize_audio_for_asr(source, root, "test")

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-af") + 1], audio_filter)
        self.assertTrue(normalized.name.endswith(".asr.wav"))

    def test_isolated_ytdlp_spawn_failure_is_diagnostic_and_closes_queue(self) -> None:
        closed: list[str] = []

        class FakeQueue:
            def cancel_join_thread(self) -> None:
                closed.append("cancel")

            def close(self) -> None:
                closed.append("close")

        class FakeContext:
            def Queue(self, maxsize: int):
                self.maxsize = maxsize
                return FakeQueue()

            def Process(self, **_kwargs):
                raise RuntimeError("spawn unavailable")

        with patch.object(main, "get_context", return_value=FakeContext()), self.assertRaises(
            main.ExtractionFailure
        ) as raised:
            main.run_isolated_ytdlp_download(
                url="https://www.bilibili.com/video/av123456",
                target_dir=Path("."),
                mode="audio",
                allow_cookie=False,
                max_bytes=1024,
                timeout_seconds=1,
            )

        self.assertEqual(raised.exception.reason, "download_failed")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(closed, ["cancel", "close"])

    def test_isolated_ytdlp_timeout_stops_owned_process_group(self) -> None:
        class FakeQueue:
            def __init__(self) -> None:
                self.messages = [{"kind": "started", "group_owned": True}]

            def get(self, timeout: float):
                self.timeout = timeout
                return self.messages.pop(0)

            def cancel_join_thread(self) -> None:
                pass

            def close(self) -> None:
                pass

        class FakeProcess:
            pid = 4321

            def __init__(self) -> None:
                self.alive = True

            def start(self) -> None:
                pass

            def is_alive(self) -> bool:
                return self.alive

            def join(self, _timeout=0) -> None:
                pass

        queue = FakeQueue()
        process = FakeProcess()

        class FakeContext:
            def Queue(self, maxsize: int):
                self.maxsize = maxsize
                return queue

            def Process(self, **_kwargs):
                return process

        def stop_group(target, group_owned):
            self.assertIs(target, process)
            self.assertTrue(group_owned)
            process.alive = False

        with patch.object(main, "get_context", return_value=FakeContext()), patch.object(
            main.time, "monotonic", side_effect=[0.0, 0.1, 2.0]
        ), patch.object(main, "terminate_child_process_group", side_effect=stop_group) as stop, self.assertRaises(
            main.ExtractionFailure
        ) as raised:
            main.run_isolated_ytdlp_download(
                url="https://www.bilibili.com/video/av123456",
                target_dir=Path("."),
                mode="media",
                media_type="video",
                allow_cookie=False,
                max_bytes=1024,
                timeout_seconds=1,
            )

        self.assertEqual(raised.exception.status_code, 504)
        stop.assert_called_once()

    def test_low_disk_rejects_upload_before_reservation(self) -> None:
        status = main.DiskSpaceStatus(
            total_bytes=10_000,
            free_bytes=100,
            free_ratio=0.01,
            minimum_free_bytes=1_000,
            required_bytes=500,
            available=False,
        )
        token = "1" * 32
        with main.UPLOAD_RESERVATION_LOCK:
            main.UPLOAD_RESERVATIONS.clear()
        with patch.object(main, "disk_space_status", return_value=status), self.assertRaises(
            HTTPException
        ) as raised:
            main.reserve_upload(token, 500)

        self.assertEqual(raised.exception.status_code, 507)
        self.assertEqual(raised.exception.detail["code"], "disk_space_low")
        self.assertNotIn(token, main.UPLOAD_RESERVATIONS)

    def test_public_error_uses_stable_code_without_internal_detail(self) -> None:
        failure = main.ExtractionFailure(
            422,
            "failed at /opt/private/video.mp4 Cookie: SESSDATA=secret",
            "upload_audio_missing",
        )

        detail = main.extraction_error_detail("upload", failure)

        self.assertEqual(detail["reason"], "upload_audio_missing")
        self.assertEqual(detail["code"], "no_audio_stream")
        self.assertNotIn("/opt/private", detail["message"])
        self.assertNotIn("secret", detail["message"])

    def test_startup_cleanup_removes_old_ocr_orphan_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orphan = root / "ocr-orphan"
            protected = root / "models"
            orphan.mkdir()
            protected.mkdir()
            modified = time.time() - main.ASR_TMP_MAX_AGE_SECONDS - 5
            os.utime(orphan, (modified, modified))

            with patch.object(main, "ASR_TMP_DIR", root):
                removed = main.cleanup_stale_asr_tmp()

            self.assertEqual(removed, 1)
            self.assertFalse(orphan.exists())
            self.assertTrue(protected.exists())

    def test_asr_semaphore_is_released_when_download_fails(self) -> None:
        class FakeSemaphore:
            def __init__(self) -> None:
                self.releases = 0

            def acquire(self, **_kwargs) -> bool:
                return True

            def release(self) -> None:
                self.releases += 1

        semaphore = FakeSemaphore()
        source = main.ExtractionSource(
            title="test",
            video_id="BV14jFvzbEvj",
            webpage_url="https://www.bilibili.com/video/BV14jFvzbEvj",
            tracks=[],
            duration=3,
        )
        with tempfile.TemporaryDirectory() as directory:
            tmp_dir = Path(directory)
            with patch.object(main, "local_asr_enabled", return_value=True), patch.object(
                main, "ASR_TMP_DIR", tmp_dir
            ), patch.object(
                main, "ASR_SEMAPHORE", semaphore
            ), patch.object(main, "ensure_asr_ready"), patch.object(
                main, "ensure_disk_space"
            ), patch.object(main, "view_source", return_value=source), patch.object(
                main,
                "download_audio_for_asr",
                side_effect=main.ExtractionFailure(502, "network failed", "download_failed"),
            ), self.assertRaises(main.ExtractionFailure):
                main.asr_subtitle(
                    main.ExtractRequest(input="BV14jFvzbEvj", source="asr"),
                    allow_cookie=False,
                )

        self.assertEqual(semaphore.releases, 1)


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

    def test_expired_artifact_deletes_file_metadata_and_reservation(self) -> None:
        token = "c" * 32
        main.reserve_media_artifact(token)
        directory = main.media_artifact_directory(token)
        directory.mkdir(parents=True)
        artifact = directory / "artifact.mp4"
        artifact.write_bytes(b"expired")
        main.write_media_artifact_metadata(
            directory,
            {
                "artifact_token": token,
                "owner_id": 7,
                "stored_name": artifact.name,
                "size": artifact.stat().st_size,
                "expires_at": time.time() - 1,
            },
        )

        with self.assertRaises(HTTPException) as raised:
            main.load_media_artifact(token, owner_id=7)

        self.assertEqual(raised.exception.status_code, 410)
        self.assertFalse(directory.exists())
        self.assertNotIn(token, main.MEDIA_RESERVATIONS)

    def test_cleanup_removes_expired_finalized_artifact_even_if_reserved(self) -> None:
        token = "d" * 32
        main.reserve_media_artifact(token)
        directory = main.media_artifact_directory(token)
        directory.mkdir(parents=True)
        artifact = directory / "artifact.mp4"
        artifact.write_bytes(b"expired")
        main.write_media_artifact_metadata(
            directory,
            {
                "artifact_token": token,
                "owner_id": 7,
                "stored_name": artifact.name,
                "size": artifact.stat().st_size,
                "expires_at": time.time() - 1,
            },
        )

        removed = main.cleanup_stale_media_artifacts()

        self.assertEqual(removed, 1)
        self.assertFalse(directory.exists())
        self.assertNotIn(token, main.MEDIA_RESERVATIONS)

    def test_cleanup_preserves_unexpired_finalized_artifact(self) -> None:
        token = "e" * 32
        directory = main.media_artifact_directory(token)
        directory.mkdir(parents=True)
        artifact = directory / "artifact.mp4"
        artifact.write_bytes(b"active")
        main.write_media_artifact_metadata(
            directory,
            {
                "artifact_token": token,
                "owner_id": 7,
                "stored_name": artifact.name,
                "size": artifact.stat().st_size,
                "expires_at": time.time() + 300,
            },
        )

        removed = main.cleanup_stale_media_artifacts()

        self.assertEqual(removed, 0)
        self.assertTrue(artifact.is_file())


class BilibiliRedirectAndCookieTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, status_code: int, url: str, location: str | None = None, payload=None) -> None:
            self.status_code = status_code
            self.url = url
            self.headers = {"location": location} if location else {}
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, responses, **_kwargs) -> None:
            self.responses = list(responses)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, _url):
            return self.responses.pop(0)

    def tearDown(self) -> None:
        main.resolve_b23_url.cache_clear()

    def test_b23_redirect_preserves_page_and_rejects_untrusted_target(self) -> None:
        safe = self.FakeClient(
            [
                self.FakeResponse(
                    302,
                    "https://b23.tv/test",
                    "https://www.bilibili.com/video/BV14jFvzbEvj?p=3",
                )
            ]
        )
        with patch.object(main.httpx, "Client", return_value=safe):
            resolved = main.resolve_b23_url("https://b23.tv/test")
        self.assertEqual(resolved, "https://www.bilibili.com/video/BV14jFvzbEvj?p=3")

        main.resolve_b23_url.cache_clear()
        unsafe = self.FakeClient(
            [self.FakeResponse(302, "https://b23.tv/test", "https://example.com/video/BV14jFvzbEvj")]
        )
        with patch.object(main.httpx, "Client", return_value=unsafe), self.assertRaises(
            main.ExtractionFailure
        ) as raised:
            main.resolve_b23_url("https://b23.tv/test")
        self.assertEqual(raised.exception.reason, "short_link_untrusted")

    def test_b23_redirect_loop_is_bounded(self) -> None:
        client = self.FakeClient(
            [self.FakeResponse(302, "https://b23.tv/loop", "https://b23.tv/loop")]
        )
        with patch.object(main.httpx, "Client", return_value=client), self.assertRaises(
            main.ExtractionFailure
        ) as raised:
            main.resolve_b23_url("https://b23.tv/loop")
        self.assertEqual(raised.exception.reason, "short_link_loop")

    def test_cookie_is_not_read_when_request_disables_it(self) -> None:
        with patch.object(main, "configured_cookie_header", side_effect=AssertionError("cookie read")) as read:
            self.assertFalse(main.cookie_allowed(False))
            self.assertNotIn("Cookie", main.headers_for(allow_cookie=False))
        read.assert_not_called()

    def test_expired_cookie_has_stable_error_without_cookie_value(self) -> None:
        response = self.FakeResponse(
            200,
            "https://api.bilibili.com/test",
            payload={"code": -101, "message": "账号未登录"},
        )
        client = self.FakeClient([response])
        with patch.object(main.httpx, "Client", return_value=client), patch.object(
            main,
            "headers_for",
            return_value={"Cookie": "SESSDATA=top-secret"},
        ), self.assertRaises(main.ExtractionFailure) as raised:
            main.api_get_json("https://api.bilibili.com/test", "https://www.bilibili.com/", True)

        self.assertEqual(raised.exception.reason, "cookie_expired")
        self.assertNotIn("top-secret", raised.exception.detail)


class BilibiliSelectionTests(unittest.TestCase):
    def test_av_link_preserves_page_and_uses_ytdlp_metadata_fallback(self) -> None:
        normalized = main.normalize_input(
            "https://www.bilibili.com/video/AV123456?p=2&spm_id_from=333.999"
        )
        self.assertEqual(normalized, "https://www.bilibili.com/video/av123456?p=2")

        info = {
            "id": "123456",
            "title": "AV test",
            "duration": 9,
            "webpage_url": normalized,
            "uploader": "tester",
        }
        with patch.object(main, "extract_info", return_value=info) as extract:
            source = main.view_source(normalized)

        self.assertEqual(source.video_id, "123456")
        self.assertEqual(source.duration, 9)
        extract.assert_called_once()

    def test_non_bv_media_falls_back_to_ytdlp(self) -> None:
        request = main.MediaJobRequest(
            input="https://www.bilibili.com/video/av123456",
            media_type="video",
            artifact_token="2" * 32,
            owner_id=1,
        )
        expected = (Path("source.mp4"), {"title": "AV test"})
        invalid_bvid = main.ExtractionFailure(400, "missing BV", "invalid_bvid", terminal=True)
        with patch.object(main, "download_bilibili_media_api", side_effect=invalid_bvid), patch.object(
            main, "download_bilibili_media_ytdlp", return_value=expected
        ) as fallback:
            result = main.download_bilibili_media(request, Path("."))

        self.assertEqual(result, expected)
        fallback.assert_called_once()

    def test_non_bv_missing_platform_subtitle_can_fall_back_to_asr(self) -> None:
        request = main.ExtractRequest(input="https://www.bilibili.com/video/av123456")
        info = {
            "id": "123456",
            "title": "AV test",
            "duration": 9,
            "webpage_url": request.input,
            "subtitles": {},
            "automatic_captions": {},
        }
        invalid_bvid = main.ExtractionFailure(400, "missing BV", "invalid_bvid", terminal=True)
        with patch.object(main, "extract_info", return_value=info), patch.object(
            main, "bili_api_source", side_effect=invalid_bvid
        ), self.assertRaises(main.ExtractionFailure) as raised:
            main.official_subtitle(request, allow_cookie=False, source_label="official_no_cookie")

        self.assertEqual(raised.exception.reason, "no_official_subtitle")
        self.assertTrue(raised.exception.can_try_asr)

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
            prior_note="没有找到可读取的字幕或语音内容。",
        )
        self.assertEqual(result_entries, entries)
        self.assertEqual(
            [attempt["source"] for attempt in result_metadata["attempts"]],
            ["official_no_cookie", "official_with_cookie"],
        )


class RenderingTests(unittest.TestCase):
    def test_raw_and_normalized_cloud_variants_render_independently(self) -> None:
        metadata = {
            "title": "测试",
            "raw_entries": [
                {"start": 0.0, "end": 1.0, "text": "原始  文本"},
            ],
        }
        normalized = [main.SubtitleEntry(0.0, 1.0, "整理文本")]

        self.assertEqual(main.render_entries(normalized, "txt", metadata), "整理文本\n")
        self.assertEqual(main.rendered_raw_content(metadata, "txt"), "原始  文本\n")

    def test_sensitive_values_and_local_paths_are_redacted(self) -> None:
        value = (
            "failed at /opt/private/video.mp4 and C:\\Users\\name\\secret.txt "
            "or file:///tmp/private.wav; https://example.com/video/1 token=top-secret"
        )

        redacted = main.redact_sensitive(value)

        self.assertNotIn("/opt/private", redacted)
        self.assertNotIn("C:\\Users", redacted)
        self.assertNotIn("file:///tmp", redacted)
        self.assertNotIn("top-secret", redacted)
        self.assertIn("https://example.com/video/1", redacted)

    def test_unicode_filename_is_preserved_and_sanitized(self) -> None:
        self.assertEqual(main.safe_filename("标题：测试/01", "markdown"), "标题：测试_01.md")
        filename = main.safe_filename('evil"\r\nContent-Disposition: inline', "srt")
        self.assertNotIn("\r", filename)
        self.assertNotIn("\n", filename)
        self.assertNotIn('"', filename)

    def test_invalid_transcription_result_becomes_public_failure(self) -> None:
        with self.assertRaises(main.ExtractionFailure) as raised:
            main.parse_transcription_result({"ok": False, "error": "decode failed"})
        self.assertEqual(raised.exception.reason, "asr_failed")

        with self.assertRaises(main.ExtractionFailure) as model_failure:
            main.parse_transcription_result(
                {
                    "ok": False,
                    "error": "LocalEntryNotFoundError: model not found",
                    "reason": "asr_model_download_failed",
                }
            )
        self.assertEqual(model_failure.exception.reason, "asr_model_download_failed")
        self.assertEqual(model_failure.exception.status_code, 503)

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
        signed = main.redact_sensitive("https://example.test/media?msToken=session-value&X-Bogus=signed-value")
        self.assertNotIn("session-value", signed)
        self.assertNotIn("signed-value", signed)


class AsrWorkerTests(unittest.TestCase):
    def test_fast_and_accurate_profiles_share_one_default_model_key(self) -> None:
        fast = main.asr_profile("fast")
        accurate = main.asr_profile("accurate")

        for key in ("model", "compute_type", "device", "cpu_threads"):
            self.assertEqual(fast[key], accurate[key])
        self.assertEqual(fast["beam_size"], 3)
        self.assertEqual(accurate["beam_size"], 5)
        self.assertFalse(fast["condition_on_previous_text"])
        self.assertTrue(accurate["condition_on_previous_text"])

    def test_whisper_model_keeps_only_one_instance_and_unloads_on_switch(self) -> None:
        created = []

        class RuntimeModel:
            def __init__(self) -> None:
                self.unloads = 0

            def unload_model(self) -> None:
                self.unloads += 1

        class FakeModel:
            def __init__(self, name: str) -> None:
                self.name = name
                self.model = RuntimeModel()

        def factory(name: str, **_kwargs):
            instance = FakeModel(name)
            created.append(instance)
            return instance

        main.clear_whisper_model()
        try:
            with patch("faster_whisper.WhisperModel", side_effect=factory):
                first = main.whisper_model("small", "int8", "cpu", 3)
                reused = main.whisper_model("small", "int8", "cpu", 3)
                switched = main.whisper_model("small", "int8", "cpu", 2)

            self.assertIs(first, reused)
            self.assertIsNot(first, switched)
            self.assertEqual(len(created), 2)
            self.assertEqual(first.model.unloads, 1)
        finally:
            main.clear_whisper_model()
        self.assertEqual(created[-1].model.unloads, 1)

    def test_accurate_transcription_uses_context_metrics_and_one_retry(self) -> None:
        class Segment:
            def __init__(self, start: float, text: str, logprob: float) -> None:
                self.start = start
                self.end = start + 1
                self.text = text
                self.avg_logprob = logprob
                self.no_speech_prob = 0.05
                self.compression_ratio = 1.2

        class Info:
            language = "zh"
            language_probability = 0.98
            duration_after_vad = 8.5

        class FakeModel:
            def __init__(self) -> None:
                self.calls = []

            def transcribe(self, _audio_path: str, **options):
                self.calls.append(options)
                if len(self.calls) == 1:
                    return [Segment(float(index), "重复字幕", -1.4) for index in range(4)], Info()
                return [Segment(0, "第一句", -0.2), Segment(1, "第二句", -0.3)], Info()

        model = FakeModel()
        with patch.object(main, "whisper_model", return_value=model), patch.object(
            main, "audio_duration_seconds", return_value=10.0
        ), patch.object(main, "peak_rss_mb", return_value=512.0):
            result = main.transcribe_audio_payload(
                "audio.wav",
                "zh",
                "accurate",
                "物联网课程 https://private.invalid/secret",
                "MQTT, ESP32",
            )

        self.assertTrue(result["ok"])
        self.assertEqual([entry[2] for entry in result["entries"]], ["第一句", "第二句"])
        self.assertEqual(len(model.calls), 2)
        self.assertTrue(model.calls[0]["condition_on_previous_text"])
        self.assertFalse(model.calls[1]["condition_on_previous_text"])
        self.assertEqual(model.calls[0]["hotwords"], "MQTT, ESP32")
        self.assertNotIn("https://", model.calls[0]["initial_prompt"])
        self.assertEqual(model.calls[0]["vad_parameters"]["min_silence_duration_ms"], 700)
        metadata = result["meta"]
        self.assertTrue(metadata["context_retry_performed"])
        self.assertTrue(metadata["context_retry_selected"])
        self.assertEqual(metadata["asr_attempt_count"], 2)
        self.assertEqual(metadata["audio_duration_seconds"], 10.0)
        self.assertEqual(metadata["peak_rss_mb"], 512.0)
        encoded = json.dumps(metadata, ensure_ascii=False)
        self.assertNotIn("MQTT", encoded)
        self.assertNotIn("物联网课程", encoded)

    def test_transcription_error_redacts_prompt_and_hotwords(self) -> None:
        class FailingModel:
            def transcribe(self, *_args, **_kwargs):
                raise RuntimeError("decode failed for 私人课程 and MQTT")

        with patch.object(main, "whisper_model", return_value=FailingModel()):
            result = main.transcribe_audio_payload(
                "audio.wav",
                "zh",
                "accurate",
                "私人课程",
                "MQTT",
            )

        self.assertFalse(result["ok"])
        self.assertNotIn("私人课程", result["error"])
        self.assertNotIn("MQTT", result["error"])
        with self.assertLogs("app.main", level="WARNING") as captured, self.assertRaises(
            main.ExtractionFailure
        ):
            main.parse_transcription_result(result)
        self.assertNotIn("私人课程", " ".join(captured.output))
        self.assertNotIn("MQTT", " ".join(captured.output))

    def test_successful_prewarm_updates_worker_warm_state(self) -> None:
        class FakeSemaphore:
            def __init__(self) -> None:
                self.released = False

            def acquire(self, **_kwargs) -> bool:
                return True

            def release(self) -> None:
                self.released = True

        class FakeEvent:
            def wait(self, _timeout: float) -> bool:
                return True

        class FakeQueue:
            def get(self, timeout: float):
                self.timeout = timeout
                return {"kind": "prewarm", "ok": True}

        original = (
            main.ASR_WORKER_RESULT_QUEUE,
            main.ASR_WORKER_READY_EVENT,
            main.ASR_WORKER_WARM,
        )
        semaphore = FakeSemaphore()
        main.ASR_WORKER_RESULT_QUEUE = FakeQueue()
        main.ASR_WORKER_READY_EVENT = FakeEvent()
        main.ASR_WORKER_WARM = False
        try:
            with patch.object(main, "ASR_SEMAPHORE", semaphore), patch.object(
                main, "ensure_asr_ready"
            ), patch.object(main, "ensure_persistent_asr_worker_locked"):
                main.prewarm_asr_worker()

            self.assertTrue(main.ASR_WORKER_WARM)
            self.assertTrue(semaphore.released)
        finally:
            (
                main.ASR_WORKER_RESULT_QUEUE,
                main.ASR_WORKER_READY_EVENT,
                main.ASR_WORKER_WARM,
            ) = original

    def test_long_audio_gets_dynamic_timeout_budget(self) -> None:
        class FakeWave:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def getframerate(self) -> int:
                return 100

            def getnframes(self) -> int:
                return 360_000

        with patch.object(main.wave, "open", return_value=FakeWave()), patch.object(
            main, "ACCURATE_ASR_TIMEOUT_PER_AUDIO_SECOND", 1.5
        ), patch.object(main, "ASR_MAX_TIMEOUT_SECONDS", 7200):
            timeout = main.asr_task_timeout(Path("long.wav"), "accurate")

        self.assertEqual(timeout, 5460)
        self.assertGreater(timeout, main.ACCURATE_ASR_TIMEOUT_SECONDS)

    def test_prewarm_failure_is_retried_by_first_real_task(self) -> None:
        class FakeRequestQueue:
            def __init__(self) -> None:
                self.items = [
                    {"task_id": "task-1", "audio_path": "audio.wav", "lang": "zh", "quality": "fast"},
                    None,
                ]

            def get(self):
                return self.items.pop(0)

        class FakeResultQueue:
            def __init__(self) -> None:
                self.items = []

            def put(self, value) -> None:
                self.items.append(value)

        class FakeEvent:
            def __init__(self) -> None:
                self.set_count = 0

            def set(self) -> None:
                self.set_count += 1

        class FakeModel:
            def transcribe(self, *_args, **_kwargs):
                segment = type("Segment", (), {"start": 0.0, "end": 1.0, "text": "重试成功"})()
                info = type("Info", (), {"language": "zh", "language_probability": 0.99})()
                return [segment], info

        request_queue = FakeRequestQueue()
        result_queue = FakeResultQueue()
        ready = FakeEvent()
        with patch.object(main, "whisper_model", side_effect=[RuntimeError("prewarm failed"), FakeModel()]) as model:
            main.persistent_asr_worker(request_queue, result_queue, ready)

        self.assertEqual(model.call_count, 2)
        self.assertEqual(ready.set_count, 1)
        self.assertEqual(result_queue.items[0]["kind"], "prewarm")
        self.assertFalse(result_queue.items[0]["ok"])
        self.assertEqual(result_queue.items[0]["model_key"], ["small", "int8", "cpu", 3])
        self.assertTrue(result_queue.items[1]["ok"])
        self.assertEqual(result_queue.items[1]["task_id"], "task-1")

    def test_dead_persistent_worker_is_rebuilt_for_next_task(self) -> None:
        class FakeQueue:
            def cancel_join_thread(self) -> None:
                pass

            def close(self) -> None:
                pass

        class FakeEvent:
            def set(self) -> None:
                pass

        class DeadProcess:
            exitcode = -9

            def is_alive(self) -> bool:
                return False

            def join(self, _timeout=0) -> None:
                pass

        class NewProcess:
            def __init__(self) -> None:
                self.started = False

            def start(self) -> None:
                self.started = True

            def is_alive(self) -> bool:
                return self.started

        new_process = NewProcess()

        class FakeContext:
            def Queue(self, maxsize: int):
                self.maxsize = maxsize
                return FakeQueue()

            def Event(self):
                return FakeEvent()

            def Process(self, **_kwargs):
                return new_process

        original = (
            main.ASR_WORKER_PROCESS,
            main.ASR_WORKER_REQUEST_QUEUE,
            main.ASR_WORKER_RESULT_QUEUE,
            main.ASR_WORKER_READY_EVENT,
            main.ASR_WORKER_WARM,
        )
        main.ASR_WORKER_PROCESS = DeadProcess()
        main.ASR_WORKER_REQUEST_QUEUE = FakeQueue()
        main.ASR_WORKER_RESULT_QUEUE = FakeQueue()
        main.ASR_WORKER_READY_EVENT = FakeEvent()
        try:
            with patch.object(main, "get_context", return_value=FakeContext()):
                main.ensure_persistent_asr_worker_locked()
            self.assertIs(main.ASR_WORKER_PROCESS, new_process)
            self.assertTrue(new_process.started)
        finally:
            (
                main.ASR_WORKER_PROCESS,
                main.ASR_WORKER_REQUEST_QUEUE,
                main.ASR_WORKER_RESULT_QUEUE,
                main.ASR_WORKER_READY_EVENT,
                main.ASR_WORKER_WARM,
            ) = original

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

        with patch.object(main, "get_context", return_value=FakeContext()), self.assertRaises(
            main.ExtractionFailure
        ) as raised:
            main.transcribe_audio_once(Path("audio.wav"), "zh", "fast")

        self.assertEqual(raised.exception.reason, "asr_worker_crashed")
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
        ), patch.object(main, "run_managed_process", side_effect=fake_run) as run:
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

    def test_embedded_text_track_defaults_to_chinese_language(self) -> None:
        media_info = {
            "subtitle_streams": [
                {"index": 1, "codec_name": "subrip", "language": "en", "title": "English"},
                {"index": 5, "codec_name": "subrip", "language": "zh-CN", "title": "Chinese"},
            ]
        }

        def fake_run(command, **_kwargs):
            Path(command[-1]).write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n中文字幕\n",
                encoding="utf-8",
            )
            return type("Completed", (), {"returncode": 0, "stderr": ""})()

        with tempfile.TemporaryDirectory() as directory, patch.object(
            main.shutil, "which", return_value="/usr/bin/ffmpeg"
        ), patch.object(main, "run_managed_process", side_effect=fake_run) as run:
            result = main.extract_embedded_text_subtitle(
                Path(directory) / "video.mkv",
                media_info,
                Path(directory),
                None,
            )

        self.assertIsNotNone(result)
        self.assertIn("0:5", run.call_args.args[0])

    def test_burned_subtitle_worker_drains_bounded_ffmpeg_stderr(self) -> None:
        class EmptyStream:
            def read(self, _size: int) -> bytes:
                return b""

        class FakeProcess:
            pid = 321
            stdout = EmptyStream()
            stderr = EmptyStream()
            returncode = 0

            def wait(self, timeout: float) -> int:
                self.timeout = timeout
                return 0

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                pass

            def terminate(self) -> None:
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
        self.assertEqual(popen.call_args.kwargs["stderr"], main.subprocess.PIPE)
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
        ), self.assertRaises(main.ExtractionFailure) as raised:
            main.extract_burned_subtitles(Path("video.mp4"), 2.0)

        self.assertEqual(raised.exception.reason, "ocr_failed")
        self.assertEqual(semaphore.releases, 1)


if __name__ == "__main__":
    unittest.main()
