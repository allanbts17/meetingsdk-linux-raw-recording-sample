import base64
import json
from types import SimpleNamespace
import unittest
import google_crc32c
from app.secrets import SecretProvider, SecretReader, SecretError


SDK = "projects/test-project/secrets/zoom-sdk/versions/1"
KEY = "projects/test-project/secrets/zoom-key/versions/2"


class FakeClient:
    def __init__(self, data):
        self.data, self.calls, self.corrupt = data, [], False

    def access_secret_version(self, *, request, timeout, retry):
        self.calls.append((request, timeout, retry))
        data = self.data[request["name"]]
        return SimpleNamespace(payload=SimpleNamespace(data=data,
            data_crc32c=google_crc32c.value(data) ^ int(self.corrupt)))


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient({SDK: json.dumps({"clientId": "test-id", "clientSecret": "test-secret"}).encode(),
                                  KEY: base64.b64encode(bytes(range(32)))})
        self.provider = SecretProvider(SDK, KEY, self.client)

    def test_credentials_and_stable_key_across_restart(self):
        self.assertEqual(self.provider.credentials()["clientId"], "test-id")
        key = self.provider.master_key()
        self.assertEqual(key, SecretProvider(SDK, KEY, self.client).master_key())
        self.assertEqual(len(key), 32)
        self.assertTrue(all(call[1:] == (10, None) for call in self.client.calls))

    def test_reject_corruption(self):
        self.client.corrupt = True
        with self.assertRaisesRegex(SecretError, "SECRET_CHECKSUM_MISMATCH"):
            self.provider.credentials()

    def test_reject_alias_or_invalid_version(self):
        for version in (SDK.replace("/1", "/latest"), SDK.replace("/1", "/0"), "https://example.test"):
            with self.assertRaisesRegex(SecretError, "INVALID_SECRET_VERSION"):
                SecretProvider(version, KEY, self.client)

    def test_errors_never_expose_payload_or_service_exception(self):
        self.client.data[SDK] = b'{"password":"private-data"}'
        with self.assertRaisesRegex(SecretError, "^INVALID_SDK_SECRET$"):
            self.provider.credentials()
        self.client.data.clear()
        with self.assertRaisesRegex(SecretError, "^SECRET_ACCESS_FAILED$"):
            self.provider.credentials()

    def test_invalid_key_and_sdk_fields(self):
        for data in (b"not-base64!", base64.b64encode(b"short")):
            self.client.data[KEY] = data
            with self.assertRaisesRegex(SecretError, "INVALID_MASTER_KEY_SECRET"):
                self.provider.master_key()
        self.client.data[SDK] = b'{"clientId":"ok","clientSecret":""}'
        with self.assertRaisesRegex(SecretError, "INVALID_SDK_SECRET"):
            self.provider.credentials()

    def test_private_token_reader_does_not_request_sdk_or_key(self):
        token_version = "projects/test-project/secrets/agent-token/versions/1"
        value = base64.b64encode(bytes(range(32)))
        client = FakeClient({token_version: value})
        reader = SecretReader(client)
        self.assertEqual(reader.token(token_version), value.decode())
        self.assertEqual([call[0]["name"] for call in client.calls], [token_version])
