"""Stateless proxy; a timeout is unknown, not proof that a job was not accepted."""
from urllib.parse import urlsplit
import httpx
from .http_common import ApiError


class ProxyBackend:
    def __init__(self, url, token, owner, *, client=None):
        parsed = urlsplit(url)
        # Private address is deployment configuration, never a user-provided media URL.
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ApiError("INVALID_AGENT_CONFIGURATION", 503)
        self.url, self.token, self.owner = url.rstrip("/"), token, owner
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3), follow_redirects=False, trust_env=False)

    async def request(self, method, path, *, body=None, key=None, request_id=None, params=None):
        headers = {"Authorization": "Bearer " + self.token, "X-Bot-Owner": self.owner, "X-Request-ID": request_id}
        if key:
            headers["Idempotency-Key"] = key
        try:
            response = await self.client.request(method, self.url + path, headers=headers,
                json=body if method == "POST" else None,
                params={key: value for key, value in (params or {}).items() if value is not None})
            if len(response.content) > 1024 * 1024 or response.status_code not in {200, 202, 400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503}:
                raise ValueError()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            if response.status_code in {401, 403}:
                raise ValueError()  # Internal credential/configuration failure is not caller authentication.
        except (httpx.HTTPError, ValueError):
            # No retry with a new operation/key, and no fabricated 202.
            raise ApiError("WORKER_UNAVAILABLE", 503) from None
        selected = {key: response.headers[key] for key in ("Idempotency-Replayed", "Retry-After", "Location") if key in response.headers}
        return response.status_code, value, selected

    async def close(self):
        await self.client.aclose()
