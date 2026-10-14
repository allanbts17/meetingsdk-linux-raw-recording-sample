"""Service entrypoint: nonsecret resource names only in arguments/environment."""
import argparse
import json
import os
import signal
from app.service import AgentService
from app.secrets import SecretError
from app.runtime import RuntimeErrorCode
from app.store import StoreError
from app.media import MediaError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", default=os.environ.get("ZOOM_STATE_ROOT", "/state"))
    parser.add_argument("--credentials-version", default=os.environ.get("ZOOM_SDK_SECRET_VERSION"))
    parser.add_argument("--master-key-version", default=os.environ.get("ZOOM_MASTER_KEY_VERSION"))
    args = parser.parse_args()
    service = None
    try:
        service = AgentService(args.state_root, args.credentials_version, args.master_key_version)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: service.agent.stopping.set())
        print(json.dumps({"event": "agent.ready", "capacity": service.store.capacity()}), flush=True)
        service.run()
        print(json.dumps({"event": "agent.stopped"}), flush=True)
        return 0
    except Exception as error:
        known = isinstance(error, (SecretError, RuntimeErrorCode, StoreError, MediaError))
        code = str(error) if known else "AGENT_SERVICE_FAILED"
        if not code or len(code) > 80 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for c in code):
            code = "AGENT_SERVICE_FAILED"
        print(json.dumps({"event": "agent.failed", "error": code}), flush=True)
        return 1
    finally:
        if service is not None:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
