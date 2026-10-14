import base64
import json
import unittest
from app.runtime import configuration, RuntimeErrorCode


class ConfigurationTests(unittest.TestCase):
    def test_jwt_and_join_without_media(self):
        text = configuration({"number": "123456789", "password": "test-password"}, {"clientId": "test-id", "clientSecret": "test-secret"})
        fields = dict(line.split(": ", 1) for line in text.splitlines())
        self.assertEqual(fields["SendVideoRawData"], '"false"')
        self.assertEqual(fields["SendAudioRawData"], '"false"')
        token = fields["token"].strip('"')
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        self.assertEqual(claims["appKey"], "test-id")
        self.assertEqual(claims["exp"] - claims["iat"], 7200)
        self.assertNotIn("test-secret", text)

    def test_configuration_injection_rejected(self):
        with self.assertRaisesRegex(RuntimeErrorCode, "INVALID_SDK_CONFIGURATION"):
            configuration({"number": "123456789", "password": 'password"\nSendVideoRawData: true'}, {"clientId": "test-id", "clientSecret": "test-secret"})
