import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import httpx
from fastapi.testclient import TestClient
from app.agent import Agent
from app.payloads import PayloadCipher
from app.store import Store
from app.private_http import create_agent_app
from app.public_http import create_proxy_app
from app.proxy import ProxyBackend
from test_agent import FakeRuntime


URL = "https://storage.googleapis.com/zoom-app-dev.firebasestorage.app/videos/test.mp4"


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zb-")
        self.store = Store(Path(self.temp.name) / "state.db")
        self.runtime = FakeRuntime()
        self.agent = Agent(self.store, PayloadCipher(bytes(range(32))), self.runtime, lambda media: "/tmp/test.mp4", operation_timeout=1)
        self.store.heartbeat(self.agent.worker_id)
        self.owner, self.token = "test-backend", "private-test-token"
        self.private = create_agent_app(self.agent, self.token, self.owner, enforce_limits=False)
        self.transport = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.private), base_url="http://agent")
        self.backend = ProxyBackend("http://agent", self.token, self.owner, client=self.transport)
        # The public factory relies on Cloud Run IAM; this in-memory app tests its proxy contract.
        self.client = TestClient(create_proxy_app(self.backend))

    def tearDown(self):
        self.client.close()
        asyncio.run(self.transport.aclose())
        self.temp.cleanup()

    def mutate(self, method, path, body=None, key=None):
        return self.client.request(method, path, json=body if method == "POST" else None,
                                   headers={"Idempotency-Key": key or str(uuid.uuid4())})

    def join(self):
        calls_before = list(self.runtime.calls)
        response = self.mutate("POST", "/v1/bots", {"meeting": {"number": "123456789", "password": "private-password"}})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.runtime.calls, calls_before)
        self.agent.run_once()
        return response.json()["bot_id"]

    def test_full_http_flow_video_audio_image_controls_and_leave(self):
        bot = self.join()
        for index, kind in enumerate(("video", "audio", "image")):
            response = self.mutate("POST", f"/v1/bots/{bot}/play", {"media": {"type": kind, "url": URL}})
            self.assertEqual(response.status_code, 202, response.text)
            playback_id = response.json()["playback_id"]
            self.agent.run_once()
            operation = self.client.get(response.json()["links"]["operation"]).json()
            self.assertEqual(operation["status"], "succeeded")
            self.assertEqual(operation["playback_id"], playback_id)
            for command in ("pause", "resume", "stop"):
                action = self.mutate("POST", f"/v1/bots/{bot}/{command}", {"playback_id": playback_id})
                self.assertEqual(action.status_code, 202, action.text)
                self.agent.run_once()
                self.assertEqual(self.client.get(action.json()["links"]["operation"]).json()["status"], "succeeded")
            self.assertEqual(self.client.get(f"/v1/bots/{bot}").json()["status"], "active")
        response = self.mutate("DELETE", f"/v1/bots/{bot}")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get("/v1/capacity").json()["available_slots"], 0)
        self.agent.run_once()
        self.assertTrue(self.client.get(f"/v1/bots/{bot}").json()["resource_released"])
        self.assertEqual(self.client.get("/v1/capacity").json()["available_slots"], 1)

    def test_api_instance_restart_replays_same_durable_operation(self):
        body, key = {"meeting": {"number": "123456789"}}, str(uuid.uuid4())
        first = self.mutate("POST", "/v1/bots", body, key)
        other = TestClient(create_proxy_app(self.backend))
        try:
            repeated = other.post("/v1/bots", json=body, headers={"Idempotency-Key": key})
            self.assertEqual(first.json(), repeated.json())
            self.assertEqual(repeated.headers["Idempotency-Replayed"], "true")
            self.assertEqual(self.store.capacity()["occupied"], 1)
        finally:
            other.close()

    def test_external_pause_blocks_resume_and_preserves_manual_pause(self):
        bot = self.join()
        play = self.mutate("POST", f"/v1/bots/{bot}/play", {"media": {"type": "video", "url": URL}})
        self.agent.run_once()
        state = self.runtime.status(bot)
        state.update(playback_state="paused", pause_reasons=["audio_unavailable", "user"])
        self.store.snapshot(bot, state)
        view = self.client.get(f"/v1/bots/{bot}").json()["playback"]
        self.assertEqual(view["pause_reasons"], ["audio_unavailable", "user"])
        self.assertFalse(view["can_resume"])
        response = self.mutate("POST", f"/v1/bots/{bot}/resume")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "PLAYBACK_BLOCKED")
        state.update(pause_reasons=["user"])
        self.store.snapshot(bot, state)
        view = self.client.get(f"/v1/bots/{bot}").json()["playback"]
        self.assertEqual(view["status"], "paused")
        self.assertTrue(view["can_resume"])
        self.assertEqual(self.client.get(play.json()["links"]["operation"]).json()["status"], "succeeded")

    def test_validation_discrimination_and_secret_redaction(self):
        secret = "private-value-never-return"
        for body in ({"meeting": {"number": secret}}, {"meeting": {"number": "123456789", "password": secret}, "secret": secret}):
            response = self.mutate("POST", "/v1/bots", body)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(secret, response.text)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        bot = self.join()
        for media in ({"type": "audio", "url": URL, "audio_enabled": True}, {"type": "image", "url": URL, "duration_seconds": True},
                      {"type": "video", "url": "http://169.254.169.254/metadata"}):
            self.assertEqual(self.mutate("POST", f"/v1/bots/{bot}/play", {"media": media}).status_code, 422)
        view = self.client.get(f"/v1/bots/{bot}")
        self.assertNotIn("private-password", view.text)
        self.assertNotIn("payload", view.text)

    def test_agent_auth_docs_owner_and_capacity(self):
        with TestClient(self.private) as client:
            self.assertEqual(client.get("/health/live").status_code, 200)
            for path in ("/docs", "/openapi.json", "/v1/capacity", "/health/ready"):
                response = client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
            self.assertEqual(client.get("/v1/capacity", headers={"Authorization": "Bearer " + self.token,
                "X-Bot-Owner": "wrong"}).status_code, 403)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_stale_heartbeat_blocks_join_without_freeing_slot(self):
        self.join()
        self.store.heartbeat("worker", ready=False)
        self.assertEqual(self.client.get("/health/ready").status_code, 503)
        response = self.mutate("POST", "/v1/bots", {"meeting": {"number": "123456789"}})
        self.assertEqual(response.status_code, 503)
        capacity = self.client.get("/v1/capacity").json()
        self.assertEqual(capacity["available_slots"], 0)
        self.assertFalse(capacity["accepting_new_sessions"])

    def test_pagination_events_request_id_and_missing_key(self):
        self.join()
        rows = self.client.get("/v1/bots?limit=1").json()
        self.assertEqual(len(rows["items"]), 1)
        bot = rows["items"][0]["bot_id"]
        events = self.client.get(f"/v1/bots/{bot}/events?limit=1").json()
        self.assertTrue(events["has_more"])
        self.assertGreater(events["next_after_sequence"], 0)
        self.assertEqual(self.client.get("/v1/bots?cursor=invalid").status_code, 422)
        response = self.client.post(f"/v1/bots/{bot}/stop", json={})
        self.assertEqual(response.status_code, 400)
        request_id = str(uuid.uuid4())
        response = self.client.get("/v1/capacity", headers={"X-Request-ID": request_id})
        self.assertEqual(response.headers["X-Request-ID"], request_id)

    def test_limits_content_type_json_and_body_size(self):
        self.assertEqual(self.client.post("/v1/bots", content="not json", headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.client.post("/v1/bots", content="{", headers={"Content-Type": "application/json"}).status_code, 400)
        self.assertEqual(self.client.post("/v1/bots", content="x" * 65537, headers={"Content-Type": "application/json"}).status_code, 413)
        limited = create_agent_app(self.agent, self.token, self.owner, enforce_limits=True)
        with TestClient(limited) as client:
            headers = {"Authorization": "Bearer " + self.token, "X-Bot-Owner": self.owner}
            for _ in range(60):
                self.assertEqual(client.get("/v1/capacity", headers=headers).status_code, 200)
            self.assertEqual(client.get("/v1/capacity", headers=headers).status_code, 429)

    def test_unknown_timeout_never_fabricates_acceptance_or_retries(self):
        calls = []
        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout("private-body-or-token", request=request)
        transport = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        client = TestClient(create_proxy_app(ProxyBackend("http://agent", self.token, self.owner, client=transport)))
        try:
            response = client.post("/v1/bots", json={"meeting": {"number": "123456789"}},
                                   headers={"Idempotency-Key": str(uuid.uuid4())})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("private-body-or-token", response.text)
        finally:
            client.close()
            asyncio.run(transport.aclose())

    def test_repeat_controls_replay_after_state_changes_and_noops(self):
        bot = self.join()
        play = self.mutate("POST", f"/v1/bots/{bot}/play", {"media": {"type": "image", "url": URL}})
        self.agent.run_once()
        key = str(uuid.uuid4())
        first = self.mutate("POST", f"/v1/bots/{bot}/pause", {}, key)
        self.agent.run_once()
        noop = self.mutate("POST", f"/v1/bots/{bot}/pause", {})
        self.assertEqual(noop.status_code, 200)
        self.assertTrue(noop.json()["no_op"])
        stop = self.mutate("POST", f"/v1/bots/{bot}/stop", {})
        self.agent.run_once()
        replay = self.mutate("POST", f"/v1/bots/{bot}/pause", {}, key)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(replay.headers["Idempotency-Replayed"], "true")
        self.assertEqual(self.client.get(f"/v1/bots/{bot}").json()["playback"]["status"], "stopped")

    def test_unexpected_exception_is_redacted_and_not_reraised(self):
        class Backend:
            async def request(self, *args, **kwargs):
                raise RuntimeError("secret-request-password")
        with TestClient(create_proxy_app(Backend())) as client:
            response = client.get("/v1/capacity")
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("secret-request-password", response.text)

    def test_reconciling_rejects_controls_but_allows_cleanup(self):
        bot = self.join()
        self.store.mark_reconciling(bot)
        self.assertEqual(self.client.get("/health/ready").status_code, 503)
        self.assertEqual(self.mutate("POST", f"/v1/bots/{bot}/play", {"media": {"type": "image", "url": URL}}).status_code, 503)
        leave = self.mutate("DELETE", f"/v1/bots/{bot}")
        self.assertEqual(leave.status_code, 202)
        self.agent.run_once()
        self.assertEqual(self.client.get("/health/ready").status_code, 200)

    def test_mutation_rate_burst_and_minute_are_durable(self):
        import time
        from app.store import StoreError
        for _ in range(5):
            self.store.rate_limit(self.owner, True)
        with self.assertRaisesRegex(StoreError, "RATE_LIMITED"):
            self.store.rate_limit(self.owner, True)
        with self.store.transaction() as db:
            db.execute("UPDATE rate_events SET created=?", (time.time() - 2,))
        for _ in range(5):
            self.store.rate_limit(self.owner, True)
        with self.store.transaction() as db:
            db.execute("UPDATE rate_events SET created=?", (time.time() - 2,))
        restarted = Store(self.store.path)
        with self.assertRaisesRegex(StoreError, "RATE_LIMITED"):
            restarted.rate_limit(self.owner, True)
        restarted.rate_limit("another-owner", True)

    def test_list_cursor_is_stable_and_bound_to_filter(self):
        first = self.join()
        self.mutate("DELETE", f"/v1/bots/{first}")
        self.agent.run_once()
        second = self.join()
        page = self.client.get("/v1/bots?limit=1").json()
        self.assertEqual(page["items"][0]["bot_id"], second)
        self.assertIsNotNone(page["next_cursor"])
        next_page = self.client.get("/v1/bots", params={"limit": 1, "cursor": page["next_cursor"]}).json()
        self.assertEqual(next_page["items"][0]["bot_id"], first)
        self.assertIsNone(next_page["next_cursor"])
        self.assertEqual(self.client.get("/v1/bots", params={"cursor": page["next_cursor"], "status": "active"}).status_code, 422)

    def test_invalid_internal_credential_returns_worker_unavailable(self):
        backend = ProxyBackend("http://agent", "invalid-private-token", self.owner, client=self.transport)
        with TestClient(create_proxy_app(backend)) as client:
            response = client.get("/v1/capacity")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "WORKER_UNAVAILABLE")
