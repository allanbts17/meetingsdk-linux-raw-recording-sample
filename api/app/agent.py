"""Durable submission and synchronous worker steps, independent of HTTP lifetime."""
import threading
import time
import uuid
from .payloads import context, PayloadError
from .runtime import RuntimeErrorCode
from .sdk_control import ControlError
from .store import StoreError
from .validation import join_payload, control_payload


class Agent:
    def __init__(self, store, cipher, runtime, media_resolver=None, operation_timeout=30):
        self.store, self.cipher, self.runtime = store, cipher, runtime
        self.media_resolver = media_resolver
        self.operation_timeout = operation_timeout
        self.worker_id = str(uuid.uuid4())
        self.stopping = threading.Event()

    def submit_join(self, owner, key, payload):
        payload = join_payload(payload)
        aad = context(owner, "join")
        return self.store.accept_join(owner, key, self.cipher.fingerprint(payload, aad), self.cipher.seal(payload, aad))

    def submit_control(self, owner, bot_id, command, key, payload):
        payload = control_payload(command, payload)
        aad = context(owner, command, bot_id)
        return self.store.accept_control(owner, bot_id, command, key, self.cipher.fingerprint(payload, aad), self.cipher.seal(payload, aad))

    def wait_status(self, job, predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stopping.is_set():
            try:
                state = self.runtime.status(job["bot_id"])
            except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
                self.stopping.wait(0.1)
                continue
            if state.get("playback_state") == "failed":
                raise RuntimeErrorCode("MEDIA_SEND_FAILED")
            if predicate(state):
                return state
            self.stopping.wait(0.1)
        raise RuntimeErrorCode("AGENT_STOPPING" if self.stopping.is_set() else "OPERATION_TIMEOUT")

    def run_once(self):
        job = self.store.claim(self.worker_id)
        if not job:
            return False
        try:
            aad = context(job["owner"], job["command"], None if job["command"] == "join" else job["bot_id"])
            payload = self.cipher.open(job["payload"], aad)
            if job["command"] == "join":
                self.runtime.start(job["bot_id"], payload["meeting"])
                timeout = min(payload.get("options", {}).get("waiting_room_timeout_seconds", 900),
                              payload.get("options", {}).get("max_session_seconds", 5400))
                self.wait_status(job, lambda state: state.get("in_meeting") is True, timeout)
                self.store.finish(job["id"], self.worker_id, succeeded=True, session_state="active")
            elif job["command"] == "leave":
                cleaned = self.runtime.stop(job["bot_id"])
                self.store.finish(job["id"], self.worker_id, succeeded=True, session_state="ended", cleanup_confirmed=cleaned)
            elif job["command"] == "play":
                if not self.media_resolver:
                    raise RuntimeErrorCode("MEDIA_RESOLVER_NOT_CONFIGURED")
                media = payload["media"]
                path = self.media_resolver(media)
                playback_id = str(uuid.uuid4())
                kind = media["type"]
                sdk_type = "video-silent" if kind == "video" and media.get("audio_enabled", True) is False else kind
                fields = {"playback_id": playback_id, "media_type": sdk_type, "path": str(path)}
                if kind == "image":
                    fields["duration_seconds"] = media.get("duration_seconds")
                try:
                    self.runtime.command(job["bot_id"], "play", job["id"], **fields)
                except (TimeoutError, ControlError) as error:
                    # A timeout may have applied play. Reconcile the same attempt, never start another.
                    if not isinstance(error, TimeoutError):
                        raise
                needs_video = kind != "audio"
                needs_audio = kind == "audio" or (kind == "video" and media.get("audio_enabled", True))
                def started(state):
                    return state.get("playback_id") == playback_id and (not needs_video or state.get("video_frames_sent", 0) > 0) and (not needs_audio or state.get("audio_blocks_sent", 0) > 0)
                self.wait_status(job, started, self.operation_timeout)
                self.store.finish(job["id"], self.worker_id, succeeded=True)
            else:
                fields = {}
                if payload.get("playback_id"):
                    fields["playback_id"] = payload["playback_id"]
                else:
                    fields["playback_id"] = self.runtime.status(job["bot_id"]).get("playback_id")
                self.runtime.command(job["bot_id"], job["command"], job["id"], **fields)
                self.store.finish(job["id"], self.worker_id, succeeded=True)
        except Exception as error:
            known = isinstance(error, (PayloadError, RuntimeErrorCode, ControlError, StoreError))
            code = str(error) if known else "WORKER_OPERATION_FAILED"
            # Never persist exception text with paths, URLs or secrets.
            if not code or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for character in code) or len(code) > 80:
                code = "WORKER_OPERATION_FAILED"
            cleanup = False
            terminal = job["command"] in {"join", "leave"}
            if terminal:
                try:
                    cleanup = self.runtime.cleanup(job["bot_id"]) is True
                except Exception:
                    cleanup = False
            self.store.finish(job["id"], self.worker_id, succeeded=False, error=code,
                              session_state="failed" if terminal else None, cleanup_confirmed=cleanup)
        return True

    def run(self):
        while not self.stopping.is_set():
            if not self.run_once():
                self.stopping.wait(0.2)
