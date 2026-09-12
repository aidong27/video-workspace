from io import BytesIO
import os
import signal
import subprocess
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from app import processes


class ManagedProcessTests(unittest.TestCase):
    def test_interruption_reaps_child_and_closes_both_pipes(self) -> None:
        process = Mock(stdout=BytesIO(b"out"), stderr=BytesIO(b"err"), returncode=None)
        process.poll.return_value = None
        process.wait.side_effect = [KeyboardInterrupt, -15]
        with patch.object(processes.subprocess, "Popen", return_value=process), self.assertRaises(KeyboardInterrupt):
            processes.run_managed_process(["ffmpeg"], timeout=1)
        process.terminate.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_capture_start_failure_still_reaps_child(self) -> None:
        process = Mock(stdout=BytesIO(b""), stderr=BytesIO(b""), returncode=None)
        process.poll.return_value = None
        process.wait.return_value = -15
        with patch.object(processes.subprocess, "Popen", return_value=process), patch.object(
            processes.LimitedStreamCapture, "start", side_effect=RuntimeError("thread limit")
        ), self.assertRaises(RuntimeError):
            processes.run_managed_process(["ffmpeg"], timeout=1)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    @unittest.skipUnless(hasattr(os, "getpgid") and hasattr(os, "killpg"), "POSIX process groups required")
    def test_child_group_cleanup_detects_group_before_start_message_arrives(self) -> None:
        class FakeProcess:
            pid = 4321

            def __init__(self) -> None:
                self.alive = True

            def is_alive(self) -> bool:
                return self.alive

            def join(self, _timeout=0) -> None:
                pass

        process = FakeProcess()

        def kill_group(pid: int, sent_signal: int) -> None:
            self.assertEqual(pid, process.pid)
            self.assertEqual(sent_signal, signal.SIGTERM)
            process.alive = False

        with patch.object(processes.os, "getpgid", return_value=process.pid), patch.object(
            processes.os, "killpg", side_effect=kill_group
        ) as killpg:
            processes.terminate_child_process_group(process, group_owned=False)

        killpg.assert_called_once_with(process.pid, signal.SIGTERM)

    def test_timeout_terminates_kills_and_reaps_process(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = BytesIO(b"partial stdout")
                self.stderr = BytesIO(b"partial stderr")
                self.returncode = None
                self.terminate_calls = 0
                self.kill_calls = 0
                self.wait_calls = []

            def poll(self):
                return self.returncode

            def terminate(self) -> None:
                self.terminate_calls += 1

            def kill(self) -> None:
                self.kill_calls += 1
                self.returncode = -9

            def wait(self, timeout=None):
                self.wait_calls.append(timeout)
                if self.returncode is not None:
                    return self.returncode
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

        process = FakeProcess()
        with patch.object(processes.subprocess, "Popen", return_value=process), self.assertRaises(
            processes.ManagedProcessTimeout
        ) as raised:
            processes.run_managed_process(["ffmpeg", "-version"], timeout=0.1)

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertGreaterEqual(len(process.wait_calls), 3)
        self.assertEqual(raised.exception.result.returncode, -9)
        self.assertIn("partial stderr", raised.exception.result.stderr)

    def test_output_capture_is_bounded(self) -> None:
        class FakeProcess:
            stdout = BytesIO(b"a" * 100)
            stderr = BytesIO(b"b" * 100)
            returncode = 0

            def wait(self, timeout=None):
                return 0

        with patch.object(processes.subprocess, "Popen", return_value=FakeProcess()):
            result = processes.run_managed_process(["ffprobe"], timeout=1, output_limit=8)

        self.assertTrue(result.stdout.startswith("a" * 8))
        self.assertIn("output truncated", result.stdout)
        self.assertLess(len(result.stdout), 80)


if __name__ == "__main__":
    unittest.main()
