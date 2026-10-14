import os
from pathlib import Path
import tempfile
import unittest
from app.agent import Agent
from app.payloads import PayloadCipher
from app.sdk_control import ControlError
from app.store import Store, StoreError


class FakeRuntime:
    def __init__(self):
        self.bot = None
        self.state = {"in_meeting": False, "playback_state": "idle"}
        self.calls = []
        self.fail_start = False
        self.polls = 0
        self.first_media = False
        self.timeout_play = False

    def start(self, bot, meeting):
        if self.fail_start:
            raise RuntimeError("secret-password must not become a public error")
        self.bot = bot
        self.calls.append("join")
        self.state["in_meeting"] = True

    def status(self, bot):
        assert bot == self.bot
        self.polls += 1
        if self.first_media and self.polls >= 2:
            self.state["video_frames_sent"] = 1
            self.state["audio_blocks_sent"] = 1
        return dict(self.state)

    def command(self, bot, command, operation_id, **fields):
        assert bot == self.bot
        self.calls.append(command)
        if command == "play":
            self.polls = 0
            self.first_media = True
            self.state.update(playback_id=fields["playback_id"], playback_state="playing", video_frames_sent=0, audio_blocks_sent=0)
            if self.timeout_play:
                raise TimeoutError()
        else:
            if fields["playback_id"] != self.state.get("playback_id"):
                raise ControlError("PLAYBACK_ID_MISMATCH")
            self.state["playback_state"] = {"pause": "paused", "resume": "playing", "stop": "stopped"}[command]
        return dict(self.state)

    def stop(self, bot):
        assert self.bot == bot
        self.calls.append("leave")
        self.bot = None
        return True

    def cleanup(self, bot):
        if self.bot:
            return self.stop(bot)
        return True


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.runtime = FakeRuntime()
        self.cipher = PayloadCipher(os.urandom(32))
        self.agent = Agent(self.store, self.cipher, self.runtime, lambda media: "/tmp/cached.mp4", operation_timeout=1)
        self.meeting = {"meeting": {"number": "123456789", "password": "secret-password", "participant_name": "TestBot"}}

    def tearDown(self):
        self.temp.cleanup()

    def join(self):
        response, _ = self.agent.submit_join("owner", "join-key-00000001", self.meeting)
        self.assertEqual(self.runtime.calls, [])  # Submit is durable; never executes in HTTP request.
        self.agent.run_once()
        self.assertEqual(self.store.operation(response["operation_id"], "owner")["status"], "succeeded")
        return response["bot_id"]

    def control(self, bot, command, payload):
        response, _ = self.agent.submit_control("owner", bot, command, f"{command}-key-000000001", payload)
        self.agent.run_once()
        return self.store.operation(response["operation_id"], "owner")

    def test_lifecycle_first_sends_and_capacity_after_leave(self):
        bot = self.join()
        play = self.control(bot, "play", {"media": {"type": "video", "url": "https://storage.test/file?secret=query"}})
        self.assertEqual(play["status"], "succeeded")
        self.assertGreaterEqual(self.runtime.polls, 2)  # ACK/playing alone isn't first send.
        for command in ["pause", "resume", "stop"]:
            self.assertEqual(self.control(bot, command, {})["status"], "succeeded")
        self.assertEqual(self.store.capacity()["available"], 0)
        self.assertEqual(self.control(bot, "leave", {})["status"], "succeeded")
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_encrypted_submission_idempotency_and_tamper(self):
        original, _ = self.agent.submit_join("owner", "join-key-00000001", self.meeting)
        replay, repeated = self.agent.submit_join("owner", "join-key-00000001", self.meeting)
        self.assertTrue(repeated)
        self.assertEqual(original, replay)
        with self.store.transaction() as db:
            payload = db.execute("SELECT payload FROM operations").fetchone()[0]
            self.assertNotIn(b"secret-password", payload)
            db.execute("UPDATE operations SET payload=?", (payload[:-1] + bytes([payload[-1] ^ 1]),))
        self.agent.run_once()
        result = self.store.operation(original["operation_id"], "owner")
        self.assertEqual(result["error"], "PAYLOAD_AUTH_FAILED")
        self.assertEqual(self.runtime.calls, [])
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_timeout_reconciles_play_without_repeating_it(self):
        bot = self.join()
        self.runtime.timeout_play = True
        result = self.control(bot, "play", {"media": {"type": "audio", "url": "https://storage.test/file"}})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.runtime.calls.count("play"), 1)

    def test_stale_control_does_not_apply_to_new_playback(self):
        bot = self.join()
        self.control(bot, "play", {"media": {"type": "image", "url": "https://storage.test/image"}})
        result = self.control(bot, "pause", {"playback_id": "old-attempt"})
        self.assertEqual(result["error"], "PLAYBACK_ID_MISMATCH")
        self.assertEqual(self.runtime.state["playback_state"], "playing")

    def test_private_exception_is_not_persisted(self):
        self.runtime.fail_start = True
        response, _ = self.agent.submit_join("owner", "join-key-00000001", self.meeting)
        self.agent.run_once()
        result = self.store.operation(response["operation_id"], "owner")
        self.assertEqual(result["error"], "WORKER_OPERATION_FAILED")
        self.assertNotIn("secret-password", str(result))

    def test_invalid_meeting_or_extra_credentials_not_queued(self):
        for payload in [{"meeting": {"number": "bad-number"}}, {"meeting": self.meeting["meeting"], "client_secret": "forbidden"}]:
            with self.assertRaises(RuntimeError):
                self.agent.submit_join("owner", "join-key-00000001", payload)
        self.assertIsNone(self.store.claim("worker"))
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_media_type_fields_are_discriminated_before_queueing(self):
        bot = self.join()
        for media in [{"type": "image", "url": "https://storage.test/x", "audio_enabled": True},
                      {"type": "audio", "url": "http://storage.test/x"},
                      {"type": "image", "url": "https://storage.test/x", "duration_seconds": True}]:
            with self.assertRaises(RuntimeError):
                self.agent.submit_control("owner", bot, "play", "play-key-00000001", {"media": media})
        self.assertIsNone(self.store.claim("worker"))
