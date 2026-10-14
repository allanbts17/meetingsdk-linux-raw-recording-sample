"""HTTP contract shared by private agent and stateless Cloud Run gateway."""
import re
import uuid
from fastapi import FastAPI, Body, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from .models import JoinRequest, PlayRequest, ControlRequest


class ApiError(RuntimeError):
    def __init__(self, code, status=409):
        self.code, self.status = code, status


def failure(code, status, request_id, details=None):
    body = {"error": {"code": code, "message": code.replace("_", " ").lower(), "request_id": request_id}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


class RequestPolicy:
    def __init__(self, app, maximum=65536):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope["headers"]}
        try:
            request_id = str(uuid.UUID(headers.get(b"x-request-id", b"").decode()))
        except (ValueError, UnicodeError):
            request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = False
        async def safe_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [(key, value) for key, value in message.get("headers", [])
                                      if key.lower() not in {b"cache-control", b"x-request-id"}]
                message["headers"].extend([(b"cache-control", b"no-store"), (b"x-request-id", request_id.encode())])
            await send(message)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.maximum:
                return await failure("REQUEST_TOO_LARGE", 413, request_id)(scope, receive, safe_send)
            if not message.get("more_body", False):
                break
        if body and scope["method"] == "DELETE":
            return await failure("UNEXPECTED_BODY", 422, request_id)(scope, receive, safe_send)
        if body and scope["method"] == "POST" and headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower() != b"application/json":
            return await failure("UNSUPPORTED_CONTENT_TYPE", 415, request_id)(scope, receive, safe_send)
        delivered = False
        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        try:
            await self.app(scope, buffered_receive, safe_send)
        except Exception:
            # Starlette may re-raise after its 500 handler. Suppress unfiltered tracebacks.
            if not started:
                await failure("INTERNAL_ERROR", 500, request_id)(scope, buffered_receive, safe_send)


def create_http_app(backend, authenticate, *, lifespan=None, title="Zoom bot API"):
    app = FastAPI(title=title, version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(RequestPolicy)
    app.state.backend = backend
    def schema():
        if app.openapi_schema is None:
            value = get_openapi(title=title, version="1.0.0", routes=app.routes)
            value.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {"type": "http", "scheme": "bearer"}
            value["security"] = [{"BearerAuth": []}]
            value["paths"]["/health/live"]["get"]["security"] = []
            app.openapi_schema = value
        return app.openapi_schema
    app.openapi = schema

    async def authenticated(request: Request):
        return await authenticate(request)

    @app.exception_handler(ApiError)
    async def api_error(request, error):
        response = failure(error.code, error.status, request.state.request_id)
        if error.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if error.status in {429, 503}:
            response.headers["Retry-After"] = "1"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        invalid_json = any(item["type"] == "json_invalid" for item in error.errors())
        # Do not echo input, custom validator context or attacker-provided field names.
        return failure("INVALID_JSON" if invalid_json else "VALIDATION_ERROR", 400 if invalid_json else 422,
                       request.state.request_id)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return failure("NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR", error.status_code, request.state.request_id)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return failure("INTERNAL_ERROR", 500, request.state.request_id)

    async def call(request, method, path, payload=None, key=None, params=None):
        status, body, headers = await request.app.state.backend.request(method, path, body=payload, key=key,
            request_id=request.state.request_id, params=params or {})
        return JSONResponse(body, status_code=status, headers=headers)

    def idempotency(value):
        if value is None:
            raise ApiError("IDEMPOTENCY_KEY_REQUIRED", 400)
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
            raise ApiError("INVALID_IDEMPOTENCY", 422)
        return value

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready", dependencies=[Depends(authenticated)])
    async def ready(request: Request):
        return await call(request, "GET", "/health/ready")

    @app.post("/v1/bots", status_code=202, dependencies=[Depends(authenticated)])
    async def join(request: Request, body: JoinRequest, key: str | None = Header(None, alias="Idempotency-Key")):
        return await call(request, "POST", "/v1/bots", body.model_dump(), idempotency(key))

    @app.get("/v1/bots", dependencies=[Depends(authenticated)])
    async def bots(request: Request, limit: int = Query(20, ge=1, le=100), cursor: str | None = Query(None, max_length=512),
                   status: str | None = Query(None, pattern="^(accepted|preparing|joining|waiting_room|active|reconnecting|leaving|ended|failed)$")):
        return await call(request, "GET", "/v1/bots", params={"limit": limit, "cursor": cursor, "status": status})

    @app.get("/v1/bots/{bot_id}", dependencies=[Depends(authenticated)])
    async def bot(request: Request, bot_id: uuid.UUID):
        return await call(request, "GET", f"/v1/bots/{bot_id}")

    @app.post("/v1/bots/{bot_id}/play", status_code=202, dependencies=[Depends(authenticated)])
    async def play(request: Request, bot_id: uuid.UUID, body: PlayRequest, key: str | None = Header(None, alias="Idempotency-Key")):
        return await call(request, "POST", f"/v1/bots/{bot_id}/play", body.model_dump(), idempotency(key))

    def control_route(command):
        async def control(request: Request, bot_id: uuid.UUID, body: ControlRequest | None = Body(None),
                          key: str | None = Header(None, alias="Idempotency-Key")):
            return await call(request, "POST", f"/v1/bots/{bot_id}/{command}",
                              body.model_dump(exclude_none=True) if body else {}, idempotency(key))
        app.add_api_route(f"/v1/bots/{{bot_id}}/{command}", control, methods=["POST"],
                          status_code=202, responses={200: {"description": "Control ya aplicado; operación no-op persistida"}},
                          dependencies=[Depends(authenticated)], name=command)
    for command in ("pause", "resume", "stop"):
        control_route(command)

    @app.delete("/v1/bots/{bot_id}", status_code=202, responses={200: {"description": "Recursos ya liberados"}}, dependencies=[Depends(authenticated)])
    async def leave(request: Request, bot_id: uuid.UUID, key: str | None = Header(None, alias="Idempotency-Key")):
        return await call(request, "DELETE", f"/v1/bots/{bot_id}", {}, idempotency(key))

    @app.get("/v1/operations/{operation_id}", dependencies=[Depends(authenticated)])
    async def operation(request: Request, operation_id: uuid.UUID):
        return await call(request, "GET", f"/v1/operations/{operation_id}")

    @app.get("/v1/bots/{bot_id}/events", dependencies=[Depends(authenticated)])
    async def events(request: Request, bot_id: uuid.UUID, after_sequence: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        return await call(request, "GET", f"/v1/bots/{bot_id}/events", params={"after_sequence": after_sequence, "limit": limit})

    @app.get("/v1/capacity", dependencies=[Depends(authenticated)])
    async def capacity(request: Request):
        return await call(request, "GET", "/v1/capacity")

    @app.get("/openapi.json", dependencies=[Depends(authenticated)], include_in_schema=False)
    async def openapi():
        return app.openapi()

    @app.get("/docs", dependencies=[Depends(authenticated)], include_in_schema=False)
    async def docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title=title)

    return app
