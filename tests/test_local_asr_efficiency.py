import itertools
import os
from pathlib import Path
from queue import Full, Queue
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from app import main


def wav(path, seconds=1, sample=b"\0\0", rate=16000, channels=1):
    with wave.open(str(path), "wb") as output:
        output.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(sample * int(seconds * rate * channels))


class LocalAudioTests(unittest.TestCase):
    def test_pcm_reuses_bytes_without_ffmpeg_and_survives_source_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "ensure_disk_space"), patch.object(
            main, "asr_audio_filter", return_value=""
        ), patch.object(main, "run_managed_process") as run:
            source = Path(tmp) / "source.wav"
            wav(source, sample=b"\1\0")
            result = main.normalize_audio_for_asr(source, Path(tmp), "ready")
            self.assertTrue(os.path.samefile(source, result))
            source.unlink()
            self.assertEqual(main.normalized_pcm_duration(result), 1)
            run.assert_not_called()

    def test_cross_device_copy_has_disk_check_and_partial_copy_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "asr_audio_filter", return_value=""), patch.object(
            main.os, "link", side_effect=OSError("cross-device")
        ), patch.object(main, "ensure_disk_space") as disk:
            source = Path(tmp) / "source.wav"
            wav(source)
            result = main.normalize_audio_for_asr(source, Path(tmp), "ready")
            self.assertEqual(result.read_bytes(), source.read_bytes())
            disk.assert_called_with(Path(tmp), source.stat().st_size)

            def broken_copy(_source, target):
                Path(target).write_bytes(b"partial")
                raise OSError("disk failure")

            with patch.object(main.shutil, "copyfile", side_effect=broken_copy), self.assertRaises(OSError):
                main.normalize_audio_for_asr(source, Path(tmp), "broken")
            self.assertFalse((Path(tmp) / "broken.asr.wav").exists())

    def test_filter_forces_bounded_ffmpeg_even_for_normalized_pcm(self):
        def convert(command, **kwargs):
            wav(Path(command[-1]))
            return SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "ensure_disk_space"), patch.object(
            main, "asr_audio_filter", return_value="highpass=f=70"
        ), patch.object(main.shutil, "which", return_value="ffmpeg"), patch.object(
            main, "run_managed_process", side_effect=convert
        ) as run:
            source = Path(tmp) / "input ; unsafe.wav"
            wav(source)
            main.normalize_audio_for_asr(source, Path(tmp), "ready")
            command = run.call_args.args[0]
            self.assertIn(str(source), command)
            self.assertLessEqual(int(command[command.index("-threads") + 1]), 2)
            self.assertEqual(command[command.index("-filter_threads") + 1], "1")
            self.assertEqual(command[command.index("-map") + 1], "0:a:0")
            self.assertEqual(command[command.index("-af") + 1], "highpass=f=70")

    def test_oversized_decoded_audio_is_removed(self):
        def convert(command, **kwargs):
            wav(Path(command[-1]), seconds=2)
            return SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "ASR_MAX_AUDIO_SECONDS", 1), patch.object(
            main, "ensure_disk_space"
        ), patch.object(main.shutil, "which", return_value="ffmpeg"), patch.object(main, "run_managed_process", side_effect=convert):
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"fixture")
            with self.assertRaises(main.ExtractionFailure) as failed:
                main.normalize_audio_for_asr(source, Path(tmp), "ready")
            self.assertEqual(failed.exception.reason, "asr_duration_too_long")
            self.assertFalse((Path(tmp) / "ready.asr.wav").exists())

    def test_digital_silence_skips_worker_but_one_bit_quiet_audio_does_not(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "ensure_persistent_asr_worker_locked") as worker:
            path = Path(tmp) / "silence.wav"
            wav(path)
            entries, meta = main.transcribe_audio(path, "zh")
            self.assertEqual(entries, [])
            self.assertEqual(meta["asr_attempt_count"], 0)
            worker.assert_not_called()
            wav(path, sample=b"\1\0")
            self.assertFalse(main.digital_silence(path))

    def test_bad_pcm_headers_and_stereo_do_not_take_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.wav"
            wav(path, channels=2)
            self.assertIsNone(main.normalized_pcm_duration(path))
            self.assertFalse(main.digital_silence(path))
            wav(path)
            path.write_bytes(path.read_bytes()[:-2])
            self.assertIsNone(main.normalized_pcm_duration(path))
            self.assertFalse(main.digital_silence(path))

    def test_duration_guard_runs_before_loading_model(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "ASR_MAX_AUDIO_SECONDS", 1), patch.object(
            main, "ensure_persistent_asr_worker_locked"
        ) as worker:
            path = Path(tmp) / "long.wav"
            wav(path, seconds=2)
            with self.assertRaises(main.ExtractionFailure) as failed:
                main.transcribe_audio(path, "zh")
            self.assertEqual(failed.exception.reason, "asr_duration_too_long")
            worker.assert_not_called()


