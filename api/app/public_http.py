"""Cloud Run IAM authenticates invocations; ownership is server configuration."""
from contextlib import asynccontextmanager
import os
from .http_common import create_http_app, ApiError
from .proxy import ProxyBackend
from .secrets import SecretReader


def create_proxy_app(backend, *, lifespan=None):
    async def cloud_run_iam(request):
        # Google validates IAM before the container; do not trust a caller-supplied owner header
        # or decode a signature-stripped token as if it were an application credential.
        return None
    return create_http_app(backend, cloud_run_iam, lifespan=lifespan)


def app_factory():
    if not os.environ.get("K_SERVICE") or not os.environ.get("ZOOM_API_OWNER"):
        raise ApiError("CLOUD_RUN_IAM_REQUIRED", 503)
    @asynccontextmanager
    async def lifespan(app):
        token = SecretReader().token(os.environ.get("ZOOM_AGENT_TOKEN_VERSION"))
        backend = ProxyBackend(os.environ.get("ZOOM_AGENT_URL", ""), token, os.environ["ZOOM_API_OWNER"])
        app.state.backend = backend
        try:
            yield
        finally:
            await backend.close()
    return create_proxy_app(None, lifespan=lifespan)
