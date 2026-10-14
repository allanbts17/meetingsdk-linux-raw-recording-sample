"""Persistent Linux worker. HTTP transport is added separately; never auto-join."""
import json
import os
from pathlib import Path
import threading
from .agent import Agent
from .media import MediaCache
from .payloads import PayloadCipher
from .recovery import RuntimeRecovery
from .runtime import SdkRuntime, RuntimeErrorCode
from .secrets import SecretProvider
from .store import Store


def pin_key_version(root, version):
    marker = root / "key-version.json"
    if marker.exists():
        if marker.is_symlink() or json.loads(marker.read_text()) != {"version": version}:
            raise RuntimeErrorCode("MASTER_KEY_VERSION_CHANGED")
        return
    descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump({"version": version}, file)
        file.flush()
        os.fsync(file.fileno())
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class AgentService:
    def __init__(self, root, credentials_version, master_key_version, *, provider=None, heartbeat_interval=5):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        # The same flock covers recovery, secret configuration and the worker lifetime.
        self.recovery = RuntimeRecovery(self.root / "r")
        self.store = None
        self.agent = None
        self.heartbeat_stop = threading.Event()
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_thread = None
        try:
            self.store = Store(self.root / "state.db")
            provider = provider or SecretProvider(credentials_version, master_key_version)
            key = provider.master_key()
            provider.credentials()  # Fail startup before claiming a job if access is missing.
            pin_key_version(self.root, master_key_version)
            self.recovery.reconcile()
            self.store.reconcile_restart(cleanup_confirmed=True)
            cache = MediaCache(self.root / "media")
            cache.reconcile_pins(cleanup_confirmed=True)
            runtime = SdkRuntime(self.root / "r", provider.credentials)
            self.agent = Agent(self.store, PayloadCipher(key), runtime, cache)
            self.store.heartbeat(self.agent.worker_id)
        except BaseException:
            if self.store is not None:
                self.store.reconcile_restart(cleanup_confirmed=False)
            self.recovery.close()
            raise

    def heartbeat(self):
        try:
            while not self.heartbeat_stop.is_set():
                self.store.heartbeat(self.agent.worker_id, ready=not self.agent.stopping.is_set())
                self.heartbeat_stop.wait(self.heartbeat_interval)
        except Exception:
            # A worker unable to persist its heartbeat stops accepting/executing work.
            self.agent.stopping.set()

    def run(self):
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, name="agent-heartbeat")
        self.heartbeat_thread.start()
        try:
            self.agent.run()
        finally:
            self.close()

    def close(self):
        if self.recovery.descriptor is None:
            return
        try:
            if self.agent is not None:
                self.agent.stopping.set()
                self.heartbeat_stop.set()
                if self.heartbeat_thread is not None:
                    self.heartbeat_thread.join(timeout=self.heartbeat_interval + 6)
                self.store.heartbeat(self.agent.worker_id, ready=False)
                for session in self.store.reserved_sessions():
                    self.agent.end_supervised(session, "AGENT_STOPPING")
                try:
                    self.recovery.reconcile()
                    for session in self.store.reserved_sessions():
                        self.store.end_session(session["id"], "AGENT_STOPPING", cleanup_confirmed=True)
                    self.agent.media_resolver.reconcile_pins(cleanup_confirmed=True)
                except Exception:
                    pass  # Retain reservations and pins until the next confirmed recovery.
        finally:
            self.recovery.close()
