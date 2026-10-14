"""Internal submission validation; HTTP models will enforce the same contract."""
import re
from urllib.parse import urlsplit


class ValidationError(RuntimeError):
    pass


def fields(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValidationError("INVALID_REQUEST")


def join_payload(payload):
    fields(payload, ["meeting", "options"])
    meeting = payload.get("meeting")
    fields(meeting, ["number", "password", "participant_name"])
    number = meeting.get("number")
    password = meeting.get("password", "")
    name = meeting.get("participant_name", "VideoBot")
    if not isinstance(number, str) or not re.fullmatch(r"[0-9]{9,11}", number) or set(number) == {"0"}:
        raise ValidationError("INVALID_MEETING_NUMBER")
    if not isinstance(password, str) or len(password) > 128 or not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
        raise ValidationError("INVALID_MEETING_FIELDS")
    if any(ord(char) < 32 or ord(char) == 127 or char == '"' for value in [password, name] for char in value):
        raise ValidationError("INVALID_MEETING_FIELDS")
    options = payload.get("options", {})
    fields(options, ["waiting_room_timeout_seconds", "max_session_seconds"])
    waiting = options.get("waiting_room_timeout_seconds", 900)
    maximum = options.get("max_session_seconds", 5400)
    if type(waiting) is not int or not 30 <= waiting <= 1800 or type(maximum) is not int or not 60 <= maximum <= 5400:
        raise ValidationError("INVALID_SESSION_OPTIONS")
    return {"meeting": {"number": number, "password": password, "participant_name": name},
            "options": {"waiting_room_timeout_seconds": waiting, "max_session_seconds": maximum}}


def control_payload(command, payload):
    fields(payload, ["media"] if command == "play" else ([] if command == "leave" else ["playback_id"]))
    if command != "play":
        identifier = payload.get("playback_id")
        if identifier is not None and (not isinstance(identifier, str) or not 1 <= len(identifier) <= 128):
            raise ValidationError("INVALID_PLAYBACK_ID")
        return payload
    media = payload.get("media")
    fields(media, ["type", "url", "audio_enabled", "duration_seconds"])
    kind, url = media.get("type"), media.get("url")
    if kind not in {"video", "audio", "image"} or not isinstance(url, str) or len(url) > 2048:
        raise ValidationError("INVALID_MEDIA")
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
    except ValueError:
        raise ValidationError("INVALID_MEDIA_URL") from None
    result = {"type": kind, "url": url}
    if kind == "video":
        enabled = media.get("audio_enabled", True)
        if type(enabled) is not bool or "duration_seconds" in media:
            raise ValidationError("INVALID_MEDIA_FIELDS")
        result["audio_enabled"] = enabled
    elif kind == "audio":
        if set(media) - {"type", "url"}:
            raise ValidationError("INVALID_MEDIA_FIELDS")
    else:
        duration = media.get("duration_seconds")
        if "audio_enabled" in media or (duration is not None and (type(duration) is not int or not 1 <= duration <= 3600)):
            raise ValidationError("INVALID_MEDIA_FIELDS")
        result["duration_seconds"] = duration
    return {"media": result}
