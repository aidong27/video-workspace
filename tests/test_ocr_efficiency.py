from io import BytesIO
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import main


def run_fixture(exit_code=0, engine_error=False):
    stream = BytesIO(b"".join(b"\xff\xd8" + content + b"\xff\xd9" for content in [b"a", b"a", b"b", b"b"]))
    process = Mock(stdout=stream, stderr=BytesIO(), pid=321, returncode=exit_code)
    process.wait.return_value = exit_code
    process.poll.return_value = exit_code
    engine = Mock(side_effect=RuntimeError("transient inference error") if engine_error else None)
    queue = Queue()
    lines = [{"text": "测试字幕", "score": 0.99, "x": 20, "y": 20}]
    with patch.dict("sys.modules", {"rapidocr": SimpleNamespace(RapidOCR=Mock(return_value=engine))}), patch.object(
        main.subprocess, "Popen", return_value=process
    ) as popen, patch.object(main, "ocr_lines_from_result", return_value=lines), patch.object(
        main, "build_ocr_entries", return_value=[main.SubtitleEntry(0, 2, "测试字幕")]
    ) as build:
        main.burned_subtitle_ocr_worker("controlled.mp4", 2, queue)
    messages = list(queue.queue)
    result = next(message for message in messages if message["kind"] == "result")
    return result, engine, build, process, popen.call_args.args[0]


def test_identical_frames_reuse_ocr_and_preserve_all_timestamps():
    result, engine, build, process, command = run_fixture()
    assert result["ok"] is True
    assert result["meta"]["ocr_reused_frames"] == 2
    assert engine.call_count == 2
    frames = build.call_args.args[0]
    assert [frame["time"] for frame in frames] == [i / main.OCR_SAMPLE_FPS for i in range(4)]
    assert all(frame["lines"][0]["text"] == "测试字幕" for frame in frames)
    assert command.count("-threads") == 2
    assert "-filter_threads" in command
    assert process.stdout.closed and process.stderr.closed


def test_partial_ffmpeg_failure_cannot_report_success():
    result, _engine, build, process, _command = run_fixture(exit_code=1)
    assert result["ok"] is False
    build.assert_not_called()
    process.wait.assert_called_once()
    assert process.stdout.closed and process.stderr.closed


def test_failed_ocr_frame_is_not_cached_as_an_empty_recognition():
    result, engine, _build, _process, _command = run_fixture(engine_error=True)
    assert result["meta"]["ocr_reused_frames"] == 0
    assert engine.call_count == 4
