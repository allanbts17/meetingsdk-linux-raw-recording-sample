"""Bounded Storage downloads and leases for the agent-owned local cache."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import unquote, urljoin, urlsplit
import uuid
import google_crc32c


class MediaError(RuntimeError):
    pass


def storage_url(url, bucket):
    try:
        if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "storage.googleapis.com" or parsed.port not in (None, 443):
            raise ValueError()
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        decoded = unquote(parsed.path)
        for _ in range(3):
            if "\\" in decoded or any(part in (".", "..") for part in decoded.split("/")):
                raise ValueError()
            parts = decoded.split("/", 2)
            if len(parts) != 3 or parts[1] != bucket or not parts[2]:
                raise ValueError()
            decoded = unquote(decoded)
        (parsed.path + parsed.query).encode("ascii")
        return parsed
    except (ValueError, UnicodeError, AttributeError):
        raise MediaError("MEDIA_URL_NOT_ALLOWED") from None


class Response:
    def __init__(self, connection, response):
        self.connection, self.response = connection, response
        self.status = response.status
        self.headers = {key.lower(): value for key, value in response.getheaders()}
        self.headers["x-goog-hash"] = response.getheader("x-goog-hash", "")

    def read(self, size, timeout):
        if self.connection.sock:
            self.connection.sock.settimeout(timeout)
        return self.response.read1(size)

    def close(self):
        self.response.close()
        self.connection.close()


def fetch(url, etag=None, timeout=10):
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection("storage.googleapis.com", 443, timeout=timeout)
    try:
        headers = {"Accept-Encoding": "identity"}
        if etag:
            headers["If-None-Match"] = etag
        connection.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), headers=headers)
        return Response(connection, connection.getresponse())
    except Exception:
        connection.close()
        raise


def probe_media(path, media):
    phase = "probe"
    args = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
            "format=format_name,duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate:stream_side_data_list:stream_disposition=attached_pic",
            "-of", "json", str(path)]
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        if len(result.stdout) > 1024 * 1024:
            raise ValueError()
        data = json.loads(result.stdout)
        phase = "metadata"
        videos = [item for item in data.get("streams", []) if item.get("codec_type") == "video" and not item.get("disposition", {}).get("attached_pic")]
        first_video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), None)
        audios = [item for item in data.get("streams", []) if item.get("codec_type") == "audio"]
        formats = set(data.get("format", {}).get("format_name", "").split(","))
        kind = media["type"]
        video = videos[0] if videos else None
        if kind != "audio" and first_video is not video:
            raise MediaError("MEDIA_VIDEO_TRACK_UNSUPPORTED")
        audio = audios[0] if audios else None
        needs_audio = kind == "audio" or (kind == "video" and media.get("audio_enabled", True))
        if kind != "audio":
            if not video:
                raise MediaError("MEDIA_VIDEO_TRACK_MISSING")
            width, height = int(video.get("width", 0)), int(video.get("height", 0))
            rotation = next((float(item["rotation"]) for item in video.get("side_data_list", []) if "rotation" in item), 0)
            if not math.isfinite(rotation) or rotation % 90 != 0:
                raise MediaError("MEDIA_ROTATION_UNSUPPORTED")
            if int(rotation) % 180:
                width, height = height, width
            if not 1 <= width <= 1920 or not 1 <= height <= 1080:
                raise MediaError("MEDIA_RESOLUTION_UNSUPPORTED")
        if needs_audio and not audio:
            raise MediaError("MEDIA_AUDIO_TRACK_MISSING")
        duration = None
        if kind != "image":
            duration = float(data.get("format", {}).get("duration", 0))
            if not math.isfinite(duration) or not 0 < duration <= 3600:
                raise MediaError("MEDIA_DURATION_UNSUPPORTED")
        if kind == "video":
            if "mp4" not in formats or video.get("codec_name") != "h264" or (needs_audio and audio.get("codec_name") != "aac"):
                raise MediaError("MEDIA_FORMAT_UNSUPPORTED")
            numerator, denominator = video.get("avg_frame_rate", "0/1").split("/")
            fps = float(numerator) / float(denominator)
            if not math.isfinite(fps) or not 0 < fps <= 30.01:
                raise MediaError("MEDIA_FPS_UNSUPPORTED")
            suffix = ".mp4"
        elif kind == "image":
            if not formats.intersection({"png_pipe", "jpeg_pipe", "image2"}) or video.get("codec_name") not in {"png", "mjpeg"}:
                raise MediaError("MEDIA_FORMAT_UNSUPPORTED")
            suffix = ".png" if video["codec_name"] == "png" else ".jpg"
        elif kind == "audio":
            codec = audio.get("codec_name", "")
            allowed = ("mp3" in formats and codec == "mp3") or ("wav" in formats and codec in {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_u8", "pcm_f32le", "pcm_f64le"}) or ("mp4" in formats and codec == "aac")
            if not allowed:
                raise MediaError("MEDIA_FORMAT_UNSUPPORTED")
            suffix = ".mp3" if "mp3" in formats else ".wav" if "wav" in formats else ".m4a"
        else:
            raise MediaError("MEDIA_TYPE_UNSUPPORTED")
        # Decode an initial sample; subsequent decoding errors remain SDK playback failures.
        decode = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-protocol_whitelist", "file,pipe", "-i", str(path), "-t", "0.1"]
        if kind != "audio":
            decode += ["-map", f"0:{int(video['index'])}"]
        if needs_audio:
            decode += ["-map", f"0:{int(audio['index'])}"]
        decode += ["-f", "null", "-"]
        phase = "decode"
        subprocess.run(decode, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=True)
        return {"suffix": suffix, "duration_seconds": duration, "video_codec": video.get("codec_name") if kind != "audio" else None,
                "audio_codec": audio.get("codec_name") if needs_audio else None,
                "width": width if kind != "audio" else None, "height": height if kind != "audio" else None}
    except MediaError:
        raise
    except subprocess.TimeoutExpired:
        raise MediaError("MEDIA_PROBE_TIMEOUT") from None
    except subprocess.CalledProcessError:
        raise MediaError("MEDIA_DECODE_INVALID" if phase == "decode" else "MEDIA_INVALID") from None
    except (ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError, OSError):
        raise MediaError("MEDIA_INVALID") from None


class MediaLease:
    def __init__(self, cache, path, marker, metadata):
        self.cache, self.path, self.marker, self.metadata = cache, path, marker, metadata
        self.released = False

    def release(self):
        if not self.released:
            with self.cache.locked():
                self.marker.unlink(missing_ok=True)
            self.released = True


class MediaCache:
    FILE = re.compile(r"^[0-9a-f]{64}\.(mp4|m4a|mp3|wav|png|jpg)$")

    def __init__(self, root, bucket="zoom-app-dev.firebasestorage.app", *, capacity=2 * 1024**3,
                 reserve=5 * 1024**3, max_bytes=1024**3, image_max_bytes=10 * 1024**2,
                 total_timeout=300, transport=fetch, probe=probe_media):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        (self.root / ".pins").mkdir(exist_ok=True, mode=0o700)
        self.bucket, self.capacity, self.reserve = bucket, capacity, reserve
        self.max_bytes, self.image_max_bytes = max_bytes, image_max_bytes
        self.total_timeout, self.transport, self.probe = total_timeout, transport, probe
        self.thread_lock = threading.RLock()
        with self.locked():
            for path in self.root.glob(".part-*"):
                if path.is_file() and not path.is_symlink():
                    path.unlink()

    @contextmanager
    def locked(self):
        import fcntl  # Cache runs in the Linux worker, not Windows API clients.
        with self.thread_lock:
            descriptor = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def files(self):
        return [path for path in self.root.iterdir() if self.FILE.fullmatch(path.name) and path.is_file() and not path.is_symlink()]

    def pins(self):
        pinned = set()
        for marker in (self.root / ".pins").iterdir():
            name = marker.read_text()
            if not self.FILE.fullmatch(name):
                raise MediaError("CACHE_STATE_INVALID")
            pinned.add(name)
        return pinned

    def make_room(self, incoming):
        files = self.files()
        used = sum(path.stat().st_size for path in files)
        pinned = self.pins()
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            if used + incoming <= self.capacity:
                break
            if path.name not in pinned:
                used -= path.stat().st_size
                path.unlink()
                self.remove_references(path.name)
        if used + incoming > self.capacity:
            raise MediaError("CACHE_FULL")
        if shutil.disk_usage(self.root).free < self.reserve:
            raise MediaError("MEDIA_DISK_SPACE_LOW")

    def remove_references(self, filename):
        for reference in self.root.glob("*.json"):
            if reference.is_symlink():
                raise MediaError("CACHE_STATE_INVALID")
            try:
                if json.loads(reference.read_text()).get("file") == filename:
                    reference.unlink()
            except (ValueError, AttributeError):
                reference.unlink()

    def lease(self, path, metadata):
        marker = self.root / ".pins" / str(uuid.uuid4())
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(path.name)
        os.utime(path, None)
        return MediaLease(self, path, marker, metadata)

    @staticmethod
    def sha(path):
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    def resolve(self, media, cancel=None):
        storage_url(media["url"], self.bucket)
        limit = self.image_max_bytes if media["type"] == "image" else self.max_bytes
        reference = self.root / (hashlib.sha256(media["url"].encode()).hexdigest() + ".json")
        deadline = time.monotonic() + self.total_timeout
        partial = None
        response = None
        with self.locked():
            try:
                cached = None
                if reference.is_file() and not reference.is_symlink():
                    try:
                        candidate = json.loads(reference.read_text())
                        name = candidate["file"]
                        if self.FILE.fullmatch(name):
                            path = self.root / name
                            if path.is_file() and not path.is_symlink():
                                if self.sha(path) != candidate["sha256"]:
                                    if name in self.pins():
                                        raise MediaError("CACHE_INTEGRITY_FAILED")
                                    path.unlink(); self.remove_references(name)
                                elif path.stat().st_size <= limit:
                                    cached = candidate
                    except (ValueError, KeyError, TypeError):
                        pass
                current = media["url"]
                for redirect in range(4):
                    if cancel and cancel.is_set():
                        raise MediaError("MEDIA_DOWNLOAD_CANCELLED")
                    storage_url(current, self.bucket)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MediaError("MEDIA_DOWNLOAD_TIMEOUT")
                    response = self.transport(current, cached.get("etag") if cached else None, min(10, remaining))
                    if time.monotonic() >= deadline:
                        raise MediaError("MEDIA_DOWNLOAD_TIMEOUT")
                    if response.status not in {301, 302, 303, 307, 308}:
                        break
                    location = response.headers.get("location")
                    response.close(); response = None
                    if not location or redirect == 3:
                        raise MediaError("MEDIA_REDIRECT_INVALID")
                    current = urljoin(current, location)
                if response.status == 304 and cached:
                    path = self.root / cached["file"]
                    details = self.probe(path, media)
                    return self.lease(path, dict(cached, media=details))
                if response.status != 200:
                    raise MediaError("MEDIA_DOWNLOAD_HTTP_FAILED")
                length = response.headers.get("content-length")
                declared = int(length) if length is not None else None
                if declared is not None and (declared < 0 or declared > limit):
                    raise MediaError("MEDIA_TOO_LARGE")
                if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    raise MediaError("MEDIA_ENCODING_UNSUPPORTED")
                self.make_room(declared or 0)
                descriptor, name = tempfile.mkstemp(prefix=".part-", dir=self.root)
                partial = Path(name)
                sha = hashlib.sha256(); md5 = hashlib.md5(usedforsecurity=False); crc = google_crc32c.Checksum()
                size = 0
                with os.fdopen(descriptor, "wb") as file:
                    while True:
                        if cancel and cancel.is_set():
                            raise MediaError("MEDIA_DOWNLOAD_CANCELLED")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise MediaError("MEDIA_DOWNLOAD_TIMEOUT")
                        block = response.read(65536, min(30, remaining))
                        if not block:
                            break
                        size += len(block)
                        if size > limit:
                            raise MediaError("MEDIA_TOO_LARGE")
                        self.make_room(size)
                        if shutil.disk_usage(self.root).free - len(block) < self.reserve:
                            raise MediaError("MEDIA_DISK_SPACE_LOW")
                        file.write(block); sha.update(block); md5.update(block); crc.update(block)
                    file.flush(); os.fsync(file.fileno())
                if not size or (declared is not None and size != declared):
                    raise MediaError("MEDIA_DOWNLOAD_INCOMPLETE")
                hashes = {}
                for item in response.headers.get("x-goog-hash", "").split(","):
                    algorithm, separator, value = item.strip().partition("=")
                    if separator and algorithm in {"md5", "crc32c"}:
                        try:
                            hashes[algorithm] = base64.b64decode(value, validate=True)
                        except ValueError:
                            raise MediaError("MEDIA_CHECKSUM_INVALID") from None
                actual = {"md5": md5.digest(), "crc32c": crc.digest()}
                if any(not hmac.compare_digest(value, actual[algorithm]) for algorithm, value in hashes.items()):
                    raise MediaError("MEDIA_CHECKSUM_MISMATCH")
                details = self.probe(partial, media)
                digest = sha.hexdigest()
                target = self.root / (digest + details["suffix"])
                if target.exists():
                    if target.is_symlink() or self.sha(target) != digest:
                        raise MediaError("CACHE_INTEGRITY_FAILED")
                    partial.unlink(); partial = None
                else:
                    partial.chmod(0o400)
                    os.replace(partial, target); partial = None
                metadata = {"file": target.name, "sha256": digest, "bytes": size, "etag": response.headers.get("etag"),
                            "checksum_verified": bool(hashes), "media": details}
                descriptor, name = tempfile.mkstemp(prefix=".part-", dir=self.root)
                partial = Path(name)
                with os.fdopen(descriptor, "w") as file:
                    json.dump(metadata, file); file.flush(); os.fsync(file.fileno())
                os.replace(partial, reference); partial = None
                return self.lease(target, metadata)
            except MediaError:
                raise
            except TimeoutError:
                raise MediaError("MEDIA_DOWNLOAD_TIMEOUT") from None
            except Exception:
                raise MediaError("MEDIA_DOWNLOAD_FAILED") from None
            finally:
                if response:
                    response.close()
                if partial:
                    partial.unlink(missing_ok=True)

    def cleanup(self):
        """Remove unpinned media; crash pins require supervisor reconciliation first."""
        with self.locked():
            pinned = self.pins()
            for path in self.files():
                if path.name not in pinned:
                    path.unlink()
            for path in self.root.glob("*.json"):
                data = json.loads(path.read_text())
                if data.get("file") not in pinned:
                    path.unlink()

    def reconcile_pins(self, *, cleanup_confirmed=False):
        """Only the singleton supervisor may clear crash pins after native cleanup."""
        if not cleanup_confirmed:
            raise MediaError("SDK_CLEANUP_UNCONFIRMED")
        with self.locked():
            for marker in (self.root / ".pins").iterdir():
                if marker.is_symlink() or not marker.is_file():
                    raise MediaError("CACHE_STATE_INVALID")
                marker.unlink()
