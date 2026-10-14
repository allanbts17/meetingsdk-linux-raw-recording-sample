"""Pull a pinned managed image with a short-lived metadata token and private temp config."""
import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    if not re.fullmatch(r"us-central1-docker\.pkg\.dev/zoom-app-dev/zoom-bot/[a-z-]+@sha256:[0-9a-f]{64}", args.image):
        print("INVALID_PINNED_IMAGE")
        return 1
    try:
        if subprocess.run(["docker", "image", "inspect", args.image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return 0
        request = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                                         headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.load(response)["access_token"]
        with tempfile.TemporaryDirectory(prefix="zoom-bot-docker-") as directory:
            os.chmod(directory, 0o700)
            subprocess.run(["docker", "--config", directory, "login", "-u", "oauth2accesstoken", "--password-stdin",
                            "us-central1-docker.pkg.dev"], input=token.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=True)
            subprocess.run(["docker", "--config", directory, "pull", args.image], check=True)
        return 0
    except Exception:
        print("MANAGED_IMAGE_PULL_FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
