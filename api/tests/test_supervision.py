import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from app.agent import Agent, OperationCancellation
from app.payloads import PayloadCipher
from app.recovery import RuntimeRecovery
from app.runtime import SdkRuntime, RuntimeErrorCode
from app.service import AgentService
from app.store import Store
from app.media import MediaCache, MediaError


class Provider:
    def master_key(self):
        return bytes(range(32))

    def credentials(self):
        return {"clientId": "test-id", "clientSecret": "test-secret"}


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zb-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state.db")

    def tearDown(self):
        self.temp.cleanup()

    def session(self):
        response, _ = self.store.accept_join("owner", str(uuid.uuid4()), "a" * 64, b"sealed")
        job = self.store.claim("worker")
        self.store.finish(job["id"], "worker", succeeded=True, session_state="active")
        self.store.set_deadline(response["bot_id"], 60)
        return response["bot_id"]

    def test_heartbeat_stale_or_stopped_never_releases_capacity(self):
        self.session()
        self.store.heartbeat("worker")
        self.assertTrue(self.store.health()["ready"])
        with self.store.transaction() as db:
            db.execute("UPDATE worker_health SET updated=?", (time.time() - 16,))
        self.assertFalse(self.store.health()["ready"])
        self.assertEqual(self.store.capacity()["available"], 0)
        self.store.heartbeat("worker", ready=False)
        self.assertFalse(self.store.health()["ready"])

    def test_deadline_counts_from_acceptance_and_cancels_download(self):
        bot = self.session()
        with self.store.transaction() as db:
            db.execute("UPDATE sessions SET created=? WHERE id=?", (time.time() - 70, bot))
        deadline = self.store.set_deadline(bot, 60)
        agent = Agent(self.store, PayloadCipher(bytes(range(32))), object())
        cancellation = OperationCancellation(agent, deadline)
        self.assertTrue(cancellation.is_set())
        self.assertEqual(cancellation.reason(), "SESSION_TIMEOUT")

    def test_expired_queued_join_never_launches_sdk(self):
        class Runtime:
            def start(self, *args):
                raise AssertionError("SDK must not start")
            def cleanup(self, *args):
                return True
        agent = Agent(self.store, PayloadCipher(bytes(range(32))), Runtime())
        response, _ = agent.submit_join("owner", "expired-key-0001", {"meeting": {"number": "123456789"},
            "options": {"max_session_seconds": 60}})
        with self.store.transaction() as db:
            db.execute("UPDATE sessions SET created=?", (time.time() - 70,))
        agent.run_once()
        result = self.store.operation(response["operation_id"], "owner")
        self.assertEqual(result["error"], "SESSION_TIMEOUT")
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_idle_session_timeout_cleans_runtime_and_releases_capacity(self):
        bot = self.session()
        class Runtime:
            bot_id = bot
            def cleanup(self, identifier):
                return True
        with self.store.transaction() as db:
            db.execute("UPDATE session_limits SET deadline=?", (time.time() - 1,))
        agent = Agent(self.store, PayloadCipher(bytes(range(32))), Runtime())
        agent.supervise()
        self.assertEqual(self.store.capacity()["available"], 1)
        self.assertEqual(self.store.events(bot, "owner")[-1]["kind"], "SESSION_TIMEOUT")

    def test_unresponsive_and_reconnect_timeouts_require_cleanup(self):
        bot = self.session()
        class Runtime:
            bot_id = bot
            def status(self, identifier):
                return {"meeting_status": 5, "in_meeting": False}
            def cleanup(self, identifier):
                return True
        agent = Agent(self.store, PayloadCipher(bytes(range(32))), Runtime())
        agent.supervise()
        self.assertEqual(self.store.capacity()["available"], 0)
        agent.reconnecting_since[bot] = time.monotonic() - 121
        agent.supervise()
        self.assertEqual(self.store.capacity()["available"], 1)
        self.assertEqual(self.store.events(bot, "owner")[-1]["kind"], "RECONNECT_TIMEOUT")
        bot = self.session()
        agent.runtime.bot_id = bot
        def unavailable(identifier):
            raise TimeoutError()
        agent.runtime.status = unavailable
        agent.supervise()
        self.assertEqual(self.store.capacity()["available"], 0)
        agent.unresponsive_since[bot] = time.monotonic() - 16
        agent.supervise()
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_supervisor_cleanup_failure_preserves_reservation(self):
        bot = self.session()
        class Runtime:
            bot_id = bot
            def status(self, identifier):
                raise RuntimeErrorCode("SDK_PROCESS_EXITED")
            def cleanup(self, identifier):
                raise RuntimeErrorCode("SDK_CLEANUP_UNCONFIRMED")
        agent = Agent(self.store, PayloadCipher(bytes(range(32))), Runtime())
        agent.supervise()
        self.assertEqual(self.store.session(bot, "owner")["state"], "failed")
        self.assertEqual(self.store.capacity()["available"], 0)
        events = len(self.store.events(bot, "owner"))
        agent.supervise()
        self.assertEqual(len(self.store.events(bot, "owner")), events)
        agent.runtime.cleanup = lambda identifier: True
        agent.supervise()
        self.assertEqual(self.store.capacity()["available"], 1)

    def test_snapshot_drops_private_fields(self):
        bot = self.session()
        self.store.snapshot(bot, {"position_seconds": 2.5, "playback_state": "playing",
                                  "path": "/private", "token": "secret"})
        with self.store.connection() as db:
            data = db.execute("SELECT body FROM snapshots").fetchone()[0]
        self.assertNotIn("secret", data)
        self.assertEqual(json.loads(data), {"position_seconds": 2.5, "playback_state": "playing"})

    def test_singleton_and_key_pin_and_restart_without_rejoin(self):
        sdk, key = "projects/test/secrets/sdk/versions/1", "projects/test/secrets/key/versions/1"
        service = AgentService(self.root, sdk, key, provider=Provider(), heartbeat_interval=0.05)
        try:
            response, _ = service.agent.submit_join("owner", "restart-key-0001", {"meeting": {"number": "123456789"}})
            with self.assertRaisesRegex(RuntimeErrorCode, "AGENT_ALREADY_RUNNING"):
                AgentService(self.root, sdk, key, provider=Provider())
        finally:
            service.close()
        restarted = AgentService(self.root, sdk, key, provider=Provider())
        try:
            self.assertIsNone(restarted.store.claim("new-worker"))
            self.assertEqual(restarted.store.operation(response["operation_id"], "owner")["status"], "cancelled")
            replay, repeated = restarted.agent.submit_join("owner", "restart-key-0001", {"meeting": {"number": "123456789"}})
            self.assertTrue(repeated)
            self.assertEqual(response, replay)
            self.assertEqual(restarted.store.capacity()["available"], 1)
        finally:
            restarted.close()
        with self.assertRaisesRegex(RuntimeErrorCode, "MASTER_KEY_VERSION_CHANGED"):
            AgentService(self.root, sdk, key.replace("/1", "/2"), provider=Provider())

    def test_heartbeat_runs_while_worker_operation_blocks(self):
        service = AgentService(self.root, "projects/test/secrets/sdk/versions/1",
                               "projects/test/secrets/key/versions/1", provider=Provider(), heartbeat_interval=0.03)
        entered = threading.Event()
        def blocked():
            entered.set()
            service.agent.stopping.wait()
        service.agent.run = blocked
        thread = threading.Thread(target=service.run)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with service.store.connection() as db:
                before = db.execute("SELECT updated FROM worker_health").fetchone()[0]
            time.sleep(0.1)
            with service.store.connection() as db:
                after = db.execute("SELECT updated FROM worker_health").fetchone()[0]
            self.assertGreater(after, before)
        finally:
            service.agent.stopping.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(service.store.health()["ready"])

    def test_crash_pins_only_cleared_after_confirmed_cleanup(self):
        cache = MediaCache(self.root / "media", reserve=0)
        media = cache.root / ("a" * 64 + ".mp4")
        media.write_bytes(b"test")
        lease = cache.lease(media, {})
        with self.assertRaisesRegex(MediaError, "SDK_CLEANUP_UNCONFIRMED"):
            cache.reconcile_pins()
        self.assertTrue(lease.marker.exists())
        cache.reconcile_pins(cleanup_confirmed=True)
        self.assertFalse(lease.marker.exists())

    def test_recovery_kills_tagged_descendants_but_not_unrelated_process(self):
        runtime_root = self.root / "r"
        recovery = RuntimeRecovery(runtime_root)
        bot_dir = runtime_root / str(uuid.uuid4())
        bot_dir.mkdir()
        token = str(uuid.uuid4())
        (bot_dir / "launch.json").write_text(json.dumps(dict(recovery.identity(), token=token)))
        unrelated = subprocess.Popen(["sleep", "30"])
        orphan = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & wait"],
                                  env=dict(os.environ, ZOOM_RUNTIME_TOKEN=token), start_new_session=True)
        try:
            time.sleep(0.1)
            self.assertGreaterEqual(len(recovery.tagged(token)), 2)
            recovery.reconcile()
            orphan.wait(3)
            self.assertEqual(recovery.tagged(token), [])
            self.assertIsNone(unrelated.poll())
            self.assertFalse(bot_dir.exists())
        finally:
            orphan.kill() if orphan.poll() is None else None
            orphan.wait()
            unrelated.terminate()
            unrelated.wait()
            recovery.close()

    def test_recovery_inspection_failure_never_deletes_directory(self):
        recovery = RuntimeRecovery(self.root / "r")
        directory = recovery.root / str(uuid.uuid4())
        directory.mkdir()
        (directory / "launch.json").write_text(json.dumps(dict(recovery.identity(), token=str(uuid.uuid4()))))
        try:
            with patch.object(RuntimeRecovery, "terminate", side_effect=RuntimeErrorCode("SDK_CLEANUP_UNCONFIRMED")):
                with self.assertRaisesRegex(RuntimeErrorCode, "SDK_CLEANUP_UNCONFIRMED"):
                    recovery.reconcile()
            self.assertTrue(directory.exists())
        finally:
            recovery.close()

    def test_changed_container_namespace_requires_host_confirmation(self):
        recovery = RuntimeRecovery(self.root / "r")
        directory = recovery.root / str(uuid.uuid4())
        directory.mkdir()
        data = dict(recovery.identity(), token=str(uuid.uuid4()))
        data["pid_namespace"] = "pid:[1]"
        (directory / "launch.json").write_text(json.dumps(data))
        try:
            with self.assertRaisesRegex(RuntimeErrorCode, "RUNTIME_NAMESPACE_CHANGED"):
                recovery.reconcile()
            self.assertTrue(directory.exists())
            data["boot_id"] = str(uuid.uuid4())
            (directory / "launch.json").write_text(json.dumps(data))
            self.assertTrue(recovery.reconcile())
            self.assertFalse(directory.exists())
        finally:
            recovery.close()

    def test_real_runtime_launch_and_forced_cleanup(self):
        executable = self.root / "fake-sdk"
        executable.write_text("#!/bin/sh\nsleep 30 & wait\n")
        executable.chmod(0o700)
        runtime = SdkRuntime(self.root / "r", Provider().credentials, executable)
        bot = str(uuid.uuid4())
        runtime.start(bot, {"number": "123456789"})
        token = runtime.token
        try:
            time.sleep(0.15)
            self.assertGreaterEqual(len(RuntimeRecovery.tagged(token)), 2)
            runtime.process.kill()
            runtime.process.wait()
            self.assertTrue(runtime.cleanup(bot))
            self.assertEqual(RuntimeRecovery.tagged(token), [])
            self.assertFalse((runtime.root / bot).exists())
        finally:
            if runtime.process:
                RuntimeRecovery.terminate(token)
                runtime.process.wait()

    def test_launcher_dies_when_parent_is_killed(self):
        token = str(uuid.uuid4())
        launcher = Path(__file__).resolve().parents[1] / "app" / "sdk_launcher.py"
        code = "import subprocess,sys,time,os; p=subprocess.Popen([sys.executable,sys.argv[1],str(os.getpid()),sys.argv[2]]); print(p.pid,flush=True); time.sleep(30)"
        executable = self.root / "sleeper"
        executable.write_text("#!/bin/sh\nexec sleep 30\n")
        executable.chmod(0o700)
        parent = subprocess.Popen([sys.executable, "-c", code, str(launcher), str(executable)],
                                  env=dict(os.environ, ZOOM_RUNTIME_TOKEN=token), stdout=subprocess.PIPE, text=True)
        try:
            child = int(parent.stdout.readline())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and child not in RuntimeRecovery.tagged(token):
                time.sleep(0.02)
            parent.kill()
            parent.wait()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and RuntimeRecovery.tagged(token):
                time.sleep(0.05)
            self.assertEqual(RuntimeRecovery.tagged(token), [])
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait()
            parent.stdout.close()
            RuntimeRecovery.terminate(token)
