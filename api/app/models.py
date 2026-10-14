"""Strict public input models. Validation never returns received values."""
from typing import Annotated, Literal, Union
from urllib.parse import unquote, urlsplit
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Meeting(StrictModel):
    number: str = Field(pattern=r"^[0-9]{9,11}$")
    password: str = Field(default="", max_length=128)
    participant_name: str = Field(default="VideoBot", min_length=1, max_length=64)

    @field_validator("number")
    @classmethod
    def number_valid(cls, value):
        if set(value) == {"0"}:
            raise ValueError("invalid meeting number")
        return value

    @field_validator("password", "participant_name")
    @classmethod
    def text_valid(cls, value, info):
        if any(ord(c) < 32 or ord(c) == 127 or c == '"' for c in value):
            raise ValueError("invalid text")
        if info.field_name == "participant_name" and not value.strip():
            raise ValueError("invalid name")
        return value


class Options(StrictModel):
    waiting_room_timeout_seconds: int = Field(default=900, ge=30, le=1800)
    max_session_seconds: int = Field(default=5400, ge=60, le=5400)


class JoinRequest(StrictModel):
    meeting: Meeting
    options: Options = Field(default_factory=Options)


class Media(StrictModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def source_valid(cls, value):
        try:
            url = urlsplit(value)
            if url.scheme != "https" or url.hostname != "storage.googleapis.com" or url.port not in (None, 443):
                raise ValueError()
            if url.username or url.password or url.fragment or any(ord(c) <= 32 or ord(c) == 127 for c in value):
                raise ValueError()
            (url.path + url.query).encode("ascii")
            path = unquote(url.path)
            for _ in range(3):
                parts = path.split("/", 2)
                if len(parts) != 3 or parts[1] != "zoom-app-dev.firebasestorage.app" or not parts[2]:
                    raise ValueError()
                if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
                    raise ValueError()
                path = unquote(path)
        except (ValueError, UnicodeError):
            raise ValueError("source not allowed") from None
        return value


class VideoMedia(Media):
    type: Literal["video"]
    audio_enabled: bool = True


class AudioMedia(Media):
    type: Literal["audio"]


class ImageMedia(Media):
    type: Literal["image"]
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)


class PlayRequest(StrictModel):
    media: Annotated[Union[VideoMedia, AudioMedia, ImageMedia], Field(discriminator="type")]


class ControlRequest(StrictModel):
    playback_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    @field_validator("playback_id")
    @classmethod
    def normalized_id(cls, value):
        return str(uuid.UUID(value)) if value is not None else None
