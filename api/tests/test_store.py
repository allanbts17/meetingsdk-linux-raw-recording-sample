from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from app.store import Store, StoreError

FINGERPRINT = hashlib.sha256(b"join-request").hexdigest()
SEALED = b"test-only-ciphertext-not-a-production-encryptor"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def join(self, key="idempotency-key-1"):
        return self.store.accept_join("backend", key, FINGERPRINT, SEALED)

    def test_failed_playback_snapshot_preserves_position_and_emits_one_safe_event(self):
        response, _ = self.join()
        bot = response["bot_id"]
        state = {"playback_id": "clip-1", "playback_state": "playing",
                 "position_seconds": 3.25, "meeting_status": 3,
                 "token": "private-value", "path": "/private/media"}
        self.store.snapshot(bot, state)
        state.update(playback_state="failed", position_seconds=4.5)
        self.store.snapshot(bot, state)
        self.store.snapshot(bot, state)
        failures = [e for e in self.store.events(bot, "backend")
                    if e["kind"] == "playback" and e["state"] == "failed"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(json.loads(failures[0]["data"]),
                         {"playback_id": "clip-1", "position_seconds": 4.5})
        self.assertEqual(self.store.session(bot, "backend")["state"], "active")
        self.assertNotIn("private", str(failures))

    def test_same_key_parallel_returns_one_durable_job(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.join(), range(8)))
        self.assertEqual(len({item[0]["bot_id"] for item in results}), 1)
        self.assertEqual(sum(not item[1] for item in results), 1)
        restarted = Store(self.path)
        job = restarted.claim("worker-1")
        self.assertEqual(job["payload"], SEALED)
        self.assertIsNone(restarted.claim("worker-2"))

    def test_different_keys_parallel_reserve_only_one_meeting(self):
        def attempt(index):
            try:
                return self.join(f"idempotency-key-{index:02}")[0]
            except StoreError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(results.count("CAPACITY_EXHAUSTED"), 7)

    def test_conflicting_reuse_does_not_change_job(self):
        response, _ = self.join()
        with self.assertRaisesRegex(StoreError, "IDEMPOTENCY_CONFLICT"):
            self.store.accept_join("backend", "idempotency-key-1", "a" * 64, SEALED)
        self.assertEqual(self.store.operation(response["operation_id"], "backend")["status"], "queued")

    def activate(self):
        response, _ = self.join()
        job = self.store.claim("worker")
        self.store.finish(job["id"], "worker", succeeded=True, session_state="active")
        return response["bot_id"]

    def test_serial_controls_owner_boundary_and_payload_purge(self):
        bot = self.activate()
        response, _ = self.store.accept_control("backend", bot, "play", "play-key-00000001", FINGERPRINT, SEALED)
        self.assertNotIn("payload", self.store.operation(response["operation_id"], "backend"))
        with self.assertRaisesRegex(StoreError, "BOT_NOT_FOUND"):
            self.store.session(bot, "other-backend")
        with self.assertRaisesRegex(StoreError, "OPERATION_IN_PROGRESS"):
            self.store.accept_control("backend", bot, "pause", "pause-key-000001", FINGERPRINT, SEALED)
        job = self.store.claim("worker")
        with self.assertRaisesRegex(StoreError, "CLAIM_LOST"):
            self.store.finish(job["id"], "other-worker", succeeded=True)
        self.store.finish(job["id"], "worker", succeeded=True)
        with self.store.connection() as db:
            self.assertIsNone(db.execute("SELECT payload FROM operations WHERE id=?", (job["id"],)).fetchone()[0])
        events = self.store.events(bot, "backend")
        self.assertGreaterEqual(len(events), 4)
        self.assertEqual(self.store.events(bot, "backend", after=events[-1]["sequence"]), [])

    def test_failed_session_reserves_until_cleanup_confirmed(self):
        self.join()
        job = self.store.claim("worker")
        self.store.finish(job["id"], "worker", succeeded=False, session_state="failed", error="AUTH_FAILED")
        self.assertEqual(self.store.capacity()["available"], 0)
        self.store.reconcile_restart(cleanup_confirmed=False)
        self.assertEqual(self.store.capacity()["available"], 0)
        self.store.reconcile_restart(cleanup_confirmed=True)
        self.assertEqual(self.store.capacity()["available"], 1)
        self.assertIsNone(self.store.claim("new-worker"))

    def test_restart_does_not_rejoin_and_preserves_idempotency(self):
        original, _ = self.join()
        self.store.claim("old-worker")
        restarted = Store(self.path)
        restarted.reconcile_restart(cleanup_confirmed=True)
        self.assertIsNone(restarted.claim("new-worker"))
        replay, is_replay = restarted.accept_join("backend", "idempotency-key-1", FINGERPRINT, SEALED)
        self.assertTrue(is_replay)
        self.assertEqual(replay, original)
        self.assertEqual(restarted.operation(original["operation_id"], "backend")["status"], "cancelled")

    def test_expired_key_remains_reserved_for_active_session(self):
        original, _ = self.join()
        with self.store.transaction() as db:
            db.execute("UPDATE idempotency SET expires=0")
        replay, is_replay = self.join()
        self.assertTrue(is_replay)
        self.assertEqual(replay, original)


if __name__ == "__main__":
    unittest.main()
