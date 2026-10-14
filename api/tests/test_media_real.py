from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from app.media import probe_media, MediaError


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Needs worker FFmpeg tools")
class RealProbeTests(unittest.TestCase):
    def test_real_worker_probe_sections_video_audio_image_and_invalid_file(self):
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=25",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "0.4",
                            "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(video)], check=True, timeout=15)
            partial = Path(root) / ".part-download"
            shutil.copyfile(video, partial)
            metadata = probe_media(partial, {"type": "video", "audio_enabled": True})
            self.assertEqual(metadata["suffix"], ".mp4")
            self.assertEqual(metadata["width"], 320)
            self.assertEqual(metadata["audio_codec"], "aac")
            self.assertEqual(probe_media(partial, {"type": "audio"})["suffix"], ".m4a")
            rotated = Path(root) / "rotated.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-c", "copy", "-metadata:s:v:0", "rotate=90", str(rotated)], check=True, timeout=15)
            metadata = probe_media(rotated, {"type": "video"})
            self.assertEqual((metadata["width"], metadata["height"]), (240, 320))
            image = Path(root) / "image.png"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:size=320x240",
                            "-frames:v", "1", "-threads", "1", str(image)], check=True, timeout=15)
            self.assertEqual(probe_media(image, {"type": "image"})["suffix"], ".png")
            partial.write_bytes(b"invalid media")
            with self.assertRaises(MediaError):
                probe_media(partial, {"type": "video"})
