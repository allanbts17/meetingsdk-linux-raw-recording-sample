"""Private HTTP adapter. Only submissions/queries use HTTP threads, never SDK control."""
import asyncio
import base64
from datetime import datetime, timezone
import json
import math
import uuid
from .http_common import ApiError
from .store import StoreError
from .validation import ValidationError


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z") if value is not None else None


def session_view(data):
    session, state, play = data["session"], data["snapshot"], data["play"]
    status = session["state"]
    if status == "active" and state.get("meeting_status") == 5:
        status = "reconnecting"
    elif status == "accepted" and data["pending"] and data["pending"]["status"] == "running":
        status = "waiting_room" if state.get("meeting_status") in {2, 11} else "joining"
    playback_id = play["playback_id"] if play else None
    playback_state = "idle"
    position = None
    metadata = json.loads(play["metadata"]) if play else {}
    if play:
        if play["status"] in {"queued", "running"}:
            playback_state = "buffering"
        elif state.get("playback_id") == playback_id:
            playback_state = state.get("playback_state", "idle")
            position = state.get("position_seconds")
        else:
            playback_state = "stopped" if play["status"] == "cancelled" else "failed"
    released = not bool(session["reserves"])
    if released and playback_state in {"playing", "paused", "buffering"}:
        playback_state = "stopped"
    meeting = dict(data["meeting"], status="in_meeting" if status == "active" else status,
                   audio_permission=None, video_permission=None)
    media = None
    if play:
        media = {"download_status": "ready" if metadata.get("downloaded_bytes") is not None else playback_state,
                 "downloaded_bytes": metadata.get("downloaded_bytes"), "total_bytes": metadata.get("downloaded_bytes"),
                 "media_id": metadata.get("media_id"), "source": metadata.get("source"), "output": None}
    return {"bot_id": session["id"], "status": status, "meeting": meeting,
            "playback": {"playback_id": playback_id, "media_type": metadata.get("type"), "status": playback_state,
                         "position_seconds": position, "duration_seconds": metadata.get("duration_seconds") if metadata.get("type") == "image"
                         else metadata.get("source", {}).get("duration_seconds"),
                         "audio_enabled": metadata.get("audio_enabled", metadata.get("type") == "audio") if play else None,
                         "pause_reasons": state.get("pause_reasons", ["user"]) if playback_state == "paused" else [],
                         "can_pause": status == "active" and playback_state in {"playing", "paused"},
                         "can_resume": status == "active" and playback_state in {"playing", "paused"}
                         and not any(reason != "user" for reason in state.get("pause_reasons", [])),
                         "can_stop": status in {"active", "reconnecting"} and playback_state != "idle"},
            "media": media, "pending_operation_id": data["pending"]["id"] if data["pending"] else None,
            "resource_released": released, "state_version": data["version"], "created_at": timestamp(session["created"]),
            "updated_at": timestamp(max(data["updated"], data["snapshot_updated"] or 0)),
            "last_error": {"code": data["last_error"]} if data["last_error"] else None}


