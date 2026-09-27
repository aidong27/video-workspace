from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
from threading import Event
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.jobs import JobIdempotencyConflict, JobManager, JobNotFound, JobQueueFull


def wait_for_terminal(manager: JobManager, job_id: str, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class JobManagerTests(unittest.TestCase):
    def test_subtitle_retention_is_absolute_and_media_stays_short_lived(self) -> None:
        manager = JobManager(lambda payload, update: payload, result_ttl_seconds=3600,
                             subtitle_ttl_seconds=86400)
        with patch("app.jobs.time.time", return_value=100000):
            subtitle = manager.submit_completed({}, {"content": "text"}, owner_id=1)
            media = manager.submit_completed({"kind": "media"}, {
                "metadata": {"expires_at": 100000 + 1800}}, owner_id=1)
            legacy_media = manager.submit_completed({"kind": "media"}, {
                "metadata": {"artifact_ttl_seconds": 1800}}, owner_id=1)
        self.assertEqual(subtitle["expires_at"], 186400)
        self.assertEqual(media["expires_at"], 101800)
        self.assertEqual(legacy_media["expires_at"], 101800)
        with patch("app.jobs.time.time", return_value=186399):
            self.assertEqual(manager.get(subtitle["id"])["expires_at"], 186400)
            with self.assertRaises(JobNotFound):
                manager.get(media["id"])
        with patch("app.jobs.time.time", return_value=186400):
            with self.assertRaises(JobNotFound):
                manager.get(subtitle["id"])

    def test_recent_records_are_owned_bounded_and_do_not_include_payloads(self) -> None:
        manager = JobManager(lambda payload, update: payload)
        first = manager.submit_completed({"hotwords": "private", "upload_path": "/private"},
            {"content": "private", "metadata": {"title": "A", "platform": "upload"}}, owner_id=1)
        manager.submit_completed({}, {"metadata": {"title": "B"}}, owner_id=2)
        second = manager.submit_completed({}, {"metadata": {"title": "C"}}, owner_id=1)
        items = manager.recent(1, limit=1)
        self.assertEqual([item["id"] for item in items], [second["id"]])
        self.assertEqual({item["id"] for item in manager.recent(1)}, {first["id"], second["id"]})
        self.assertNotIn("private", str(manager.recent(1)))
        self.assertNotIn("result", items[0])

    def test_restart_prunes_expired_rows_beyond_restore_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            manager = JobManager(lambda payload, update: payload, state_path=path,
                                 max_records=100, subtitle_ttl_seconds=86400)
            with patch("app.jobs.time.time", return_value=100000):
                for _ in range(30):
                    manager.submit_completed({}, {"content": "old"}, owner_id=1)
            restored = JobManager(lambda payload, update: payload, state_path=path,
                                  max_records=10, subtitle_ttl_seconds=86400)
            with patch("app.jobs.time.time", return_value=186400):
                restored.start()
                try:
                    self.assertEqual(restored.recent(1), [])
                    with restored._connect_state() as connection:
                        self.assertEqual(connection.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
                finally:
                    restored.stop()

    def test_pending_jobs_do_not_expire_with_completed_results(self) -> None:
        manager = JobManager(lambda payload, update: payload)
        job = manager.submit({})
        manager.records[job["id"]].updated_at = 1
        self.assertIsNone(manager.get(job["id"])["expires_at"])
        self.assertEqual(manager.cleanup(), 0)

    def test_periodic_cleanup_prunes_rows_outside_restore_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            manager = JobManager(lambda payload, update: payload, state_path=path, max_records=100)
            with patch("app.jobs.time.time", return_value=100000):
                for _ in range(30):
                    manager.submit_completed({}, {"content": "old"}, owner_id=1)
                restored = JobManager(lambda payload, update: payload, state_path=path, max_records=10)
                restored.start()
            try:
                self.assertEqual(len(restored.records), 10)
                with patch("app.jobs.time.time", return_value=103600):
                    restored.cleanup()
                with restored._connect_state() as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            finally:
                restored.stop()

    def test_corrupt_result_metadata_does_not_break_recent_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            manager = JobManager(lambda payload, update: payload, state_path=path)
            good = manager.submit_completed({}, {"content": "good"}, owner_id=1)
            for malformed in ([1], {"metadata": [1]}):
                job = manager.submit_completed({}, {"content": "bad"}, owner_id=1)
                record = manager.records[job["id"]]
                record.result = malformed
                manager._persist_locked(record)
            restored = JobManager(lambda payload, update: payload, state_path=path)
            restored.start()
            try:
                self.assertEqual([item["id"] for item in restored.recent(1)], [good["id"]])
                with restored._connect_state() as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            finally:
                restored.stop()

    def test_cancelled_ids_do_not_accumulate_behind_busy_worker(self) -> None:
        started, release = Event(), Event()
        processed = []

        def processor(payload, _update):
            processed.append(payload["value"])
            started.set()
            release.wait(2)
            return payload

        manager = JobManager(processor, max_pending=2, max_records=10)
        manager.start()
        try:
            manager.submit({"value": "running"})
            self.assertTrue(started.wait(1))
            for index in range(250):
                job = manager.submit({"value": index})
                manager.cancel(job["id"])
                self.assertEqual(len(manager.queue), 0)
            final = manager.submit({"value": "final"})
            self.assertEqual(final["queue_position"], 1)
            release.set()
            self.assertEqual(wait_for_terminal(manager, final["id"])["status"], "completed")
            self.assertEqual(processed, ["running", "final"])
        finally:
            release.set()
            manager.stop()

    def test_concurrent_submissions_and_workers_execute_exactly_once(self) -> None:
        processed = []
        manager = JobManager(lambda payload, update: processed.append(payload["value"]) or payload,
                             max_pending=100, worker_count=3)
        manager.start()
        try:
            with ThreadPoolExecutor(max_workers=8) as submitters:
                jobs = list(submitters.map(lambda i: manager.submit({"value": i}), range(60)))
            for job in jobs:
                self.assertEqual(manager.wait(job["id"], timeout=2)["status"], "completed")
            self.assertEqual(sorted(processed), list(range(60)))
            self.assertEqual(len(manager.queue), 0)
        finally:
            manager.stop()

    def test_queue_positions_follow_fifo_after_cancellation(self) -> None:
        manager = JobManager(lambda payload, update: payload, max_pending=3)
        first, middle, last = [manager.submit({"value": value}) for value in range(3)]
        manager.cancel(middle["id"])
        self.assertEqual(manager.get(last["id"])["queue_position"], 2)
        self.assertEqual(manager.get(first["id"])["queue_position"], 1)
        manager.stop()
        self.assertEqual(len(manager.queue), 0)
        self.assertEqual(manager.get(last["id"])["status"], "cancelled")

    def test_internal_failure_log_does_not_echo_exception_details(self) -> None:
        def processor(_payload, _update):
            raise RuntimeError("secret at /tmp/private/video.mp4")

        manager = JobManager(processor)
        manager.start()
        try:
            with self.assertLogs("app.jobs", level="ERROR") as captured:
                submitted = manager.submit({})
                result = wait_for_terminal(manager, submitted["id"])
            output = "\n".join(captured.output)
            self.assertEqual(result["status"], "failed")
            self.assertIn("RuntimeError", output)
            self.assertNotIn("secret", output)
            self.assertNotIn("/tmp", output)
        finally:
            manager.stop()

    def test_job_progress_and_result(self) -> None:
        def processor(payload, update):
            update("work", 55, "处理中")
            return {"ok": True, "value": payload["value"]}

        manager = JobManager(processor, max_pending=2)
        manager.start()
        try:
            submitted = manager.submit({"value": 7})
            result = wait_for_terminal(manager, submitted["id"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"]["value"], 7)
            self.assertEqual(result["progress"], 100)
        finally:
            manager.stop()

    def test_http_error_is_preserved(self) -> None:
        def processor(_payload, _update):
            raise HTTPException(status_code=422, detail={"reason": "bad_video"})

        manager = JobManager(processor)
        manager.start()
        try:
            submitted = manager.submit({})
            result = wait_for_terminal(manager, submitted["id"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_status"], 422)
            self.assertEqual(result["error"]["reason"], "bad_video")
        finally:
            manager.stop()

    def test_queued_job_can_be_cancelled(self) -> None:
        manager = JobManager(lambda payload, update: payload)
        submitted = manager.submit({"value": 1})
        cancelled = manager.cancel(submitted["id"])
        self.assertEqual(cancelled["status"], "cancelled")

    def test_queued_cancellation_discards_owned_resource_once(self) -> None:
        discarded = []
        manager = JobManager(
            lambda payload, update: payload,
            discarder=lambda payload: discarded.append(payload),
        )
        submitted = manager.submit({"kind": "upload", "upload_token": "abc"})
        manager.cancel(submitted["id"])
        manager.cancel(submitted["id"])
        self.assertEqual(discarded, [{"kind": "upload", "upload_token": "abc"}])

    def test_pending_capacity_is_bounded(self) -> None:
        manager = JobManager(lambda payload, update: payload, max_pending=1)
        manager.submit({"value": 1})
        with self.assertRaises(JobQueueFull):
            manager.submit({"value": 2})

    def test_cancelled_job_immediately_releases_pending_capacity(self) -> None:
        manager = JobManager(lambda payload, update: payload, max_pending=1)
        first = manager.submit({"value": 1})
        manager.cancel(first["id"])

        second = manager.submit({"value": 2})

        self.assertEqual(second["status"], "queued")
        self.assertEqual(manager.stats()["queued"], 1)

    def test_running_job_does_not_consume_pending_capacity(self) -> None:
        started = Event()
        release = Event()

        def processor(payload, _update):
            if payload["value"] == "running":
                started.set()
                release.wait(2)
            return payload

        manager = JobManager(processor, max_pending=1, worker_count=1)
        manager.start()
        try:
            manager.submit({"value": "running"})
            self.assertTrue(started.wait(1))
            manager.submit({"value": "queued"})
            with self.assertRaises(JobQueueFull):
                manager.submit({"value": "overflow"})
            self.assertEqual(manager.stats()["running"], 1)
            self.assertEqual(manager.stats()["queued"], 1)
        finally:
            release.set()
            manager.stop()

    def test_shutdown_discards_queued_resources(self) -> None:
        started = Event()
        release = Event()
        discarded = []

        def processor(payload, _update):
            if payload["value"] == "running":
                started.set()
                release.wait(2)
            return payload

        manager = JobManager(processor, worker_count=1, discarder=discarded.append)
        manager.start()
        try:
            manager.submit({"value": "running"})
            self.assertTrue(started.wait(1))
            queued = manager.submit({"value": "queued"})
            manager.stop(timeout=0.01)
            self.assertEqual(manager.get(queued["id"])["status"], "cancelled")
            self.assertEqual(discarded, [{"value": "queued"}])
        finally:
            release.set()
            manager.stop()

    def test_job_is_scoped_to_owner(self) -> None:
        manager = JobManager(lambda payload, update: payload)
        submitted = manager.submit({"value": 1}, owner_id=7)
        self.assertEqual(manager.get(submitted["id"], owner_id=7)["status"], "queued")
        with self.assertRaises(JobNotFound):
            manager.get(submitted["id"], owner_id=8)

    def test_completed_fast_path_skips_the_worker_queue(self) -> None:
        manager = JobManager(lambda payload, update: self.fail("processor should not run"))
        submitted = manager.submit_completed(
            {"value": 1},
            {"ok": True, "content": "cached"},
            owner_id=7,
        )
        self.assertEqual(submitted["status"], "completed")
        self.assertEqual(submitted["stage"], "cache_hit")
        self.assertEqual(submitted["result"]["content"], "cached")
        self.assertEqual(manager.stats()["queued"], 0)

    def test_idempotency_key_reuses_job_for_same_owner(self) -> None:
        manager = JobManager(lambda payload, update: payload, max_pending=2)
        first = manager.submit({"value": 1}, owner_id=7, idempotency_key="request-123")
        repeated = manager.submit({"value": 1}, owner_id=7, idempotency_key="request-123")
        other_owner = manager.submit({"value": 3}, owner_id=8, idempotency_key="request-123")

        self.assertEqual(first["id"], repeated["id"])
        self.assertFalse(first["reused"])
        self.assertTrue(repeated["reused"])
        self.assertNotEqual(first["id"], other_owner["id"])
        self.assertEqual(manager.stats()["queued"], 2)

    def test_idempotency_key_rejects_a_different_request(self) -> None:
        manager = JobManager(lambda payload, update: payload, max_pending=2)
        manager.submit({"value": 1}, owner_id=7, idempotency_key="request-456")

        with self.assertRaises(JobIdempotencyConflict):
            manager.submit({"value": 2}, owner_id=7, idempotency_key="request-456")

    def test_wait_returns_terminal_result_without_polling(self) -> None:
        manager = JobManager(lambda payload, update: {"value": payload["value"]})
        manager.start()
        try:
            submitted = manager.submit({"value": 9}, owner_id=7)
            result = manager.wait(submitted["id"], owner_id=7, timeout=2)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"]["value"], 9)
        finally:
            manager.stop()

    def test_second_worker_finishes_fast_job_while_first_is_blocked(self) -> None:
        slow_started = Event()
        release_slow = Event()

        def processor(payload, _update):
            if payload["value"] == "slow":
                slow_started.set()
                release_slow.wait(2)
            return {"ok": True, "value": payload["value"]}

        manager = JobManager(processor, worker_count=2)
        manager.start()
        try:
            slow = manager.submit({"value": "slow"})
            self.assertTrue(slow_started.wait(1))
            fast = manager.submit({"value": "fast"})
            fast_result = wait_for_terminal(manager, fast["id"], timeout=1)
            self.assertEqual(fast_result["result"]["value"], "fast")
            self.assertEqual(manager.get(slow["id"])["status"], "running")
            self.assertEqual(manager.stats()["workers_alive"], 2)
        finally:
            release_slow.set()
            manager.stop()

    def test_manager_restarts_after_stopping_during_a_running_job(self) -> None:
        started = Event()
        release = Event()

        def processor(payload, _update):
            if payload["value"] == "first":
                started.set()
                release.wait(2)
            return {"value": payload["value"]}

        manager = JobManager(processor, worker_count=1)
        manager.start()
        try:
            first = manager.submit({"value": "first"})
            self.assertTrue(started.wait(1))
            manager.stop(timeout=0.01)
            release.set()
            first_result = wait_for_terminal(manager, first["id"])
            self.assertEqual(first_result["status"], "completed")

            deadline = time.monotonic() + 1
            while any(worker.is_alive() for worker in manager.workers) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(any(worker.is_alive() for worker in manager.workers))

            manager.start()
            second = manager.submit({"value": "second"})
            second_result = wait_for_terminal(manager, second["id"])
            self.assertEqual(second_result["result"]["value"], "second")
        finally:
            release.set()
            manager.stop()

    def test_persistent_completed_result_survives_manager_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "jobs.db"
            first = JobManager(lambda payload, update: payload, state_path=state_path)
            submitted = first.submit_completed(
                {"value": 1},
                {"ok": True, "content": "cached"},
                owner_id=7,
            )

            restored = JobManager(lambda payload, update: payload, state_path=state_path)
            restored.start()
            try:
                result = restored.get(submitted["id"], owner_id=7)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["result"]["content"], "cached")
            finally:
                restored.stop()

    def test_persistent_link_job_is_requeued_after_unclean_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "jobs.db"
            first = JobManager(lambda payload, update: payload, state_path=state_path)
            submitted = first.submit({"input": "BV14jFvzbEvj"}, owner_id=7)

            restored = JobManager(
                lambda payload, update: {"ok": True, "input": payload["input"]},
                state_path=state_path,
            )
            restored.start()
            try:
                result = restored.wait(submitted["id"], owner_id=7, timeout=2)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["result"]["input"], "BV14jFvzbEvj")
            finally:
                restored.stop()

    def test_persistent_upload_job_reports_restart_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "jobs.db"
            first = JobManager(lambda payload, update: payload, state_path=state_path)
            submitted = first.submit(
                {"kind": "upload", "upload_token": "a" * 32},
                owner_id=7,
            )

            restored = JobManager(lambda payload, update: payload, state_path=state_path)
            restored.start()
            try:
                result = restored.get(submitted["id"], owner_id=7)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error_status"], 410)
                self.assertEqual(result["error"]["code"], "job_expired")
            finally:
                restored.stop()

    def test_persistent_running_link_job_is_not_resubmitted_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "jobs.db"
            first = JobManager(lambda payload, update: payload, state_path=state_path)
            submitted = first.submit({"input": "BV14jFvzbEvj"}, owner_id=7)
            with first.lock:
                record = first.records[submitted["id"]]
                record.status = "running"
                record.stage = "waiting_for_provider"
                first._persist_locked(record)

            calls = []
            restored = JobManager(
                lambda payload, update: calls.append(payload) or payload,
                state_path=state_path,
            )
            restored.start()
            try:
                result = restored.get(submitted["id"], owner_id=7)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error_status"], 410)
                self.assertEqual(result["error"]["code"], "job_expired")
                self.assertEqual(calls, [])
            finally:
                restored.stop()


if __name__ == "__main__":
    unittest.main()
