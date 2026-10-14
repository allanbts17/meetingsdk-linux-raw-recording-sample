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
        if not owner or not 16 <= len(key) <= 128 or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
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

    def record(self, db, owner, method, route, key, fingerprint, bot_id, command, payload):
        operation_id = str(uuid.uuid4())
        now = time.time()
        db.execute("INSERT INTO operations VALUES (?,?,?,'queued',?,NULL,NULL,?)", (operation_id, bot_id, command, payload, now))
        response = {"bot_id": bot_id, "operation_id": operation_id, "status": "queued"}
        db.execute("INSERT INTO idempotency VALUES (?,?,?,?,?,?,?,?)",
                   (owner, method, route, key, fingerprint, bot_id, json.dumps(response), now + 86400))
        db.execute("INSERT INTO events(bot_id,kind,state,created) VALUES (?,?,?,?)", (bot_id, command, "queued", now))
        return response

    def accept_join(self, owner, key, fingerprint, sealed_payload):
        self.validate_key(owner, key, fingerprint, sealed_payload)
        with self.transaction() as db:
            replay = self.replay(db, owner, "POST", "/v1/bots", key, fingerprint)
            if replay:
                return replay, True
            if db.execute("SELECT 1 FROM sessions WHERE reserves=1").fetchone():
                raise StoreError("CAPACITY_EXHAUSTED")
            bot_id = str(uuid.uuid4())
            db.execute("INSERT INTO sessions VALUES (?,?,'accepted',1,?)", (bot_id, owner, time.time()))
            return self.record(db, owner, "POST", "/v1/bots", key, fingerprint, bot_id, "join", sealed_payload), False

    def accept_control(self, owner, bot_id, command, key, fingerprint, sealed_payload):
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
            if not session["reserves"] or (command != "leave" and session["state"] != "active"):
                raise StoreError("BOT_NOT_ACTIVE")
            if db.execute("SELECT 1 FROM operations WHERE bot_id=? AND status IN ('queued','running')", (bot_id,)).fetchone():
                raise StoreError("OPERATION_IN_PROGRESS")
            return self.record(db, owner, method, route, key, fingerprint, bot_id, command, sealed_payload), False

    def claim(self, worker_id):
        if not worker_id:
            raise StoreError("WORKER_ID_REQUIRED")
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM operations WHERE status='running'").fetchone():
                return None
            row = db.execute("""SELECT o.*,s.owner FROM operations o JOIN sessions s ON s.id=o.bot_id
                              WHERE o.status='queued' ORDER BY o.created,o.id LIMIT 1""").fetchone()
            if not row:
                return None
            db.execute("UPDATE operations SET status='running',claimed_by=? WHERE id=?", (worker_id, row["id"]))
            return dict(row, status="running", claimed_by=worker_id)

    def finish(self, operation_id, worker_id, *, succeeded, session_state=None, error=None, cleanup_confirmed=False):
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
            status = "succeeded" if succeeded else "failed"
            db.execute("UPDATE operations SET status=?,payload=NULL,error=? WHERE id=?", (status, error, operation_id))
            if session_state:
                db.execute("UPDATE sessions SET state=? WHERE id=?", (session_state, operation["bot_id"]))
            if cleanup_confirmed:
                db.execute("UPDATE sessions SET reserves=0 WHERE id=?", (operation["bot_id"],))
            db.execute("INSERT INTO events(bot_id,kind,state,created) VALUES (?,?,?,?)", (operation["bot_id"], operation["command"], status, time.time()))

    def session(self, bot_id, owner):
        with self.connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND owner=?", (bot_id, owner)).fetchone()
            if not row:
                raise StoreError("BOT_NOT_FOUND")
            return dict(row)

    def operation(self, operation_id, owner):
        with self.connection() as db:
            row = db.execute("""SELECT o.id,o.bot_id,o.command,o.status,o.error,o.created FROM operations o
                                JOIN sessions s ON s.id=o.bot_id WHERE o.id=? AND s.owner=?""", (operation_id, owner)).fetchone()
            if not row:
                raise StoreError("OPERATION_NOT_FOUND")
            return dict(row)

    def events(self, bot_id, owner, after=0, limit=100):
        self.session(bot_id, owner)
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events WHERE bot_id=? AND sequence>? ORDER BY sequence LIMIT ?", (bot_id, after, min(max(limit, 1), 100)))]

    def capacity(self):
        with self.connection() as db:
            occupied = db.execute("SELECT COUNT(*) FROM sessions WHERE reserves=1").fetchone()[0]
            return {"limit": 1, "occupied": occupied, "available": 1 - occupied}

    def reconcile_restart(self, *, cleanup_confirmed=False):
        """Called by the supervisor after inspecting old processes; never auto-rejoin."""
        with self.transaction() as db:
            sessions = db.execute("SELECT id FROM sessions WHERE reserves=1").fetchall()
            for session in sessions:
                db.execute("UPDATE sessions SET state='failed',reserves=? WHERE id=?", (0 if cleanup_confirmed else 1, session["id"]))
                db.execute("""UPDATE operations SET status='cancelled',error='WORKER_RESTARTED',payload=NULL
                              WHERE bot_id=? AND status IN ('queued','running')""", (session["id"],))
                db.execute("INSERT INTO events(bot_id,kind,state,created) VALUES (?,'worker_restart','failed',?)", (session["id"], time.time()))
            return len(sessions)
