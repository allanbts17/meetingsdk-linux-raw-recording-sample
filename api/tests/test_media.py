import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import google_crc32c
from app.media import MediaCache, MediaError, storage_url, probe_media

URL = "https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/videos/test.mp4"


class FakeResponse:
    def __init__(self, body=b"sample", status=200, headers=None):
        self.status = status
        self.body = body
        self.offset = 0
        crc = google_crc32c.Checksum(); crc.update(body)
        self.headers = {"etag": '"version-1"', "content-length": str(len(body)), "x-goog-hash":
                        "crc32c=" + base64.b64encode(crc.digest()).decode() + ",md5=" + base64.b64encode(hashlib.md5(body).digest()).decode()}
        if headers:
            self.headers.update(headers)
        self.closed = False

    def read(self, size, timeout):
        block = self.body[self.offset:self.offset + size]
        self.offset += len(block)
        return block

    def close(self):
        self.closed = True


def fake_probe(path, media):
    return {"suffix": ".mp4", "duration_seconds": 1}


class MediaCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = 0
        def transport(url, etag=None, timeout=10):
            self.calls += 1
            return FakeResponse(status=304) if etag == '"version-1"' else FakeResponse()
        self.cache = MediaCache(self.temp.name, reserve=0, transport=transport, probe=fake_probe)
        self.media = {"type": "video", "url": URL}

    def tearDown(self):
        self.temp.cleanup()

    def assert_clean_partial(self):
        self.assertEqual(list(Path(self.temp.name).glob(".part-*")), [])

    def test_download_checksum_readonly_pin_cleanup_and_no_url_metadata(self):
        resource = self.cache.resolve(self.media)
        self.assertEqual(resource.path.read_bytes(), b"sample")
        self.assertTrue(resource.metadata["checksum_verified"])
        self.assertEqual(resource.path.stat().st_mode & 0o777, 0o400)
        self.assertNotIn(URL, str(resource.metadata))
        self.cache.cleanup()
        self.assertTrue(resource.path.exists())
        resource.release(); resource.release(); self.cache.cleanup()
        self.assertFalse(resource.path.exists())
        self.assert_clean_partial()

    def test_conditional_reuse_and_parallel_leases(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            resources = list(pool.map(lambda _: self.cache.resolve(self.media), range(4)))
        self.assertEqual(len({item.path for item in resources}), 1)
        self.assertEqual(len(list((Path(self.temp.name) / ".pins").iterdir())), 4)
        for item in resources:
            item.release()
        self.assert_clean_partial()

    def test_changed_object_creates_new_file_without_replacing_pinned_version(self):
        original = self.cache.resolve(self.media)
        self.cache.transport = lambda *args: FakeResponse(b"new-data", headers={"etag": '"version-2"'})
        changed = self.cache.resolve(self.media)
        self.assertNotEqual(original.path, changed.path)
        self.assertEqual(original.path.read_bytes(), b"sample")
        self.assertEqual(changed.path.read_bytes(), b"new-data")
        original.release(); changed.release()

    def test_wrong_checksum_and_incomplete_download_never_publish(self):
        for response, code in [(FakeResponse(headers={"x-goog-hash": "crc32c=AAAAAA=="}), "CHECKSUM_MISMATCH"),
                               (FakeResponse(headers={"content-length": "100"}), "INCOMPLETE")]:
            self.cache.transport = lambda *args: response
            with self.assertRaisesRegex(MediaError, code):
                self.cache.resolve(self.media)
            self.assertEqual(self.cache.files(), [])
            self.assertTrue(response.closed)
            self.assert_clean_partial()

    def test_no_content_length_still_obeys_limit(self):
        response = FakeResponse(b"123456789")
        del response.headers["content-length"]
        self.cache.transport = lambda *args: response
        self.cache.max_bytes = 5
        with self.assertRaisesRegex(MediaError, "TOO_LARGE"):
            self.cache.resolve(self.media)
        self.assert_clean_partial()

    def test_pins_prevent_eviction_and_survive_other_cache_instance(self):
        self.cache.capacity = 10
        resource = self.cache.resolve(self.media)
        other = MediaCache(self.temp.name, reserve=0, capacity=10, transport=lambda *args: FakeResponse(b"123456789"), probe=fake_probe)
        with self.assertRaisesRegex(MediaError, "CACHE_FULL"):
            other.resolve(dict(self.media, url=URL + "?generation=2"))
        self.assertTrue(resource.path.exists())
        resource.release()
        replacement = other.resolve(dict(self.media, url=URL + "?generation=2"))
        self.assertFalse(resource.path.exists())
        replacement.release()

    def test_redirect_to_metadata_or_wrong_bucket_never_requested(self):
        destinations = []
        def redirect(url, *args):
            destinations.append(url)
            return FakeResponse(status=302, headers={"location": "http://169.254.169.254/computeMetadata/v1/"})
        self.cache.transport = redirect
        with self.assertRaisesRegex(MediaError, "URL_NOT_ALLOWED"):
            self.cache.resolve(self.media)
        self.assertEqual(destinations, [URL])

    def test_cancelled_and_low_disk_fail_without_partial_files(self):
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaisesRegex(MediaError, "CANCELLED"):
            self.cache.resolve(self.media, cancel=cancelled)
        with patch("app.media.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
            self.cache.reserve = 1
            with self.assertRaisesRegex(MediaError, "DISK_SPACE_LOW"):
                self.cache.resolve(self.media)
        self.assert_clean_partial()

    def test_probe_failure_does_not_publish(self):
        def reject(*args):
            raise MediaError("MEDIA_AUDIO_TRACK_MISSING")
        self.cache.probe = reject
        with self.assertRaisesRegex(MediaError, "AUDIO_TRACK_MISSING"):
            self.cache.resolve(self.media)
        self.assertEqual(self.cache.files(), [])
        self.assert_clean_partial()

    def test_corrupted_cache_is_repaired_only_after_unpinning(self):
        resource = self.cache.resolve(self.media)
        resource.path.chmod(0o600)
        resource.path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(MediaError, "CACHE_INTEGRITY_FAILED"):
            self.cache.resolve(self.media)
        resource.release()
        repaired = self.cache.resolve(self.media)
        self.assertEqual(repaired.path.read_bytes(), b"sample")
        repaired.release()

    def test_cancel_during_transfer_and_read_timeout_remove_partial(self):
        cancelled = threading.Event()
        response = FakeResponse(b"x" * 70000)
        read = response.read
        def interrupt(size, timeout):
            block = read(size, timeout)
            cancelled.set()
            return block
        response.read = interrupt
        self.cache.transport = lambda *args: response
        with self.assertRaisesRegex(MediaError, "DOWNLOAD_CANCELLED"):
            self.cache.resolve(self.media, cancel=cancelled)
        self.assert_clean_partial()
        response = FakeResponse()
        def timeout(*args):
            raise TimeoutError()
        response.read = timeout
        self.cache.transport = lambda *args: response
        with self.assertRaisesRegex(MediaError, "DOWNLOAD_TIMEOUT"):
            self.cache.resolve(self.media)
        self.assert_clean_partial()

    def test_allowed_redirect_is_revalidated_and_downloads(self):
        calls = []
        def redirect(url, *args):
            calls.append(url)
            return FakeResponse(status=302, headers={"location": "next.mp4"}) if len(calls) == 1 else FakeResponse()
        self.cache.transport = redirect
        resource = self.cache.resolve(self.media)
        self.assertEqual(calls[-1], URL.replace("test.mp4", "next.mp4"))
        resource.release()

    def test_transport_exception_does_not_expose_url_query(self):
        def failure(*args):
            raise RuntimeError("request failed with private-signature")
        self.cache.transport = failure
        with self.assertRaises(MediaError) as result:
            self.cache.resolve(dict(self.media, url=URL + "?signature=private-signature"))
        self.assertNotIn("private-signature", str(result.exception))


class MediaPolicyTests(unittest.TestCase):
    def test_url_allowlist_and_encoded_traversal(self):
        bucket = "zoom-app-dev.firebasestorage.app"
        self.assertEqual(storage_url(URL, bucket).hostname, "storage.googleapis.com")
        for url in [URL.replace("https", "http"), URL.replace(bucket, "another-bucket"), URL.replace("storage.googleapis.com", "127.0.0.1"),
                    URL.replace("storage.googleapis.com", "user:pass@storage.googleapis.com"), URL + "#fragment",
                    URL.replace("videos/test", "videos/%252e%252e/test")]:
            with self.assertRaises(MediaError):
                storage_url(url, bucket)

    def test_probe_formats_limits_rotation_and_required_tracks(self):
        video = {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 640, "height": 480, "avg_frame_rate": "30/1"}
        audio = {"index": 1, "codec_type": "audio", "codec_name": "aac"}
        data = {"streams": [video, audio], "format": {"format_name": "mov,mp4,m4a", "duration": "10"}}
        def run(*args, **kwargs):
            return SimpleNamespace(stdout=json.dumps(data).encode())
        with patch("app.media.subprocess.run", side_effect=run):
            self.assertEqual(probe_media("/tmp/test", {"type": "video"})["width"], 640)
            data["streams"] = [video]
            with self.assertRaisesRegex(MediaError, "AUDIO_TRACK_MISSING"):
                probe_media("/tmp/test", {"type": "video"})
            self.assertEqual(probe_media("/tmp/test", {"type": "video", "audio_enabled": False})["video_codec"], "h264")
            video["avg_frame_rate"] = "60/1"
            with self.assertRaisesRegex(MediaError, "FPS_UNSUPPORTED"):
                probe_media("/tmp/test", {"type": "video", "audio_enabled": False})
            video.update(width=1080, height=1920, avg_frame_rate="30/1", side_data_list=[{"rotation": 90}])
            self.assertEqual(probe_media("/tmp/test", {"type": "video", "audio_enabled": False})["width"], 1920)
            video["side_data_list"] = []
            with self.assertRaisesRegex(MediaError, "RESOLUTION_UNSUPPORTED"):
                probe_media("/tmp/test", {"type": "video", "audio_enabled": False})
