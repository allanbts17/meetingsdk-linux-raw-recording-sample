"""Linux SDK process lifecycle, with one private directory per bot."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from .sdk_control import SdkControl, ControlError


class RuntimeErrorCode(RuntimeError):
    pass


def configuration(meeting, credentials):
    try:
        if any(not isinstance(credentials.get(key), str) or not credentials[key].strip() for key in ["clientId", "clientSecret"]):
            raise ValueError()
        issued = int(time.time()) - 30
        def encoded(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
        unsigned = encoded({"alg": "HS256", "typ": "JWT"}) + b"." + encoded({
            "appKey": credentials["clientId"], "iat": issued, "exp": issued + 7200, "tokenExp": issued + 7200})
        signature = base64.urlsafe_b64encode(hmac.new(credentials["clientSecret"].encode(), unsigned, hashlib.sha256).digest()).rstrip(b"=")
        fields = {
            "meeting_number": meeting["number"], "meeting_password": meeting.get("password", ""),
            "participant_name": meeting.get("participant_name", "VideoBot"), "token": (unsigned + b"." + signature).decode(),
            "recording_token": "", "onBehalfOf_Token": "", "GetVideoRawData": "false", "GetAudioRawData": "false",
            "SendVideoRawData": "false", "SendAudioRawData": "false", "video_source": "/app/media/video.mp4",
        }
        if any(not isinstance(value, str) or any(c in value for c in '\r\n"\0') for value in fields.values()):
            raise ValueError()
        return "".join(f'{key}: "{value}"\n' for key, value in fields.items())
    except (KeyError, TypeError, AttributeError, ValueError):
        raise RuntimeErrorCode("INVALID_SDK_CONFIGURATION") from None


class SdkRuntime:
    def __init__(self, root, credentials_provider, executable="/app/demo/bin/meetingSDKDemo"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.credentials_provider = credentials_provider
        self.executable = Path(executable).resolve()
        self.process = None
        self.bot_id = None
        self.directory = None
        self.control = None

    def start(self, bot_id, meeting):
        import uuid
        try:
            uuid.UUID(bot_id)
        except (ValueError, TypeError):
            raise RuntimeErrorCode("INVALID_BOT_ID") from None
        if self.process is not None:
            raise RuntimeErrorCode("RUNTIME_ALREADY_OWNED")
        directory = self.root / bot_id
        socket_path = directory / "sdk.sock"
        if len(os.fsencode(socket_path)) >= 104:
            raise RuntimeErrorCode("CONTROL_PATH_TOO_LONG")
        directory.mkdir(mode=0o700, exist_ok=False)
        try:
            config = configuration(meeting, self.credentials_provider())
            descriptor = os.open(directory / "config.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                file.write(config)
            environment = dict(os.environ, ZOOM_CONFIG_PATH=str(directory / "config.txt"), ZOOM_CONTROL_SOCKET=str(socket_path))
            # SDK diagnostics stay private; public errors use fixed codes.
            descriptor = os.open(directory / "sdk.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.directory, self.bot_id = directory, bot_id
            self.control = SdkControl(str(socket_path), timeout=5)
            with os.fdopen(descriptor, "wb") as log:
                self.process = subprocess.Popen([str(self.executable)], cwd=self.executable.parent, env=environment,
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        except BaseException:
            if self.process is None:
                shutil.rmtree(directory)
                self.directory = self.control = self.bot_id = None
            raise

    def status(self, bot_id):
        self.check_owner(bot_id)
        if self.process.poll() is not None:
            raise RuntimeErrorCode("SDK_PROCESS_EXITED")
        return self.control.command("status")

    def command(self, bot_id, command, operation_id, **fields):
        self.check_owner(bot_id)
        return self.control.command(command, operation_id=operation_id, **fields)

    def check_owner(self, bot_id):
        if not self.process or self.bot_id != bot_id:
            raise RuntimeErrorCode("RUNTIME_NOT_FOUND")

    def group_alive(self):
        if not self.process:
            return False
        self.process.poll()  # Reap the leader before testing its process group.
        try:
            os.killpg(self.process.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def stop(self, bot_id):
        self.check_owner(bot_id)
        if self.process.poll() is None:
            try:
                self.control.command("quit")
            except (OSError, ControlError):
                pass
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
        for sig in [signal.SIGTERM, signal.SIGKILL]:
            if not self.group_alive():
                break
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                break
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                continue
        if self.group_alive():
            raise RuntimeErrorCode("SDK_CLEANUP_UNCONFIRMED")
        # Only the directory created by start; never remove the configured root.
        if self.directory and self.directory.parent == self.root:
            shutil.rmtree(self.directory)
        self.process = self.control = self.directory = self.bot_id = None
        return True

    def cleanup(self, bot_id):
        if self.bot_id is None:
            return True
        return self.stop(bot_id)
