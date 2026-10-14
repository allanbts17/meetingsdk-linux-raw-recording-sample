"""Explicit Storage download diagnostic; reports metadata/codes, never the URL."""
import argparse
import json
from pathlib import Path
import tempfile
import subprocess
from app.media import MediaCache, MediaError, probe_media


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-request", required=True)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    payload = json.loads(Path(args.media_request).read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory(prefix="zb-cache-") as directory:
        def diagnostic(path, media):
            if args.diagnose:
                result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate", "-of", "json", str(path)],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
                try:
                    data = json.loads(result.stdout)
                    print(json.dumps({"event": "media.probe_metadata", "probe_exit": result.returncode,
                                      "format": data.get("format"), "streams": data.get("streams")}), flush=True)
                except ValueError:
                    print(json.dumps({"event": "media.probe_metadata", "probe_exit": result.returncode}), flush=True)
            return probe_media(path, media)
        cache = MediaCache(directory, probe=diagnostic)
        lease = cache.resolve(payload["media"])
        print(json.dumps(lease.metadata), flush=True)
        lease.release()
        cache.cleanup()


if __name__ == "__main__":
    try:
        main()
    except MediaError as error:
        print(json.dumps({"error": str(error)}), flush=True)
        raise SystemExit(1)
    except Exception:
        print(json.dumps({"error": "MEDIA_PROBE_FAILED"}), flush=True)
        raise SystemExit(1)
