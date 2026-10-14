"""Dependency-free GCE metadata/Secret Manager diagnostic. Prints no payload."""
import base64
import json
import urllib.request


def checksum(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def main():
    try:
        request = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.load(response)["access_token"]
        for secret in ("zoom-bot-sdk", "zoom-bot-master-key"):
            request = urllib.request.Request(
                f"https://secretmanager.googleapis.com/v1/projects/zoom-app-dev/secrets/{secret}/versions/1:access",
                headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)["payload"]
            data = base64.b64decode(payload["data"], validate=True)
            if checksum(data) != int(payload["dataCrc32c"]):
                raise ValueError()
            if secret == "zoom-bot-sdk":
                value = json.loads(data)
                if set(value) != {"clientId", "clientSecret"} or not all(isinstance(v, str) and v.strip() for v in value.values()):
                    raise ValueError()
            elif len(base64.b64decode(data, validate=True)) != 32:
                raise ValueError()
        print('VM_SECRET_ACCESS_AND_CHECKSUM_OK')
        return 0
    except Exception:
        print('VM_SECRET_ACCESS_FAILED')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
