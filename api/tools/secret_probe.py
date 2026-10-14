"""Validate deployed secret access without printing credentials or joining Zoom."""
import argparse
import json
from app.secrets import SecretProvider, SecretError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-version", required=True)
    parser.add_argument("--master-key-version", required=True)
    args = parser.parse_args()
    try:
        provider = SecretProvider(args.credentials_version, args.master_key_version)
        provider.credentials()
        provider.master_key()
    except SecretError as error:
        print(json.dumps({"event": "secrets.failed", "error": str(error)}))
        return 1
    print(json.dumps({"event": "secrets.validated"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
