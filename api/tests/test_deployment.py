import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from app.store import Store, StoreError
from app.runtime import SdkRuntime, RuntimeErrorCode
from tools.agent_health import main as health_probe


source = Path(__file__).resolve().parents[2] / 'deploy' / 'host_reconcile.py'
spec = importlib.util.spec_from_file_location('host_reconcile', source)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zb-')
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state.db')
        self.now = time.time()

    def tearDown(self):
        self.temp.cleanup()

    def terminal(self, cleanup=True):
        response, _ = self.store.accept_join('owner', str(uuid.uuid4()), 'a' * 64, b'sealed')
        job = self.store.claim('worker')
        self.store.finish(job['id'], 'worker', succeeded=False, session_state='failed', cleanup_confirmed=cleanup)
        return response

    def age(self):
        with self.store.transaction() as db:
            db.execute('UPDATE sessions SET created=?', (self.now - 100,))
            db.execute('UPDATE operations SET created=?', (self.now - 100,))
            db.execute('UPDATE operation_details SET completed=?', (self.now - 100,))
            db.execute('UPDATE events SET created=?', (self.now - 100,))
            db.execute('UPDATE idempotency SET expires=?', (self.now - 1,))

    def test_retention_removes_only_old_confirmed_terminal_history(self):
        response = self.terminal()
        self.age()
        self.assertEqual(self.store.prune_history(retention_seconds=60, now=self.now), 1)
        with self.assertRaisesRegex(StoreError, 'BOT_NOT_FOUND'):
            self.store.session(response['bot_id'], 'owner')
        with self.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_retention_preserves_unconfirmed_capacity_and_live_replay_keys(self):
        self.terminal(cleanup=False)
        self.age()
        self.assertEqual(self.store.prune_history(retention_seconds=60, now=self.now), 0)
        self.assertEqual(self.store.capacity()['occupied'], 1)
        with self.store.transaction() as db:
            db.execute('UPDATE sessions SET reserves=0')
            db.execute('UPDATE idempotency SET expires=?', (self.now + 60,))
        self.assertEqual(self.store.prune_history(retention_seconds=60, now=self.now), 0)

    def test_retention_uses_completion_and_preserves_unfinished_jobs(self):
        self.terminal()
        self.age()
        with self.store.transaction() as db:
            db.execute('UPDATE operation_details SET completed=?', (self.now,))
        self.assertEqual(self.store.prune_history(retention_seconds=60, now=self.now), 0)
        with self.store.transaction() as db:
            db.execute('UPDATE operation_details SET completed=?', (self.now - 100,))
            db.execute("UPDATE operations SET status='queued'")
        self.assertEqual(self.store.prune_history(retention_seconds=60, now=self.now), 0)

    def manifest(self):
        directory = self.root / 'r' / str(uuid.uuid4())
        directory.mkdir(parents=True)
        data = {'token': str(uuid.uuid4()), 'boot_id': str(uuid.uuid4()), 'pid_namespace': 'pid:[999999]', 'container_id': 'a' * 12}
        (directory / 'launch.json').write_text(json.dumps(data))
        container = {'Id': 'a' * 64, 'Config': {'Hostname': 'a' * 12, 'Labels': {'com.zoom-bot.managed': 'true'}},
                     'Mounts': [{'Source': str(self.root), 'Destination': '/state'}],
                     'State': {'Running': False, 'Pid': 0, 'Status': 'exited'}}
        return directory, data, container

    def test_host_requires_container_and_namespace_death_before_removal(self):
        directory, data, container = self.manifest()
        container['State']['Running'] = True
        with self.assertRaisesRegex(host.RecoveryError, 'PREVIOUS_CONTAINER_STILL_ACTIVE'):
            host.reconcile(self.root, inspect=lambda _: container, alive=lambda _: False, boot_id=data['boot_id'])
        self.assertTrue(directory.exists())
        container['State']['Running'] = False
        with self.assertRaisesRegex(host.RecoveryError, 'PREVIOUS_NAMESPACE_STILL_ACTIVE'):
            host.reconcile(self.root, inspect=lambda _: container, alive=lambda _: True, boot_id=data['boot_id'])
        self.assertTrue(directory.exists())
        self.assertEqual(host.reconcile(self.root, inspect=lambda _: container, alive=lambda _: False, boot_id=data['boot_id']), 1)
        self.assertFalse(directory.exists())

    def test_host_rejects_unmanaged_container_and_symlink(self):
        directory, data, container = self.manifest()
        container['Config']['Labels'] = {}
        with self.assertRaisesRegex(host.RecoveryError, 'PREVIOUS_CONTAINER_NOT_VERIFIED'):
            host.reconcile(self.root, inspect=lambda _: container, boot_id=data['boot_id'])
        self.assertTrue(directory.exists())
        linked = self.root / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(host.RecoveryError, 'INVALID_STATE_ROOT'):
            host.reconcile(linked)

    def test_host_reboot_proof_does_not_require_old_container(self):
        directory, data, _ = self.manifest()
        def not_inspect(_):
            raise AssertionError('Old boot processes cannot exist')
        self.assertEqual(host.reconcile(self.root, inspect=not_inspect, boot_id=str(uuid.uuid4())), 1)
        self.assertFalse(directory.exists())

    def test_media_mount_must_reference_the_same_cached_file(self):
        cache, mirror = self.root / 'media', self.root / 'mirror'
        cache.mkdir(); mirror.mkdir()
        path = cache / 'sample.mp4'
        path.write_bytes(b'test')
        runtime = SdkRuntime(self.root / 'r', lambda: {}, media_root=cache, read_only_media_root=mirror)
        (mirror / path.name).write_bytes(b'test')
        with self.assertRaisesRegex(RuntimeErrorCode, 'MEDIA_MOUNT_MISMATCH'):
            runtime.media_path(path)
        (mirror / path.name).unlink()
        os.link(path, mirror / path.name)
        self.assertEqual(runtime.media_path(path), mirror / path.name)

    def test_health_probe_reads_state_without_releasing_capacity(self):
        self.terminal(cleanup=False)
        self.store.heartbeat('worker')
        with patch.dict(os.environ, {'ZOOM_STATE_ROOT': str(self.root)}):
            self.assertEqual(health_probe(), 0)
            self.store.heartbeat('worker', ready=False)
            self.assertEqual(health_probe(), 1)
        self.assertEqual(self.store.capacity()['occupied'], 1)