class RecognitionTests(unittest.TestCase):
    def first_pass(self):
        return [(0, 1, "original")], SimpleNamespace(language="zh"), {
            "transcribe_seconds": 1, "repeated_segment_ratio": 0.8,
            "low_confidence_segment_ratio": 0.9,
        }

    def test_optional_retry_failure_preserves_first_pass_and_redacts_log(self):
        for error in [RuntimeError("private hotwords"), TimeoutError("private URL")]:
            with self.subTest(error=type(error).__name__), patch.object(main, "whisper_model"), patch.object(
                main, "audio_duration_seconds", return_value=10
            ), patch.object(main, "run_whisper_transcription", side_effect=[self.first_pass(), error]), self.assertLogs(
                "app.main", level="WARNING"
            ) as logs:
                result = main.transcribe_audio_payload("fixture.wav", "zh", "accurate")
                self.assertTrue(result["ok"])
                self.assertEqual(result["entries"][0][2], "original")
                self.assertFalse(result["meta"]["context_retry_selected"])
                self.assertIsNotNone(result["meta"]["context_retry_failure"])
                self.assertNotIn("private", " ".join(logs.output))

    def test_low_remaining_time_does_not_start_second_pass(self):
        with patch.object(main, "whisper_model"), patch.object(main, "audio_duration_seconds", return_value=10), patch.object(
            main, "run_whisper_transcription", return_value=self.first_pass()
        ) as run:
            result = main.transcribe_audio_payload("fixture.wav", "zh", "accurate", deadline=time.monotonic() + 20)
            self.assertTrue(result["ok"])
            self.assertEqual(result["meta"]["context_retry_skipped_reason"], "time_budget")
            run.assert_called_once()

    def test_progress_is_based_on_timestamps_without_transcript_text(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(start=0, end=end, text="private text") for end in [10, 70, 100]], SimpleNamespace())
        progress = []
        with patch.object(main.time, "monotonic", side_effect=itertools.count()), main.extraction_progress(
            lambda stage, percent, message: progress.append((percent, message))
        ):
            main.run_whisper_transcription(model, "fixture.wav", {}, 100)
        self.assertEqual([item[0] for item in progress], [70, 83, 90])
        self.assertNotIn("private text", str(progress))

    def test_expired_retry_stops_at_segment_boundary(self):
        model = Mock()
        closed = []

        def segments():
            try:
                yield SimpleNamespace(start=0, end=1, text="text")
            finally:
                closed.append(True)

        model.transcribe.return_value = (segments(), SimpleNamespace())
        with self.assertRaises(TimeoutError):
            main.run_whisper_transcription(model, "fixture.wav", {}, 100, retry_deadline=0)
        self.assertEqual(closed, [True])

    def test_malformed_progress_does_not_fail_task(self):
        with patch.object(main, "report_progress") as report:
            for message in [{}, {"progress": None}, {"progress": float("inf"), "message": "progress"}]:
                self.assertTrue(main.consume_asr_progress({"kind": "progress", **message}))
            self.assertFalse(main.consume_asr_progress({"ok": True}))
            report.assert_not_called()

    def test_progress_queue_is_nonblocking(self):
        queue = Queue(maxsize=1)
        queue.put("existing")
        main.publish_asr_progress(queue, "task", "transcribe", 80, "progress")
        self.assertEqual(queue.get_nowait(), "existing")

    def test_parent_ignores_stale_progress_and_receives_final_result(self):
        requests = Mock()
        results = Mock()
        count = itertools.count()

        def get(**_kwargs):
            index = next(count)
            task_id = requests.put.call_args.args[0]["task_id"]
            if index < 2:
                return {"task_id": "stale" if index == 0 else task_id, "kind": "progress", "progress": 80, "message": "progress"}
            return {"task_id": task_id, "ok": True, "entries": [(0, 1, "text")], "meta": {}}

        results.get.side_effect = get
        progress = Mock()
        with patch.object(main, "ASR_WORKER_PROCESS", Mock()), patch.object(main, "ASR_WORKER_REQUEST_QUEUE", requests), patch.object(
            main, "ASR_WORKER_RESULT_QUEUE", results
        ), patch.object(main, "ensure_persistent_asr_worker_locked"), patch.object(main, "schedule_asr_worker_idle_exit_locked"), patch.object(
            main, "ASR_WORKER_WARM", False
        ), patch.object(main, "ASR_WORKER_MODEL_KEY", None), main.extraction_progress(progress):
            entries, _ = main.transcribe_audio(Path("fixture.wav"), "zh")
        self.assertEqual(entries[0].text, "text")
        progress.assert_called_once_with("transcribe", 80, "progress")

    def test_full_worker_request_queue_resets_instead_of_hanging(self):
        requests = Mock()
        requests.put.side_effect = Full
        with patch.object(main, "ASR_WORKER_PROCESS", Mock()), patch.object(main, "ASR_WORKER_REQUEST_QUEUE", requests), patch.object(
            main, "ensure_persistent_asr_worker_locked"
        ), patch.object(main, "schedule_asr_worker_idle_exit_locked"), patch.object(main, "stop_asr_worker_locked") as stop:
            with self.assertRaises(main.ExtractionFailure) as failed:
                main.transcribe_audio(Path("fixture.wav"), "zh")
            self.assertEqual(failed.exception.reason, "asr_worker_crashed")
            stop.assert_called_once_with(graceful=False)
            self.assertLessEqual(requests.put.call_args.kwargs["timeout"], 5)
        self.assertTrue(main.ASR_WORKER_LOCK.acquire(blocking=False))
        main.ASR_WORKER_LOCK.release()
