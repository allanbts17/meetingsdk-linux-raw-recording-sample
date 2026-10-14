"""Agent-owned durable state. Payloads must be encrypted before entering this layer."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


class StoreError(RuntimeError):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL,
                    reserves INTEGER NOT NULL CHECK(reserves IN (0,1)), created REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_meeting ON sessions(reserves) WHERE reserves=1;
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES sessions(id),
                    command TEXT NOT NULL, status TEXT NOT NULL, payload BLOB,
                    claimed_by TEXT, error TEXT, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL REFERENCES sessions(id), kind TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    owner TEXT NOT NULL, method TEXT NOT NULL, route TEXT NOT NULL, key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, bot_id TEXT NOT NULL REFERENCES sessions(id),
                    response TEXT NOT NULL, expires REAL NOT NULL,
                    PRIMARY KEY(owner,method,route,key)
                );
                CREATE TABLE IF NOT EXISTS worker_health (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    worker_id TEXT NOT NULL, updated REAL NOT NULL, ready INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_limits (
                    bot_id TEXT PRIMARY KEY REFERENCES sessions(id), deadline REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    bot_id TEXT PRIMARY KEY REFERENCES sessions(id), body TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cancellations (
                    operation_id TEXT PRIMARY KEY REFERENCES operations(id), reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operation_details (
                    operation_id TEXT PRIMARY KEY REFERENCES operations(id), playback_id TEXT,
                    metadata TEXT NOT NULL, started REAL, completed REAL, result TEXT
                );
                CREATE TABLE IF NOT EXISTS session_details (
                    bot_id TEXT PRIMARY KEY REFERENCES sessions(id), metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rate_events (owner TEXT NOT NULL, created REAL NOT NULL, mutation INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS rate_owner_time ON rate_events(owner,created);
                CREATE TABLE IF NOT EXISTS reconciling (bot_id TEXT PRIMARY KEY REFERENCES sessions(id));
                CREATE TABLE IF NOT EXISTS event_details (
                    sequence INTEGER PRIMARY KEY REFERENCES events(sequence), body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operations_bot_state ON operations(bot_id,status,created);
                CREATE INDEX IF NOT EXISTS events_bot_time ON events(bot_id,created);
                CREATE INDEX IF NOT EXISTS idempotency_bot_expiry ON idempotency(bot_id,expires);
            """)
        Path(self.path).chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def validate_key(owner, key, fingerprint, payload):
        if not owner or not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise StoreError("INVALID_IDEMPOTENCY")
        if not isinstance(payload, bytes) or not payload:
            raise StoreError("SEALED_PAYLOAD_REQUIRED")

    def replay(self, db, owner, method, route, key, fingerprint):
        row = db.execute("""SELECT i.*, s.reserves FROM idempotency i JOIN sessions s ON s.id=i.bot_id
                            WHERE i.owner=? AND method=? AND route=? AND key=?""",
                         (owner, method, route, key)).fetchone()
        if not row:
            return None
        if row["expires"] <= time.time() and not row["reserves"]:
            db.execute("DELETE FROM idempotency WHERE owner=? AND method=? AND route=? AND key=?", (owner, method, route, key))
            return None
        if row["fingerprint"] != fingerprint:
            raise StoreError("IDEMPOTENCY_CONFLICT")
        return json.loads(row["response"])

    def record(self, db, owner, method, route, key, fingerprint, bot_id, command, payload, *, playback_id=None, metadata=None):
        operation_id = str(uuid.uuid4())
        now = time.time()
        db.execute("INSERT INTO operations VALUES (?,?,?,'queued',?,NULL,NULL,?)", (operation_id, bot_id, command, payload, now))
        response = {"bot_id": bot_id, "operation_id": operation_id, "status": "queued"}
        if playback_id is not None:
            response["playback_id"] = playback_id
        db.execute("INSERT INTO operation_details VALUES (?,?,?,NULL,NULL,NULL)",
                   (operation_id, playback_id, json.dumps(metadata or {})))
        db.execute("INSERT INTO idempotency VALUES (?,?,?,?,?,?,?,?)",
                   (owner, method, route, key, fingerprint, bot_id, json.dumps(response), now + 86400))
        self.event(db, bot_id, command, "queued", {"operation_id": operation_id, "playback_id": playback_id})
        return response

    @staticmethod
    def event(db, bot_id, kind, state, data=None):
        safe = {key: value for key, value in (data or {}).items() if key in
                {"operation_id", "playback_id", "position_seconds", "reason", "playback_status", "no_op"} and value is not None}
        cursor = db.execute("INSERT INTO events(bot_id,kind,state,created) VALUES (?,?,?,?)", (bot_id, kind, state, time.time()))
        db.execute("INSERT INTO event_details VALUES (?,?)", (cursor.lastrowid, json.dumps(safe)))

    def accept_join(self, owner, key, fingerprint, sealed_payload, *, meeting=None):
        self.validate_key(owner, key, fingerprint, sealed_payload)
        with self.transaction() as db:
            replay = self.replay(db, owner, "POST", "/v1/bots", key, fingerprint)
            if replay:
                return replay, True
            if db.execute("SELECT 1 FROM sessions WHERE reserves=1").fetchone():
                raise StoreError("CAPACITY_EXHAUSTED")
            bot_id = str(uuid.uuid4())
            db.execute("INSERT INTO sessions VALUES (?,?,'accepted',1,?)", (bot_id, owner, time.time()))
            safe = {key: value for key, value in (meeting or {}).items() if key in {"number", "participant_name"}}
            db.execute("INSERT INTO session_details VALUES (?,?)", (bot_id, json.dumps(safe)))
            return self.record(db, owner, "POST", "/v1/bots", key, fingerprint, bot_id, "join", sealed_payload), False

    def accept_control(self, owner, bot_id, command, key, fingerprint, sealed_payload, *, playback_id=None, media=None):
        self.validate_key(owner, key, fingerprint, sealed_payload)
        if command not in {"play", "pause", "resume", "stop", "leave"}:
            raise StoreError("INVALID_COMMAND")
        method = "DELETE" if command == "leave" else "POST"
        route = f"/v1/bots/{bot_id}" + ("" if command == "leave" else f"/{command}")
        with self.transaction() as db:
            replay = self.replay(db, owner, method, route, key, fingerprint)
            if replay:
                return replay, True
            session = db.execute("SELECT * FROM sessions WHERE id=? AND owner=?", (bot_id, owner)).fetchone()
            if not session:
                raise StoreError("BOT_NOT_FOUND")
            if not session["reserves"] and command == "leave":
                response = self.record(db, owner, method, route, key, fingerprint, bot_id, command, sealed_payload)
                response.update(status="succeeded", no_op=True)
                db.execute("UPDATE operations SET status='succeeded',payload=NULL WHERE id=?", (response["operation_id"],))
                db.execute("UPDATE operation_details SET completed=?,result=? WHERE operation_id=?",
                           (time.time(), json.dumps({"no_op": True}), response["operation_id"]))
                db.execute("UPDATE idempotency SET response=? WHERE owner=? AND method=? AND route=? AND key=?",
                           (json.dumps(response), owner, method, route, key))
                self.event(db, bot_id, command, "succeeded", {"operation_id": response["operation_id"], "no_op": True})
                return response, False
            if session["state"] == "reconnecting" and command not in {"leave", "stop"}:
                raise StoreError("PLAYBACK_BLOCKED")
            if not session["reserves"] or (command != "leave" and session["state"] not in ({"active", "reconnecting"} if command == "stop" else {"active"})):
                raise StoreError("BOT_NOT_ACTIVE")
            if command != "leave" and db.execute("SELECT 1 FROM reconciling WHERE bot_id=?", (bot_id,)).fetchone():
                raise StoreError("STATE_RECONCILING")
            if command == "play":
                snapshot = db.execute("SELECT body FROM snapshots WHERE bot_id=?", (bot_id,)).fetchone()
                if snapshot and json.loads(snapshot["body"]).get("playback_state") in {"playing", "paused", "waiting", "buffering"}:
                    raise StoreError("PLAYBACK_ALREADY_ACTIVE")
            pending = db.execute("SELECT * FROM operations WHERE bot_id=? AND status IN ('queued','running')", (bot_id,)).fetchall()
            if pending:
                if command == "leave" and any(row["command"] == "leave" for row in pending):
                    existing = next(row for row in pending if row["command"] == "leave")
                    response = {"bot_id": bot_id, "operation_id": existing["id"], "status": "queued"}
                    db.execute("INSERT INTO idempotency VALUES (?,?,?,?,?,?,?,?)", (owner, method, route, key,
                        fingerprint, bot_id, json.dumps(response), time.time() + 86400))
                    return response, False
                allowed = command == "leave" or (command == "stop" and all(row["command"] == "play" for row in pending))
                if not allowed:
                    raise StoreError("OPERATION_IN_PROGRESS")
            current = db.execute("""SELECT d.playback_id FROM operation_details d JOIN operations o ON o.id=d.operation_id
                WHERE o.bot_id=? AND o.command='play' ORDER BY o.created DESC,o.id DESC LIMIT 1""", (bot_id,)).fetchone()
            captured = current["playback_id"] if current else None
            if command != "play" and playback_id is not None and playback_id != captured:
                raise StoreError("PLAYBACK_ID_MISMATCH")
            if command in {"pause", "resume"}:
                snapshot = db.execute("SELECT body FROM snapshots WHERE bot_id=?", (bot_id,)).fetchone()
                state = json.loads(snapshot["body"]) if snapshot else {}
                if state.get("meeting_status") == 5:
                    raise StoreError("PLAYBACK_BLOCKED")
                if command == "resume" and any(reason != "user" for reason in state.get("pause_reasons", [])):
                    raise StoreError("PLAYBACK_BLOCKED")
                if state.get("playback_id") != captured or state.get("playback_state") not in {"playing", "paused"}:
                    raise StoreError("INVALID_STATE")
            for row in pending:
                reason = "CANCELLED_BY_LEAVE" if command == "leave" else "CANCELLED_BY_STOP"
                if row["status"] == "running":
                    db.execute("INSERT OR REPLACE INTO cancellations VALUES (?,?)", (row["id"], reason))
                else:
                    db.execute("UPDATE operations SET status='cancelled',payload=NULL,error=? WHERE id=?", (reason, row["id"]))
                    db.execute("UPDATE operation_details SET completed=? WHERE operation_id=?", (time.time(), row["id"]))
                    self.event(db, bot_id, row["command"], "cancelled", {"operation_id": row["id"], "reason": reason})
            if command == "leave":
                db.execute("UPDATE sessions SET state='leaving' WHERE id=?", (bot_id,))
            if command == "play":
                captured = str(uuid.uuid4())
            safe_media = {key: value for key, value in (media or {}).items() if key in {"type", "audio_enabled", "duration_seconds"}}
            response = self.record(db, owner, method, route, key, fingerprint, bot_id, command, sealed_payload,
                                   playback_id=captured, metadata=safe_media)
            if command in {"pause", "resume"} and not pending:
                expected = "paused" if command == "pause" else "playing"
                if state.get("playback_state") == expected:
                    response.update(status="succeeded", no_op=True)
                    result = {"no_op": True, "playback_id": captured, "playback_status": expected,
                              "position_seconds": state.get("position_seconds")}
                    db.execute("UPDATE operations SET status='succeeded',payload=NULL WHERE id=?", (response["operation_id"],))
                    db.execute("UPDATE operation_details SET completed=?,result=? WHERE operation_id=?",
                               (time.time(), json.dumps(result), response["operation_id"]))
                    db.execute("UPDATE idempotency SET response=? WHERE owner=? AND method=? AND route=? AND key=?",
                               (json.dumps(response), owner, method, route, key))
                    self.event(db, bot_id, command, "succeeded", dict(result, operation_id=response["operation_id"]))
            return response, False

    def claim(self, worker_id):
        if not worker_id:
            raise StoreError("WORKER_ID_REQUIRED")
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM operations WHERE status='running'").fetchone():
                return None
            row = db.execute("""SELECT o.*,s.owner,d.playback_id FROM operations o JOIN sessions s ON s.id=o.bot_id
                              LEFT JOIN operation_details d ON d.operation_id=o.id WHERE o.status='queued'
                              ORDER BY CASE o.command WHEN 'leave' THEN 0 WHEN 'stop' THEN 1 ELSE 2 END,o.created,o.id LIMIT 1""").fetchone()
            if not row:
                return None
            db.execute("UPDATE operations SET status='running',claimed_by=?,payload=NULL WHERE id=?", (worker_id, row["id"]))
            db.execute("UPDATE operation_details SET started=? WHERE operation_id=?", (time.time(), row["id"]))
            if row["command"] == "join":
                db.execute("UPDATE sessions SET state='preparing' WHERE id=? AND state='accepted'", (row["bot_id"],))
            return dict(row, status="running", claimed_by=worker_id)

    def finish(self, operation_id, worker_id, *, succeeded, session_state=None, error=None, cleanup_confirmed=False, cancelled=False, result=None):
        if session_state is not None and session_state not in {"active", "waiting_room", "leaving", "ended", "failed"}:
            raise StoreError("INVALID_STATE")
        if error is not None and not re.fullmatch(r"[A-Z_]{1,80}", error):
            raise StoreError("INVALID_ERROR_CODE")
        with self.transaction() as db:
            operation = db.execute("SELECT * FROM operations WHERE id=? AND status='running' AND claimed_by=?", (operation_id, worker_id)).fetchone()
            if not operation:
                raise StoreError("CLAIM_LOST")
            if cleanup_confirmed and session_state not in {"ended", "failed"}:
                raise StoreError("CLEANUP_REQUIRES_TERMINAL_STATE")
            status = "cancelled" if cancelled else ("succeeded" if succeeded else "failed")
            db.execute("UPDATE operations SET status=?,payload=NULL,error=? WHERE id=?", (status, error, operation_id))
            db.execute("UPDATE operation_details SET completed=?,result=? WHERE operation_id=?",
                       (time.time(), json.dumps(result) if result is not None else None, operation_id))
            if session_state:
                db.execute("""UPDATE sessions SET state=CASE WHEN state='leaving' AND ?='active' THEN state ELSE ? END
                    WHERE id=?""", (session_state, session_state, operation["bot_id"]))
            if cleanup_confirmed:
                db.execute("UPDATE sessions SET reserves=0 WHERE id=?", (operation["bot_id"],))
                db.execute("DELETE FROM reconciling WHERE bot_id=?", (operation["bot_id"],))
            detail = db.execute("SELECT playback_id FROM operation_details WHERE operation_id=?", (operation_id,)).fetchone()
            self.event(db, operation["bot_id"], operation["command"], status,
                       dict(result or {}, operation_id=operation_id, playback_id=detail["playback_id"] if detail else None, reason=error))

    def session(self, bot_id, owner):
        with self.connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND owner=?", (bot_id, owner)).fetchone()
            if not row:
                raise StoreError("BOT_NOT_FOUND")
            return dict(row)

    def operation(self, operation_id, owner):
        with self.connection() as db:
            row = db.execute("""SELECT o.id,o.bot_id,o.command,o.status,o.error,o.created,d.playback_id,d.started,d.completed,d.result FROM operations o
                                JOIN sessions s ON s.id=o.bot_id LEFT JOIN operation_details d ON d.operation_id=o.id
                                WHERE o.id=? AND s.owner=?""", (operation_id, owner)).fetchone()
            if not row:
                raise StoreError("OPERATION_NOT_FOUND")
            return dict(row)

    def cancellation_reason(self, operation_id):
        with self.connection() as db:
            row = db.execute("SELECT reason FROM cancellations WHERE operation_id=?", (operation_id,)).fetchone()
            return row["reason"] if row else None

    def playback_not_started(self, playback_id):
        with self.connection() as db:
            row = db.execute("""SELECT o.status,d.result FROM operations o JOIN operation_details d ON d.operation_id=o.id
                WHERE o.command='play' AND d.playback_id=?""", (playback_id,)).fetchone()
            return bool(row and row["status"] in {"failed", "cancelled"} and row["result"] is None)

    def media_metadata(self, operation_id, metadata):
        with self.transaction() as db:
            row = db.execute("SELECT metadata FROM operation_details WHERE operation_id=?", (operation_id,)).fetchone()
            value = json.loads(row["metadata"])
            value["downloaded_bytes"] = metadata.get("bytes")
            value["media_id"] = metadata.get("sha256")
            source = metadata.get("media", {})
            value["source"] = {key: source.get(key) for key in {"width", "height", "fps", "video_codec", "audio_codec", "duration_seconds"}}
            db.execute("UPDATE operation_details SET metadata=? WHERE operation_id=?", (json.dumps(value), operation_id))

    def events(self, bot_id, owner, after=0, limit=100):
        self.session(bot_id, owner)
        with self.connection() as db:
            return [dict(row) for row in db.execute("""SELECT e.*,d.body AS data FROM events e LEFT JOIN event_details d ON d.sequence=e.sequence
                WHERE bot_id=? AND e.sequence>? ORDER BY e.sequence LIMIT ?""", (bot_id, after, min(max(limit, 1), 201)))]

    def rate_limit(self, owner, mutation):
        now = time.time()
        with self.transaction() as db:
            db.execute("DELETE FROM rate_events WHERE created<?", (now - 60,))
            row = db.execute("""SELECT COUNT(*) AS total,COALESCE(SUM(mutation),0) AS mutations,
                COALESCE(SUM(CASE WHEN mutation=1 AND created>? THEN 1 ELSE 0 END),0) AS burst
                FROM rate_events WHERE owner=?""", (now - 1, owner)).fetchone()
            if row["total"] >= 60 or (mutation and (row["mutations"] >= 10 or row["burst"] >= 5)):
                raise StoreError("RATE_LIMITED")
            db.execute("INSERT INTO rate_events VALUES (?,?,?)", (owner, now, int(mutation)))

    def public_data(self, bot_id, owner):
        session = self.session(bot_id, owner)
        with self.connection() as db:
            details = db.execute("SELECT metadata FROM session_details WHERE bot_id=?", (bot_id,)).fetchone()
            snapshot = db.execute("SELECT body,updated FROM snapshots WHERE bot_id=?", (bot_id,)).fetchone()
            latest = db.execute("""SELECT o.status,o.error,o.created,d.* FROM operations o JOIN operation_details d ON d.operation_id=o.id
                WHERE o.bot_id=? AND o.command='play' ORDER BY o.created DESC,o.id DESC LIMIT 1""", (bot_id,)).fetchone()
            pending = db.execute("SELECT id,command,status FROM operations WHERE bot_id=? AND status IN ('queued','running') ORDER BY created LIMIT 1", (bot_id,)).fetchone()
            last_error = db.execute("SELECT error FROM operations WHERE bot_id=? AND error IS NOT NULL ORDER BY created DESC LIMIT 1", (bot_id,)).fetchone()
            supervisor_error = db.execute("SELECT kind FROM events WHERE bot_id=? AND state='failed' ORDER BY sequence DESC LIMIT 1", (bot_id,)).fetchone()
            event = db.execute("SELECT COALESCE(MAX(sequence),0) AS version,MAX(created) AS updated FROM events WHERE bot_id=?", (bot_id,)).fetchone()
        return {"session": session, "meeting": json.loads(details["metadata"]) if details else {},
                "snapshot": json.loads(snapshot["body"]) if snapshot else {}, "snapshot_updated": snapshot["updated"] if snapshot else None,
                "play": dict(latest) if latest else None, "pending": dict(pending) if pending else None,
                "last_error": (supervisor_error["kind"] if supervisor_error and re.fullmatch(r"[A-Z_]{1,80}", supervisor_error["kind"])
                               else last_error["error"] if last_error else None), "version": event["version"],
                "updated": event["updated"] or session["created"]}

    def list_sessions(self, owner, limit, status=None, before=None):
        query = "SELECT id,state,created FROM sessions WHERE owner=?"
        values = [owner]
        if status is not None:
            query += " AND state=?"
            values.append(status)
        if before is not None:
            query += " AND (created<? OR (created=? AND id<?))"
            values.extend([before[0], before[0], before[1]])
        query += " ORDER BY created DESC,id DESC LIMIT ?"
        values.append(limit)
        with self.connection() as db:
            return [dict(row) for row in db.execute(query, values)]

    def capacity(self):
        with self.connection() as db:
            occupied = db.execute("SELECT COUNT(*) FROM sessions WHERE reserves=1").fetchone()[0]
            return {"limit": 1, "occupied": occupied, "available": 1 - occupied}

    def prune_history(self, *, retention_seconds=30 * 86400, now=None):
        """Bounded transaction; never delete capacity, unfinished work or live replay keys."""
        now = time.time() if now is None else now
        cutoff = now - retention_seconds
        with self.transaction() as db:
            rows = db.execute("""SELECT s.id FROM sessions s WHERE s.reserves=0 AND s.state IN ('ended','failed')
                AND s.created<? AND NOT EXISTS (SELECT 1 FROM operations o LEFT JOIN operation_details d ON d.operation_id=o.id
                    WHERE o.bot_id=s.id AND (o.status IN ('queued','running') OR COALESCE(d.completed,o.created)>=?))
                AND NOT EXISTS (SELECT 1 FROM events e WHERE e.bot_id=s.id AND e.created>=?)
                AND NOT EXISTS (SELECT 1 FROM idempotency i WHERE i.bot_id=s.id AND i.expires>?) LIMIT 25""",
                (cutoff, cutoff, cutoff, now)).fetchall()
            for row in rows:
                bot = row['id']
                db.execute("DELETE FROM cancellations WHERE operation_id IN (SELECT id FROM operations WHERE bot_id=?)", (bot,))
                db.execute("DELETE FROM operation_details WHERE operation_id IN (SELECT id FROM operations WHERE bot_id=?)", (bot,))
                db.execute("DELETE FROM event_details WHERE sequence IN (SELECT sequence FROM events WHERE bot_id=?)", (bot,))
                for table in ('idempotency', 'events', 'session_details', 'session_limits', 'snapshots', 'reconciling', 'operations'):
                    db.execute(f"DELETE FROM {table} WHERE bot_id=?", (bot,))
                db.execute("DELETE FROM sessions WHERE id=?", (bot,))
            return len(rows)

    def reconcile_restart(self, *, cleanup_confirmed=False):
        """Called by the supervisor after inspecting old processes; never auto-rejoin."""
        with self.transaction() as db:
            sessions = db.execute("SELECT id FROM sessions WHERE reserves=1").fetchall()
            for session in sessions:
                db.execute("UPDATE sessions SET state='failed',reserves=? WHERE id=?", (0 if cleanup_confirmed else 1, session["id"]))
                db.execute("""UPDATE operations SET status='cancelled',error='WORKER_RESTARTED',payload=NULL
                              WHERE bot_id=? AND status IN ('queued','running')""", (session["id"],))
                db.execute("""UPDATE operation_details SET completed=COALESCE(completed,?) WHERE operation_id IN
                    (SELECT id FROM operations WHERE bot_id=? AND status='cancelled')""", (time.time(), session["id"]))
                db.execute("INSERT INTO events(bot_id,kind,state,created) VALUES (?,'worker_restart','failed',?)", (session["id"], time.time()))
            if cleanup_confirmed:
                db.execute("DELETE FROM reconciling")
            return len(sessions)

    def heartbeat(self, worker_id, *, ready=True):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO worker_health VALUES (1,?,?,?)", (worker_id, time.time(), int(ready)))

    def health(self, stale_after=15):
        with self.connection() as db:
            row = db.execute("SELECT * FROM worker_health WHERE singleton=1").fetchone()
            if not row:
                return {"ready": False, "heartbeat_age_seconds": None}
            age = max(0, time.time() - row["updated"])
            reconciling = db.execute("SELECT 1 FROM reconciling LIMIT 1").fetchone()
            return {"ready": bool(row["ready"]) and age <= stale_after and not reconciling, "heartbeat_age_seconds": age}

    def mark_reconciling(self, bot_id):
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO reconciling VALUES (?)", (bot_id,))

    def set_deadline(self, bot_id, maximum):
        with self.transaction() as db:
            row = db.execute("SELECT created FROM sessions WHERE id=?", (bot_id,)).fetchone()
            if not row:
                raise StoreError("BOT_NOT_FOUND")
            db.execute("INSERT OR REPLACE INTO session_limits VALUES (?,?)", (bot_id, row["created"] + maximum))
            return row["created"] + maximum

    def reserved_sessions(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("""SELECT s.*,l.deadline FROM sessions s
                LEFT JOIN session_limits l ON l.bot_id=s.id WHERE s.reserves=1""")]

    def snapshot(self, bot_id, state):
        allowed = {"playback_id", "playback_state", "position_seconds", "video_frames_sent",
                   "audio_blocks_sent", "meeting_status", "in_meeting", "shutdown_requested", "pause_reasons"}
        safe = {key: value for key, value in state.items() if key in allowed}
        body = json.dumps(safe, allow_nan=False)
        with self.transaction() as db:
            old = db.execute("SELECT body FROM snapshots WHERE bot_id=?", (bot_id,)).fetchone()
            previous = json.loads(old["body"]) if old else {}
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (bot_id, body, time.time()))
            db.execute("DELETE FROM reconciling WHERE bot_id=?", (bot_id,))
            if safe.get("playback_id") and (safe.get("playback_state"), safe.get("playback_id"), safe.get("pause_reasons")) != (previous.get("playback_state"), previous.get("playback_id"), previous.get("pause_reasons")):
                self.event(db, bot_id, "playback", safe.get("playback_state", "idle"), safe)
            if safe.get("meeting_status") != previous.get("meeting_status"):
                statuses = {0: "idle", 1: "joining", 2: "waiting_room", 3: "joined", 4: "leaving", 5: "reconnecting", 6: "failed", 7: "ended", 11: "waiting_room"}
                self.event(db, bot_id, "meeting", statuses.get(safe.get("meeting_status"), "unknown"))
            phase = {1: "joining", 2: "waiting_room", 11: "waiting_room", 3: "active", 5: "reconnecting"}.get(safe.get("meeting_status"))
            if phase:
                db.execute("""UPDATE sessions SET state=? WHERE id=? AND reserves=1
                    AND state IN ('accepted','preparing','joining','waiting_room','active','reconnecting')""", (phase, bot_id))

    def end_session(self, bot_id, error, *, cleanup_confirmed):
        if not re.fullmatch(r"[A-Z_]{1,80}", error):
            raise StoreError("INVALID_ERROR_CODE")
        with self.transaction() as db:
            row = db.execute("SELECT reserves,state FROM sessions WHERE id=?", (bot_id,)).fetchone()
            if not row or not row["reserves"]:
                return
            if row["state"] == "failed" and not cleanup_confirmed:
                return  # Keep the reservation without flooding identical failure events.
            db.execute("UPDATE sessions SET state='failed',reserves=? WHERE id=?", (0 if cleanup_confirmed else 1, bot_id))
            if cleanup_confirmed:
                db.execute("DELETE FROM reconciling WHERE bot_id=?", (bot_id,))
            db.execute("""UPDATE operations SET status='cancelled',error=?,payload=NULL
                WHERE bot_id=? AND status IN ('queued','running')""", (error, bot_id))
            db.execute("""UPDATE operation_details SET completed=COALESCE(completed,?) WHERE operation_id IN
                (SELECT id FROM operations WHERE bot_id=? AND status='cancelled')""", (time.time(), bot_id))
            db.execute("INSERT INTO events(bot_id,kind,state,created) VALUES (?,?,?,?)", (bot_id, error, "failed", time.time()))
