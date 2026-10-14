"""Explicit local integration test; uses a test-only local media resolver, not HTTP."""
import argparse
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from app.agent import Agent
from app.payloads import PayloadCipher
from app.runtime import SdkRuntime
from app.store import Store
from app.media import MediaCache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Protected local JSON; never pass credentials as arguments")
    parser.add_argument("--video", default="/app/media/video.mp4")
    parser.add_argument("--media-request", help="JSON play body with a permitted Storage URL")
    parser.add_argument("--hold-seconds", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.hold_seconds <= 120:
        parser.error("hold-seconds must be 1..120")
    settings = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory(prefix="zb-") as directory:
        def credentials():
            return {"clientId": settings["clientId"], "clientSecret": settings["clientSecret"]}
        runtime = SdkRuntime(Path(directory) / "s", credentials)
        store = Store(Path(directory) / "state.db")
        def media_resolver(media):
            if media["url"] != "https://example.test/local-demo":
                raise ValueError("test resolver only")
            return Path(args.video).resolve(strict=True)
        agent = Agent(store, PayloadCipher(os.urandom(32)), runtime, media_resolver)
        cache = MediaCache(Path(directory) / "cache") if args.media_request else None
        if cache:
            agent.media_resolver = cache
        play_payload = json.loads(Path(args.media_request).read_text(encoding="utf-8-sig")) if args.media_request else {
            "media": {"type": "video", "url": "https://example.test/local-demo"}}
        for sig in [signal.SIGINT, signal.SIGTERM]:
            signal.signal(sig, lambda *_: agent.stopping.set())
        response, _ = agent.submit_join("local-demo", "demo-join-key-0001", {"meeting": {
            "number": settings["meetingNumber"], "password": settings.get("meetingPassword", ""),
            "participant_name": settings.get("participantName", "VideoBot")},
            "options": {"waiting_room_timeout_seconds": 60, "max_session_seconds": 120}})
        bot = response["bot_id"]
        try:
            agent.run_once()
            if store.session(bot, "local-demo")["state"] != "active":
                raise RuntimeError("join failed")
            print(json.dumps({"event": "agent.joined", "bot_id": bot}), flush=True)
            play, _ = agent.submit_control("local-demo", bot, "play", "demo-play-key-0001", play_payload)
            agent.run_once()
            result = store.operation(play["operation_id"], "local-demo")
            if result["status"] != "succeeded":
                print(json.dumps({"event": "agent.play_failed", "error": result["error"]}), flush=True)
                raise RuntimeError("play failed")
            print(json.dumps({"event": "agent.playing", "bot_id": bot}), flush=True)
            if cache:
                resource = agent.media_resources[bot]
                print(json.dumps({"event": "media.ready", "bytes": resource.metadata["bytes"],
                                  "checksum_verified": resource.metadata["checksum_verified"], "media": resource.metadata["media"]}), flush=True)
            agent.stopping.wait(args.hold_seconds)
            leave, _ = agent.submit_control("local-demo", bot, "leave", "demo-leave-key-0001", {})
            agent.run_once()
            assert store.operation(leave["operation_id"], "local-demo")["status"] == "succeeded"
            assert store.capacity()["available"] == 1
            print(json.dumps({"event": "agent.ended", "capacity_available": 1}), flush=True)
        finally:
            if runtime.bot_id is not None:
                runtime.cleanup(bot)
            agent.release_media(bot)
            if cache:
                cache.cleanup()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Underlying errors can include private file contents or credential-provider details.
        print("AGENT_DEMO_FAILED", flush=True)
        raise SystemExit(1)
