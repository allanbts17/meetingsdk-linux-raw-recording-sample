from pathlib import Path
import tempfile
import threading
import time
import unittest
from app.agent import Agent
from app.media import MediaError
from app.payloads import PayloadCipher
from app.store import Store, StoreError
from test_agent import FakeRuntime


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zb-")
        self.store = Store(Path(self.temp.name) / "state.db")
        self.runtime = FakeRuntime()
        self.agent = Agent(self.store, PayloadCipher(bytes(range(32))), self.runtime,
                           lambda media: "/tmp/test.mp4", operation_timeout=1)
        self.owner = "owner"
        self.join, _ = self.agent.submit_join(self.owner, "join-key-00000001", {"meeting": {"number": "123456789"}})
        self.bot = self.join["bot_id"]

    def tearDown(self):
        self.agent.stopping.set()
        self.temp.cleanup()

    def control(self, command, payload=None, key=None):
        return self.agent.submit_control(self.owner, self.bot, command, key or f"{command}-key-00000001", payload or {})[0]

    def play(self):
        return self.control("play", {"media": {"type": "video", "url": "https://storage.test/test.mp4"}})

    def result(self, response):
        return self.store.operation(response["operation_id"], self.owner)

    def test_stop_cancels_queued_play_and_keeps_meeting(self):
        self.agent.run_once()
        play = self.play()
        stop = self.control("stop", {"playback_id": play["playback_id"]})
        self.assertEqual(self.result(play)["status"], "cancelled")
        with self.store.connection() as db:
            self.assertIsNone(db.execute("SELECT payload FROM operations WHERE id=?", (play["operation_id"],)).fetchone()[0])
        self.agent.run_once()
        self.assertEqual(self.result(stop)["status"], "succeeded")
        self.assertEqual(self.runtime.calls, ["join"])
        self.assertEqual(self.store.capacity()["available"], 0)

    def test_stop_interrupts_running_download_before_sdk_play(self):
        self.agent.run_once()
        entered = threading.Event()
        class Resolver:
            def resolve(self, media, cancel):
                entered.set()
                while not cancel.is_set():
                    time.sleep(0.01)
                raise MediaError("MEDIA_DOWNLOAD_CANCELLED")
        self.agent.media_resolver = Resolver()
        play = self.play()
        thread = threading.Thread(target=self.agent.run_once)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            stop = self.control("stop", {"playback_id": play["playback_id"]})
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(self.result(play)["status"], "cancelled")
            self.assertEqual(self.result(play)["error"], "CANCELLED_BY_STOP")
            self.agent.run_once()
            self.assertEqual(self.result(stop)["status"], "succeeded")
            self.assertNotIn("play", self.runtime.calls)
        finally:
            self.agent.stopping.set()
            thread.join(3)

    def test_leave_interrupts_join_and_reserves_until_leave_finishes(self):
        original_start = self.runtime.start
        def waiting(bot, meeting):
            original_start(bot, meeting)
            self.runtime.state["in_meeting"] = False
        self.runtime.start = waiting
        thread = threading.Thread(target=self.agent.run_once)
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and self.runtime.bot is None:
                time.sleep(0.01)
            leave = self.control("leave")
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(self.result(self.join)["status"], "cancelled")
            self.assertEqual(self.store.capacity()["available"], 0)
            self.agent.run_once()
            self.assertEqual(self.result(leave)["status"], "succeeded")
            self.assertEqual(self.store.capacity()["available"], 1)
        finally:
            self.agent.stopping.set()
            thread.join(3)

    def test_leave_preempts_stop_and_reuses_pending_leave(self):
        self.agent.run_once()
        play = self.play()
        stop = self.control("stop")
        leave = self.control("leave")
        other = self.control("leave", key="second-leave-key-01")
        self.assertEqual(other["operation_id"], leave["operation_id"])
        self.assertEqual(self.result(play)["status"], "cancelled")
        self.assertEqual(self.result(stop)["status"], "cancelled")
        self.agent.run_once()
        self.assertEqual(self.result(leave)["status"], "succeeded")
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_stale_stop_does_not_cancel_new_pending_play(self):
        self.agent.run_once()
        play = self.play()
        with self.assertRaisesRegex(StoreError, "PLAYBACK_ID_MISMATCH"):
            self.control("stop", {"playback_id": "old-attempt"})
        self.assertEqual(self.result(play)["status"], "queued")
        self.assertIsNone(self.store.cancellation_reason(play["operation_id"]))

    def test_completed_play_ack_is_not_relabelled_cancelled(self):
        self.agent.run_once()
        play = self.play()
        acknowledged = threading.Event()
        release = threading.Event()
        original_finish = self.store.finish
        def finish(operation_id, *args, **kwargs):
            if operation_id == play["operation_id"] and kwargs.get("succeeded"):
                acknowledged.set()
                if not release.wait(3):
                    raise AssertionError("test synchronization timeout")
            return original_finish(operation_id, *args, **kwargs)
        self.store.finish = finish
        thread = threading.Thread(target=self.agent.run_once)
        thread.start()
        try:
            self.assertTrue(acknowledged.wait(2))
            stop = self.control("stop")
            release.set()
            thread.join(3)
            self.assertEqual(self.result(play)["status"], "succeeded")
            self.agent.run_once()
            self.assertEqual(self.result(stop)["status"], "succeeded")
            self.assertEqual(self.runtime.state["playback_state"], "stopped")
        finally:
            release.set()
            self.agent.stopping.set()
            thread.join(3)
