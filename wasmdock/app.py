"""Local control plane. Tenant headers demonstrate partitioning, not authentication."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .models import JobSpec
from .samples import list_samples
from .scheduler import QueueFull, Scheduler, TENANTS

ROOT = Path(__file__).resolve().parents[1]


class BodyLimitMiddleware:
    def __init__(self, app, limit=262_144):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                await PlainTextResponse("Request exceeds the 256 KiB limit.", status_code=413)(scope, receive, send)
                return
            body.append(message)
            if not message.get("more_body", False):
                break
        index = 0
        async def replay():
            nonlocal index
            if index < len(body):
                message = body[index]
                index += 1
                return message
            return await receive()
        return await self.app(scope, replay, send)


def create_app(database=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.scheduler = Scheduler(database or os.getenv("WASMDOCK_DATABASE", str(ROOT/".data/jobs.sqlite3")))
        yield
        app.state.scheduler.close()

    app = FastAPI(title="WasmDock", version="1.0.0", lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; connect-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'" if request.url.path == "/docs" else "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        return response

    def tenant(value):
        if value not in TENANTS:
            raise HTTPException(400, "Use X-Tenant: alpha or beta. This is a local demo identity, not authentication.")
        return value

    @app.get("/healthz")
    def health():
        return {"status":"ok", "runtime":"wasmtime", "version":"1.0.0"}

    @app.get("/api/samples")
    def samples():
        return list_samples()

    @app.post("/api/jobs", status_code=202)
    def submit(spec: JobSpec, request: Request, x_tenant: Annotated[str, Header()] = "alpha"):
        try:
            return request.app.state.scheduler.submit(tenant(x_tenant), spec)
        except QueueFull as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After":"2"}) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/jobs")
    def jobs(request: Request, x_tenant: Annotated[str, Header()] = "alpha"):
        return request.app.state.scheduler.list(tenant(x_tenant))

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, request: Request, x_tenant: Annotated[str, Header()] = "alpha"):
        result = request.app.state.scheduler.get(tenant(x_tenant), job_id)
        if result is None:
            raise HTTPException(404, "Job not found for this tenant.")
        return result

    @app.get("/api/stats")
    def stats(request: Request, x_tenant: Annotated[str, Header()] = "alpha"):
        selected = tenant(x_tenant)
        result = request.app.state.scheduler.stats()
        result["recent"] = request.app.state.scheduler.list(selected, 12)
        return result

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(request: Request):
        stats = request.app.state.scheduler.stats()
        lines = ["# HELP wasmdock_jobs Current bounded job history by tenant and state", "# TYPE wasmdock_jobs gauge"]
        for name, values in stats["tenants"].items():
            for state, value in values.items():
                lines.append(f'wasmdock_jobs{{tenant="{name}",state="{state}"}} {value}')
        lines.extend(["# TYPE wasmdock_worker_slots gauge", f"wasmdock_worker_slots {stats['workers']}"])
        return "\n".join(lines)+"\n"

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT/"static/index.html")

    app.mount("/static", StaticFiles(directory=ROOT/"static"), name="static")
    return app


app = create_app()