class AgentBackend:
    def __init__(self, agent, owner, *, enforce_limits=True):
        self.agent, self.store, self.owner = agent, agent.store, owner
        self.enforce_limits = enforce_limits

    async def request(self, method, path, *, body=None, key=None, request_id=None, params=None):
        try:
            return await asyncio.to_thread(self.dispatch, method, path, body or {}, key, params or {})
        except StoreError as error:
            code = str(error)
            aliases = {"CAPACITY_EXHAUSTED": "CAPACITY_EXCEEDED", "BOT_NOT_ACTIVE": "INVALID_STATE",
                       "PLAYBACK_ALREADY_ACTIVE": "PLAYBACK_BUSY", "PLAYBACK_ID_MISMATCH": "PLAYBACK_CHANGED"}
            code = aliases.get(code, code)
            status = 404 if code in {"BOT_NOT_FOUND", "OPERATION_NOT_FOUND"} else (429 if code == "RATE_LIMITED" else
                     (503 if code == "STATE_RECONCILING" else 409))
            raise ApiError(code, status) from None
        except ValidationError:
            raise ApiError("VALIDATION_ERROR", 422) from None

    def dispatch(self, method, path, body, key, params):
        if self.enforce_limits:
            self.store.rate_limit(self.owner, method in {"POST", "DELETE"})
        healthy = self.store.health()["ready"]
        if path == "/health/ready":
            return (200 if healthy else 503), {"status": "ready" if healthy else "not_ready",
                "checks": {"database": "ok", "worker": "healthy" if healthy else "unavailable"}}, {}
        if path == "/v1/capacity":
            capacity = self.store.capacity()
            reserved = self.store.reserved_sessions()
            return 200, {"max_concurrent_bots": capacity["limit"], "reserved_slots": capacity["occupied"],
                "available_slots": capacity["available"], "active_bot_id": reserved[0]["id"] if reserved else None,
                "accepting_new_sessions": healthy and capacity["available"] > 0,
                "worker_status": "healthy" if healthy else "unavailable"}, {}
        if path == "/v1/bots" and method == "GET":
            return 200, self.list_bots(params), {}
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[1] == "operations":
            value = self.store.operation(parts[2], self.owner)
            result = json.loads(value["result"]) if value["result"] else None
            return 200, {"operation_id": value["id"], "bot_id": value["bot_id"], "action": value["command"],
                "playback_id": value["playback_id"], "status": value["status"], "no_op": bool(result and result.get("no_op")),
                "requested_at": timestamp(value["created"]), "started_at": timestamp(value["started"]),
                "completed_at": timestamp(value["completed"]), "result": result,
                "error": {"code": value["error"]} if value["error"] else None}, {}
        if method == "GET" and len(parts) >= 3:
            bot = parts[2]
            if len(parts) == 4 and parts[3] == "events":
                after, limit = params.get("after_sequence", 0), params.get("limit", 50)
                rows = self.store.events(bot, self.owner, after, limit + 1)
                names = {("join", "queued"): "bot.accepted", ("join", "succeeded"): "meeting.joined",
                         ("play", "succeeded"): "playback.started", ("pause", "succeeded"): "playback.paused",
                         ("resume", "succeeded"): "playback.resumed", ("stop", "succeeded"): "playback.stopped",
                         ("leave", "queued"): "bot.leaving", ("leave", "succeeded"): "bot.ended"}
                items = []
                for row in rows[:limit]:
                    data = json.loads(row["data"]) if row["data"] else {}
                    kind = "operation.succeeded" if data.get("no_op") else names.get((row["kind"], row["state"]), f'{row["kind"]}.{row["state"]}')
                    items.append({"sequence": row["sequence"], "type": kind, "occurred_at": timestamp(row["created"]), "data": data})
                return 200, {"items": items, "next_after_sequence": items[-1]["sequence"] if items else after,
                             "has_more": len(rows) > limit}, {}
            return 200, session_view(self.store.public_data(bot, self.owner)), {}
        if method in {"POST", "DELETE"}:
            if not healthy and method != "DELETE":
                raise ApiError("WORKER_UNAVAILABLE", 503)
            if path == "/v1/bots":
                response, replayed = self.agent.submit_join(self.owner, key, body)
                action = "join"
            else:
                action = "leave" if method == "DELETE" else parts[3]
                response, replayed = self.agent.submit_control(self.owner, parts[2], action, key, body)
            response = dict(response, action=action, links={"bot": f'/v1/bots/{response["bot_id"]}',
                                                           "operation": f'/v1/operations/{response["operation_id"]}'})
            if action == "join":
                response["status"] = "accepted"
            headers = {"Idempotency-Replayed": str(replayed).lower(), "Retry-After": "1",
                       "Location": response["links"]["bot"] if action == "join" else response["links"]["operation"]}
            return (200 if response.get("no_op") else 202), response, headers
        raise ApiError("NOT_FOUND", 404)

    def list_bots(self, params):
        limit, status, cursor = params.get("limit", 20), params.get("status"), params.get("cursor")
        before = None
        if cursor:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if value["owner"] != self.owner or value["status"] != status or not math.isfinite(value["created"]):
                    raise ValueError()
                uuid.UUID(value["id"])
                before = (value["created"], value["id"])
            except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
                raise ApiError("INVALID_CURSOR", 422) from None
        rows = self.store.list_sessions(self.owner, limit + 1, status, before)
        selected = rows[:limit]
        items = []
        for row in selected:
            view = session_view(self.store.public_data(row["id"], self.owner))
            items.append({"bot_id": row["id"], "status": view["status"],
                          "playback_status": view["playback"]["status"], "created_at": timestamp(row["created"])})
        next_cursor = None
        if len(rows) > limit:
            last = selected[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps({"owner": self.owner, "status": status,
                "created": last["created"], "id": last["id"]}).encode()).decode().rstrip("=")
        return {"items": items, "next_cursor": next_cursor}
