"""Authenticated envelopes and keyed request fingerprints; never log plaintext."""
import hashlib
import hmac
import json
import os
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class PayloadError(RuntimeError):
    pass


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise PayloadError("INVALID_PAYLOAD") from None


def context(owner, command, bot_id=None):
    return canonical({"version": 1, "owner": owner, "command": command, "bot_id": bot_id})


class PayloadCipher:
    MAGIC = b"ZB01"
    LIMIT = 65536

    def __init__(self, master_key):
        if not isinstance(master_key, bytes) or len(master_key) != 32:
            raise PayloadError("INVALID_PAYLOAD_KEY")
        material = HKDF(algorithm=hashes.SHA256(), length=64, salt=None, info=b"zoom-bot-agent-v1").derive(master_key)
        self.aes = AESGCM(material[:32])
        self.fingerprint_key = material[32:]

    def fingerprint(self, payload, associated_data):
        return hmac.new(self.fingerprint_key, associated_data + b"\0" + canonical(payload), hashlib.sha256).hexdigest()

    def seal(self, payload, associated_data):
        encoded = canonical(payload)
        if len(encoded) > self.LIMIT:
            raise PayloadError("PAYLOAD_TOO_LARGE")
        nonce = os.urandom(12)
        return self.MAGIC + nonce + self.aes.encrypt(nonce, encoded, associated_data)

    def open(self, envelope, associated_data):
        if not isinstance(envelope, bytes) or not 32 <= len(envelope) <= self.LIMIT + 32 or not envelope.startswith(self.MAGIC):
            raise PayloadError("INVALID_PAYLOAD_ENVELOPE")
        try:
            decoded = self.aes.decrypt(envelope[4:16], envelope[16:], associated_data)
            value = json.loads(decoded)
        except (InvalidTag, ValueError, UnicodeError):
            raise PayloadError("PAYLOAD_AUTH_FAILED") from None
        if not isinstance(value, dict):
            raise PayloadError("INVALID_PAYLOAD")
        return value
