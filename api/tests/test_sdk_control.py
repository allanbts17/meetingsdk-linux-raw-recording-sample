import json
import socket
import unittest
from unittest.mock import MagicMock, patch
from app.sdk_control import ControlError, SdkControl


class SdkControlTests(unittest.TestCase):
    def exchange(self, chunks, **fields):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.side_effect = chunks
        with patch("app.sdk_control.socket.AF_UNIX", 1, create=True), patch("app.sdk_control.socket.socket", return_value=connection):
            result = SdkControl().command("status", operation_id="op-1", **fields)
        sent = json.loads(connection.sendall.call_args.args[0])
        self.assertEqual(sent["operation_id"], "op-1")
        self.assertEqual(sent["version"], 1)
        return result

    def test_fragmented_response(self):
        result = self.exchange([b'{"version":1,"operation_id":', b'"op-1","ok":true}\n'])
        self.assertTrue(result["ok"])

    def test_wrong_operation_is_not_ack(self):
        with self.assertRaisesRegex(ControlError, "MISMATCH"):
            self.exchange([b'{"version":1,"operation_id":"other","ok":true}\n'])

    def test_rejected_command(self):
        with self.assertRaisesRegex(ControlError, "PLAYBACK_ID_MISMATCH"):
            self.exchange([b'{"version":1,"operation_id":"op-1","ok":false,"error":"PLAYBACK_ID_MISMATCH"}\n'])

    def test_eof_and_oversized_response(self):
        with self.assertRaisesRegex(ControlError, "INCOMPLETE"):
            self.exchange([b'{"ok":', b''])
        with self.assertRaisesRegex(ControlError, "TOO_LARGE"):
            self.exchange([b'x' * 8193])

    def test_timeout_does_not_retry(self):
        with self.assertRaises(socket.timeout):
            self.exchange([socket.timeout("unknown outcome")])

    def test_large_request_rejected_before_socket(self):
        with patch("app.sdk_control.socket.socket") as connect:
            with self.assertRaisesRegex(ControlError, "REQUEST_TOO_LARGE"):
                SdkControl().command("play", path="x" * 8192)
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
