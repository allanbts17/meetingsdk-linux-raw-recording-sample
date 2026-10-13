"""Private GCE agent → SDK IPC; this is not an HTTP API client."""
import json
import socket
import uuid


class ControlError(RuntimeError):
    pass


class SdkControl:
    def __init__(self, path="/tmp/zoom-sdk-control.sock", timeout=20):
        self.path = path
        self.timeout = timeout

    def command(self, command, *, operation_id=None, **fields):
        operation_id = operation_id or str(uuid.uuid4())
        request = dict(fields, version=1, operation_id=operation_id, command=command)
        encoded = json.dumps(request, ensure_ascii=True).encode() + b"\n"
        if len(encoded) > 8192:
            raise ControlError("IPC_REQUEST_TOO_LARGE")
        # Timeout is an unknown outcome. The agent must reconcile status before retrying play.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            connection.sendall(encoded)
            output = bytearray()
            while b"\n" not in output:
                chunk = connection.recv(1024)
                if not chunk:
                    raise ControlError("IPC_INCOMPLETE_RESPONSE")
                output.extend(chunk)
                if len(output) > 8192:
                    raise ControlError("IPC_RESPONSE_TOO_LARGE")
        try:
            response = json.loads(output.split(b"\n", 1)[0])
        except (ValueError, UnicodeError) as error:
            raise ControlError("IPC_INVALID_RESPONSE") from error
        if not isinstance(response, dict) or response.get("version") != 1 or response.get("operation_id") != operation_id:
            raise ControlError("IPC_RESPONSE_MISMATCH")
        if response.get("ok") is not True:
            raise ControlError(response.get("error", "IPC_COMMAND_FAILED"))
        return response
