"""Private agent HTTP; separate bearer credential and fixed allowed consumer."""
from contextlib import asynccontextmanager
import hmac
import json
import os
import threading
from .agent_backend import AgentBackend
from .http_common import create_http_app, ApiError
from .secrets import SecretReader, validate_version
from .service import AgentService


def create_agent_app(agent, token, owner, *, lifespan=None, enforce_limits=True):
    if not token or not owner:
        raise ApiError("INVALID_AGENT_CONFIGURATION", 503)
    async def authenticate(request):
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            raise ApiError("UNAUTHORIZED", 401)
        if request.headers.get("x-bot-owner") != owner:
            raise ApiError("FORBIDDEN", 403)
    backend = AgentBackend(agent, owner, enforce_limits=enforce_limits) if agent is not None else None
    return create_http_app(backend, authenticate, lifespan=lifespan, title="Zoom bot private agent")


def app_factory():
    owner = os.environ.get("ZOOM_API_OWNER")
    if not owner:
        raise ApiError("INVALID_AGENT_CONFIGURATION", 503)
    validate_version(os.environ.get("ZOOM_AGENT_TOKEN_VERSION"))
    token = SecretReader().token(os.environ.get("ZOOM_AGENT_TOKEN_VERSION"))
    @asynccontextmanager
    async def lifespan(app):
        service = AgentService(os.environ.get("ZOOM_STATE_ROOT", "/state"), os.environ.get("ZOOM_SDK_SECRET_VERSION"),
                               os.environ.get("ZOOM_MASTER_KEY_VERSION"))
        app.state.backend = AgentBackend(service.agent, owner)
        def worker():
            try:
                service.run()
            except Exception:
                print(json.dumps({"event": "agent.worker_failed", "error": "AGENT_SERVICE_FAILED"}), flush=True)
        thread = threading.Thread(target=worker, name="agent-worker")
        thread.start()
        try:
            yield
        finally:
            service.agent.stopping.set()
            # Download reads and native cleanup have bounded timeouts. Deployment stop grace >=75 s.
            thread.join(timeout=70)
            if thread.is_alive():
                # Do not close the owner lock or guess cleanup while a worker is still using it.
                raise RuntimeError("AGENT_SHUTDOWN_UNCONFIRMED")
    return create_agent_app(None, token, owner, lifespan=lifespan)
