"""Local diagnostic CLI; not the public HTTP API."""
import argparse
import json
from .sdk_control import SdkControl

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["status", "play", "pause", "resume", "stop", "quit"])
parser.add_argument("--playback-id")
parser.add_argument("--type", dest="media_type", choices=["video", "video-silent", "audio"])
parser.add_argument("--path")
args = parser.parse_args()
fields = {key: value for key, value in vars(args).items() if key != "command" and value is not None}
print(json.dumps(SdkControl().command(args.command, **fields)))
