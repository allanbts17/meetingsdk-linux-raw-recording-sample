import os
import unittest
from app.payloads import PayloadCipher, PayloadError, context


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.cipher = PayloadCipher(os.urandom(32))
        self.payload = {"meeting": {"password": "test-password"}, "url": "https://example.test/file?secret=test-token"}
        self.aad = context("client", "play", "bot-1")

    def test_roundtrip_random_nonce_and_no_plaintext(self):
        first = self.cipher.seal(self.payload, self.aad)
        self.assertNotEqual(first, self.cipher.seal(self.payload, self.aad))
        self.assertNotIn(b"test-password", first)
        self.assertNotIn(b"test-token", first)
        self.assertEqual(self.cipher.open(first, self.aad), self.payload)

    def test_tamper_wrong_owner_bot_command_and_key_rejected(self):
        encrypted = self.cipher.seal(self.payload, self.aad)
        for aad in [context("other", "play", "bot-1"), context("client", "play", "bot-2"), context("client", "stop", "bot-1")]:
            with self.assertRaisesRegex(PayloadError, "AUTH_FAILED"):
                self.cipher.open(encrypted, aad)
        with self.assertRaises(PayloadError):
            self.cipher.open(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), self.aad)
        with self.assertRaises(PayloadError):
            PayloadCipher(os.urandom(32)).open(encrypted, self.aad)

    def test_keyed_fingerprint_stable_and_scoped(self):
        first = self.cipher.fingerprint(self.payload, self.aad)
        self.assertEqual(first, self.cipher.fingerprint(self.payload, self.aad))
        self.assertNotEqual(first, self.cipher.fingerprint(self.payload, context("other", "play", "bot-1")))

    def test_limits_and_invalid_key(self):
        with self.assertRaises(PayloadError):
            PayloadCipher(b"short")
        with self.assertRaisesRegex(PayloadError, "TOO_LARGE"):
            self.cipher.seal({"data": "x" * 65536}, self.aad)
        with self.assertRaises(PayloadError):
            self.cipher.open(b"plain-password", self.aad)
