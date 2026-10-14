"""Single owner and orphan cleanup using private launch tokens and Linux pidfds."""
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import shutil
import time
import uuid
from .runtime import RuntimeErrorCode


class RuntimeRecovery:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.descriptor = os.open(self.root / ".owner.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.descriptor)
            self.descriptor = None
            raise RuntimeErrorCode("AGENT_ALREADY_RUNNING") from None

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    @staticmethod
    def identity():
        return {"boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "pid_namespace": os.readlink("/proc/self/ns/pid")}

    @staticmethod
    def tagged(token):
        expected = f"ZOOM_RUNTIME_TOKEN={token}".encode()
        found = []
        for directory in Path("/proc").iterdir():
            if not directory.name.isdigit():
                continue
            try:
                environment = (directory / "environ").read_bytes().split(b"\0")
                if expected in environment:
                    found.append(int(directory.name))
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                # Processes belonging to our uid must be inspectable before absence is proven.
                try:
                    if directory.stat().st_uid == os.getuid():
                        raise RuntimeErrorCode("SDK_CLEANUP_UNCONFIRMED")
                except FileNotFoundError:
                    continue
        return found

    @classmethod
    def terminate(cls, token, timeout=3):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in cls.tagged(token):
                descriptor = None
                try:
                    descriptor = os.pidfd_open(pid)
                    # Recheck ownership after opening. pidfd then prevents PID reuse races.
                    if f"ZOOM_RUNTIME_TOKEN={token}".encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                        signal.pidfd_send_signal(descriptor, sig)
                except (FileNotFoundError, ProcessLookupError):
                    pass
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not cls.tagged(token):
                    return True
                time.sleep(0.05)
        if cls.tagged(token):
            raise RuntimeErrorCode("SDK_CLEANUP_UNCONFIRMED")
        return True

    def reconcile(self):
        """Do not call without the exclusive owner lock; never rejoin old sessions."""
        for directory in self.root.iterdir():
            if directory.name == ".owner.lock":
                continue
            try:
                uuid.UUID(directory.name)
                if directory.is_symlink() or not directory.is_dir():
                    raise ValueError()
                manifest = directory / "launch.json"
                if manifest.is_symlink():
                    raise ValueError()
                if manifest.exists():
                    data = json.loads(manifest.read_text())
                    token = data["token"]
                    uuid.UUID(token)
                    uuid.UUID(data["boot_id"])
                    if not re.fullmatch(r"pid:\[[0-9]+\]", data["pid_namespace"]):
                        raise ValueError()
                    identity = self.identity()
                    if data["boot_id"] == identity["boot_id"]:
                        if data["pid_namespace"] != identity["pid_namespace"]:
                            # Other containers' processes are invisible here. Require host proof.
                            raise RuntimeErrorCode("RUNTIME_NAMESPACE_CHANGED")
                        self.terminate(token)
                    # After a host reboot the previous processes cannot remain alive.
                else:
                    # The manifest is durably written before any child can start.
                    # A prelaunch crash may leave an empty/config-only directory.
                    if any(path.name not in {"config.txt", "sdk.log"} for path in directory.iterdir()):
                        raise ValueError()
                shutil.rmtree(directory)
            except (ValueError, KeyError, TypeError, OSError):
                raise RuntimeErrorCode("SDK_CLEANUP_UNCONFIRMED") from None
        return True
