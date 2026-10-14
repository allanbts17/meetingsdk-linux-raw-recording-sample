"""Secret Manager access through ADC; never include payloads in errors or logs."""
import base64
import json
import re
import google_crc32c


class SecretError(RuntimeError):
    pass


def validate_version(name):
    if not isinstance(name, str) or not re.fullmatch(
        r"projects/[a-zA-Z0-9_-]+/secrets/[a-zA-Z0-9_-]+/versions/[1-9][0-9]*", name
    ):
        raise SecretError("INVALID_SECRET_VERSION")


class SecretReader:
    def __init__(self, client=None):
        if client is None:
            from google.cloud import secretmanager
            try:
                client = secretmanager.SecretManagerServiceClient()
            except Exception:
                raise SecretError("SECRET_AUTHENTICATION_FAILED") from None
        self.client = client

    def read(self, name):
        validate_version(name)
        try:
            response = self.client.access_secret_version(request={"name": name}, timeout=10, retry=None)
            payload = response.payload
            data = bytes(payload.data)
            if not data or len(data) > 65536:
                raise SecretError("INVALID_SECRET_PAYLOAD")
            if google_crc32c.value(data) != payload.data_crc32c:
                raise SecretError("SECRET_CHECKSUM_MISMATCH")
            return data
        except SecretError:
            raise
        except Exception:
            raise SecretError("SECRET_ACCESS_FAILED") from None

    def token(self, name):
        try:
            value = self.read(name)
            if len(base64.b64decode(value, validate=True)) != 32:
                raise ValueError()
            return value.decode("ascii")
        except SecretError:
            raise
        except (ValueError, UnicodeError):
            raise SecretError("INVALID_AGENT_TOKEN") from None


class SecretProvider(SecretReader):
    def __init__(self, credentials_version, master_key_version, client=None):
        # Pin versions: silently rotating the encryption key loses durable payloads.
        validate_version(credentials_version)
        validate_version(master_key_version)
        super().__init__(client)
        self.credentials_version = credentials_version
        self.master_key_version = master_key_version

    def credentials(self):
        try:
            value = json.loads(self.read(self.credentials_version))
            if not isinstance(value, dict) or set(value) != {"clientId", "clientSecret"}:
                raise ValueError()
            if any(not isinstance(item, str) or not item.strip() or len(item) > 4096
                   or any(c in item for c in '\r\n\0"') for item in value.values()):
                raise ValueError()
            return value
        except SecretError:
            raise
        except (ValueError, TypeError, UnicodeError):
            raise SecretError("INVALID_SDK_SECRET") from None

    def master_key(self):
        try:
            key = base64.b64decode(self.read(self.master_key_version), validate=True)
            if len(key) != 32:
                raise ValueError()
            return key
        except SecretError:
            raise
        except (ValueError, TypeError):
            raise SecretError("INVALID_MASTER_KEY_SECRET") from None
