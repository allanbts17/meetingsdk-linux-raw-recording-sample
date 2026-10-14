"""Durable submission and synchronous worker steps, independent of HTTP lifetime."""
import threading
import time
import uuid
from .payloads import context, PayloadError
from .runtime import RuntimeErrorCode
from .sdk_control import ControlError
from .store import StoreError
from .validation import join_payload, control_payload
from .media import MediaError
from .secrets import SecretError


class OperationCancellation:
    def __init__(self, agent, deadline=None, operation_id=None):
        self.agent, self.deadline, self.operation_id = agent, deadline, operation_id

    def reason(self):
        if self.agent.stopping.is_set():
            return "AGENT_STOPPING"
        if self.operation_id is not None:
            requested = self.agent.store.cancellation_reason(self.operation_id)
            if requested:
                return requested
        if self.deadline is not None and time.time() >= self.deadline:
            return "SESSION_TIMEOUT"
        process = getattr(self.agent.runtime, "process", None)
        if process is not None and process.poll() is not None:
            return "SDK_PROCESS_EXITED"
        return None

    def is_set(self):
        return self.reason() is not None

    def wait(self, seconds):
        self.agent.stopping.wait(seconds)
        return self.is_set()


class Agent:
    def __init__(self, store, cipher, runtime, media_resolver=None, operation_timeout=30):
        self.store, self.cipher, self.runtime = store, cipher, runtime
        self.media_resolver = media_resolver
        self.operation_timeout = operation_timeout
        self.worker_id = str(uuid.uuid4())
        self.stopping = threading.Event()
        self.media_resources = {}
        self.cancellation = OperationCancellation(self)
        self.unresponsive_since = {}
        self.reconnecting_since = {}

    def release_media(self, bot_id):
        resource = self.media_resources.pop(bot_id, None)
        if resource and hasattr(resource, "release"):
            resource.release()

    def submit_join(self, owner, key, payload):
        payload = join_payload(payload)
        aad = context(owner, "join")
        return self.store.accept_join(owner, key, self.cipher.fingerprint(payload, aad), self.cipher.seal(payload, aad), meeting=payload["meeting"])

    def submit_control(self, owner, bot_id, command, key, payload):
        payload = control_payload(command, payload)
        aad = context(owner, command, bot_id)
        return self.store.accept_control(owner, bot_id, command, key, self.cipher.fingerprint(payload, aad), self.cipher.seal(payload, aad),
                                         playback_id=payload.get("playback_id"), media=payload.get("media"))

    def applied(self, job, state, **extra):
        self.store.snapshot(job["bot_id"], state)
        result = {"playback_id": state.get("playback_id"), "playback_status": state.get("playback_state"),
                  "position_seconds": state.get("position_seconds")}
        result.update(extra)
        self.store.finish(job["id"], self.worker_id, succeeded=True, result=result)

    def wait_status(self, job, predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.cancellation.is_set():
            try:
                state = self.runtime.status(job["bot_id"])
            except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
                self.stopping.wait(0.1)
                continue
            if state.get("playback_state") == "failed":
                raise RuntimeErrorCode("MEDIA_SEND_FAILED")
            self.store.snapshot(job["bot_id"], state)
            if predicate(state):
                return state
            self.stopping.wait(0.1)
        raise RuntimeErrorCode(self.cancellation.reason() or "OPERATION_TIMEOUT")

    def run_once(self):
        job = self.store.claim(self.worker_id)
        if not job:
            return False
        play_resource_acquired = False
        try:
            aad = context(job["owner"], job["command"], None if job["command"] == "join" else job["bot_id"])
            payload = self.cipher.open(job["payload"], aad)
            if job["command"] == "join":
                maximum = payload.get("options", {}).get("max_session_seconds", 5400)
                session_deadline = self.store.set_deadline(job["bot_id"], maximum)
            else:
                session_deadline = next((row["deadline"] for row in self.store.reserved_sessions()
                                         if row["id"] == job["bot_id"]), None)
            self.cancellation = OperationCancellation(self, session_deadline, job["id"])
            if job["command"] != "leave" and self.cancellation.is_set():
                raise RuntimeErrorCode(self.cancellation.reason())
            if job["command"] == "join":
                self.runtime.start(job["bot_id"], payload["meeting"])
                timeout = min(payload.get("options", {}).get("waiting_room_timeout_seconds", 900),
                              max(0, session_deadline - time.time()))
                state = self.wait_status(job, lambda state: state.get("in_meeting") is True, timeout)
                self.store.snapshot(job["bot_id"], state)
                self.store.finish(job["id"], self.worker_id, succeeded=True, session_state="active")
            elif job["command"] == "leave":
                cleaned = self.runtime.cleanup(job["bot_id"])
                if cleaned:
                    self.release_media(job["bot_id"])
                self.store.finish(job["id"], self.worker_id, succeeded=True, session_state="ended", cleanup_confirmed=cleaned)
            elif job["command"] == "play":
                if not self.media_resolver:
                    raise RuntimeErrorCode("MEDIA_RESOLVER_NOT_CONFIGURED")
                media = payload["media"]
                current = self.runtime.status(job["bot_id"])
                if current.get("playback_state") not in {"idle", "finished", "stopped", "failed"}:
                    raise RuntimeErrorCode("PLAYBACK_ALREADY_ACTIVE")
                if current.get("playback_state") == "failed":
                    self.runtime.command(job["bot_id"], "stop", job["id"], playback_id=current.get("playback_id"))
                self.release_media(job["bot_id"])
                resource = self.media_resolver.resolve(media, cancel=self.cancellation) if hasattr(self.media_resolver, "resolve") else self.media_resolver(media)
                self.media_resources[job["bot_id"]] = resource
                play_resource_acquired = True
                if hasattr(resource, "metadata"):
                    self.store.media_metadata(job["id"], resource.metadata)
                if self.cancellation.is_set():
                    raise RuntimeErrorCode(self.cancellation.reason())
                path = resource.path if hasattr(resource, "path") else resource
                playback_id = job["playback_id"]
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
                state = self.wait_status(job, started, self.operation_timeout)
                self.applied(job, state)
            else:
                state = self.runtime.status(job["bot_id"])
                captured = job["playback_id"]
                if job["command"] == "stop" and state.get("playback_state") in {"idle", "stopped", "finished"}:
                    if state.get("playback_state") != "finished":
                        self.release_media(job["bot_id"])
                    if captured != state.get("playback_id") and self.store.playback_not_started(captured):
                        state.update(playback_id=captured, playback_state="stopped", position_seconds=0)
                    self.applied(job, state, no_op=True)
                    return True
                if captured != state.get("playback_id") or captured is None:
                    raise RuntimeErrorCode("PLAYBACK_ID_MISMATCH")
                expected = {"pause": "paused", "resume": "playing", "stop": "stopped"}[job["command"]]
                if state.get("playback_state") == expected:
                    self.applied(job, state, no_op=True)
                    return True
                fields = {"playback_id": captured}
                try:
                    self.runtime.command(job["bot_id"], job["command"], job["id"], **fields)
                except TimeoutError:
                    pass  # Reconcile the same attempt; never repeat the command blindly.
                state = self.wait_status(job, lambda state: state.get("playback_id") == captured
                                         and state.get("playback_state") == expected, self.operation_timeout)
                if job["command"] == "stop":
                    self.release_media(job["bot_id"])
                    self.store.snapshot(job["bot_id"], state)
                self.applied(job, state)
        except Exception as error:
            known = isinstance(error, (PayloadError, RuntimeErrorCode, ControlError, StoreError, MediaError, SecretError))
            code = str(error) if known else "WORKER_OPERATION_FAILED"
            requested = self.store.cancellation_reason(job["id"])
            if requested:
                code = requested
            if (isinstance(error, TimeoutError) or code == "OPERATION_TIMEOUT" or
                (isinstance(error, ControlError) and code.startswith("IPC_"))) and job["command"] not in {"join", "leave"}:
                self.store.mark_reconciling(job["bot_id"])
            # Never persist exception text with paths, URLs or secrets.
            if not code or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for character in code) or len(code) > 80:
                code = "WORKER_OPERATION_FAILED"
            cleanup = False
            terminal = job["command"] in {"join", "leave"}
            if terminal:
                try:
                    cleanup = self.runtime.cleanup(job["bot_id"]) is True
                    if cleanup:
                        self.release_media(job["bot_id"])
                except Exception:
                    cleanup = False
            elif job["command"] == "play" and play_resource_acquired:
                # An uncertain IPC result may already be decoding this file; stop before unpinning.
                try:
                    state = self.runtime.status(job["bot_id"])
                    if state.get("playback_state") not in {"idle", "stopped", "finished"}:
                        self.runtime.command(job["bot_id"], "stop", job["id"], playback_id=state.get("playback_id"))
                    self.release_media(job["bot_id"])
                except Exception:
                    pass  # Preserve the pin until confirmed stop/leave; never guess decoder lifetime.
            self.store.finish(job["id"], self.worker_id, succeeded=False, error=code,
                              session_state=("leaving" if requested else "failed") if terminal else None,
                              cleanup_confirmed=cleanup and not requested, cancelled=bool(requested))
        return True

    def end_supervised(self, session, code):
        cleaned = False
        try:
            # A lost in-memory owner is not proof that old decoders disappeared.
            if getattr(self.runtime, "bot_id", None) != session["id"]:
                raise RuntimeErrorCode("RUNTIME_NOT_FOUND")
            cleaned = self.runtime.cleanup(session["id"]) is True
            if cleaned:
                self.release_media(session["id"])
        except Exception:
            pass
        self.store.end_session(session["id"], code, cleanup_confirmed=cleaned)

    def supervise(self):
        """Run between jobs on the SDK-owning thread; heartbeat has its own thread."""
        for session in self.store.reserved_sessions():
            if session["state"] in {"accepted", "leaving"}:
                continue
            bot = session["id"]
            if session["deadline"] is not None and time.time() >= session["deadline"]:
                self.end_supervised(session, "SESSION_TIMEOUT")
                continue
            if session["state"] == "failed":
                self.end_supervised(session, "SDK_CLEANUP_UNCONFIRMED")
                continue
            try:
                state = self.runtime.status(bot)
                self.store.snapshot(bot, state)
                self.unresponsive_since.pop(bot, None)
                status = state.get("meeting_status")
                if status in {0, 6, 7}:
                    self.end_supervised(session, "MEETING_ENDED")
                elif status == 5:
                    since = self.reconnecting_since.setdefault(bot, time.monotonic())
                    if time.monotonic() - since >= 120:
                        self.end_supervised(session, "RECONNECT_TIMEOUT")
                else:
                    self.reconnecting_since.pop(bot, None)
            except RuntimeErrorCode as error:
                if str(error) == "SDK_PROCESS_EXITED":
                    self.end_supervised(session, "SDK_PROCESS_EXITED")
                else:
                    self.end_supervised(session, "SDK_STATE_UNAVAILABLE")
            except (OSError, ControlError):
                since = self.unresponsive_since.setdefault(bot, time.monotonic())
                if time.monotonic() - since >= 15:
                    self.end_supervised(session, "SDK_UNRESPONSIVE")

    def run(self):
        next_supervision = 0
        while not self.stopping.is_set():
            if time.monotonic() >= next_supervision:
                self.supervise()
                next_supervision = time.monotonic() + 1
            if not self.run_once():
                self.stopping.wait(0.2)
