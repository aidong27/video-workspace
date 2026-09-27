from threading import Event
import unittest
from unittest.mock import Mock

from app.maintenance import MaintenanceLoop


class MaintenanceTests(unittest.TestCase):
    def test_cleanup_runs_without_requests_and_stops_cleanly(self):
        called = Event()
        loop = MaintenanceLoop((called.set,), interval=0.01)
        loop.start()
        thread = loop.thread
        loop.start()
        self.assertIs(loop.thread, thread)
        self.assertTrue(called.wait(1))
        loop.stop()
        self.assertFalse(thread.is_alive())
        called.clear()
        self.assertFalse(called.wait(0.03))
        loop.start()
        self.assertTrue(called.wait(1))
        loop.stop()

    def test_one_cleanup_failure_does_not_stop_others_or_leak_details(self):
        next_cleanup = Mock()
        loop = MaintenanceLoop((Mock(side_effect=OSError("private path/token")), next_cleanup))
        with self.assertLogs("app.maintenance", level="ERROR") as output:
            loop.run_once()
        next_cleanup.assert_called_once_with()
        self.assertNotIn("private", "".join(output.output))
