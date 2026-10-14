"""Host-only recovery. Never free state on the assumption that a container is dead."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid


class RecoveryError(RuntimeError):
    pass


def inspect_container(identifier):
    result = subprocess.run(["docker", "inspect", identifier], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RecoveryError("PREVIOUS_CONTAINER_NOT_VERIFIED")
    return json.loads(result.stdout)[0]


def namespace_alive(namespace):
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            if os.readlink(path / "ns/pid") == namespace:
                return True
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            raise RecoveryError("HOST_PROCESS_INSPECTION_DENIED") from None
    return False


def reconcile(state_root, *, inspect=inspect_container, alive=namespace_alive, boot_id=None):
    supplied = Path(state_root).absolute()
    if supplied.is_symlink() or supplied.resolve() != supplied:
        raise RecoveryError("INVALID_STATE_ROOT")
    root = supplied / "r"
    if root.is_symlink():
        raise RecoveryError("INVALID_STATE_ROOT")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(root / ".owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RecoveryError("AGENT_STILL_OWNS_STATE") from None
        boot_id = boot_id or Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        removed = 0
        for directory in root.iterdir():
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
                    uuid.UUID(data["token"])
                    uuid.UUID(data["boot_id"])
                    if not re.fullmatch(r"pid:\[[0-9]+\]", data["pid_namespace"]):
                        raise ValueError()
                    if data["boot_id"] == boot_id:
                        identifier = data["container_id"]
                        if not re.fullmatch(r"[0-9a-f]{12,64}", identifier):
                            raise ValueError()
                        container = inspect(identifier)
                        labels = container["Config"].get("Labels") or {}
                        valid_mount = any(Path(mount.get("Source", "")) == supplied and mount.get("Destination") == "/state"
                                          for mount in container.get("Mounts", []))
                        if not container["Id"].startswith(identifier) or container["Config"]["Hostname"] != identifier or labels.get("com.zoom-bot.managed") != "true" or not valid_mount:
                            raise RecoveryError("PREVIOUS_CONTAINER_NOT_VERIFIED")
                        state = container["State"]
                        if state.get("Running") or state.get("Pid") != 0 or state.get("Status") not in {"exited", "dead"}:
                            raise RecoveryError("PREVIOUS_CONTAINER_STILL_ACTIVE")
                        if alive(data["pid_namespace"]):
                            raise RecoveryError("PREVIOUS_NAMESPACE_STILL_ACTIVE")
                elif any(path.name not in {"config.txt", "sdk.log"} for path in directory.iterdir()):
                    raise ValueError()
                # Exact UUID child of verified state/r; config/logs disappear only after proof.
                shutil.rmtree(directory)
                removed += 1
            except (ValueError, KeyError, TypeError, OSError):
                raise RecoveryError("INVALID_RUNTIME_MANIFEST") from None
        return removed
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", default="/var/lib/zoom-bot")
    args = parser.parse_args()
    try:
        removed = reconcile(args.state_root)
        print(json.dumps({"event": "host.reconciled", "runtime_directories_removed": removed}))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, RecoveryError) else "HOST_RECOVERY_FAILED"
        print(json.dumps({"event": "host.recovery_failed", "error": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
