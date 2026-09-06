from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
import uvicorn

from . import __version__
from .admission import CapacityError, RateLimiter
from .analyzer import analyze_repository
from .drawio import render_drawio
from .github import RepositoryError, fetch_repository, parse_github_url
from .layout import compute_layout
from .model import ModelError, load_architecture
from .store import DiagramStore, StoreError
from .svg import render_svg


STATIC_DIR = Path(__file__).parent / "static"


class CreateJobRequest(BaseModel):
    repo_url: str = Field(min_length=1, max_length=300)
    github_token: SecretStr | None = Field(default=None, max_length=512)
    theme: Literal["classic", "icon-sketch", "brand-logos"] = "brand-logos"


class SaveDiagramRequest(BaseModel):
    xml: str = Field(min_length=1, max_length=5 * 1024 * 1024)


class JobRunner:
    def __init__(self, store: DiagramStore, workers: int = 2) -> None:
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="repo2drawio")
        self._submitted: set[str] = set()
        self._lock = threading.Lock()
        self.max_pending = max(workers, int(os.environ.get("REPO2DRAWIO_MAX_PENDING", "8")))
        self.max_jobs = max(1, int(os.environ.get("REPO2DRAWIO_MAX_JOBS", "500")))

    def submit(
        self,
        repo_url: str,
        github_token: str | None = None,
        private_access: bool = False,
        theme: str = "brand-logos",
    ) -> tuple[dict, str]:
        parse_github_url(repo_url)
        with self._lock:
            if len(self._submitted) >= self.max_pending:
                raise CapacityError("The server is busy. Try an instant example below or retry in a minute.")
            if sum(1 for _ in self.store.root.glob("*/job.json")) >= self.max_jobs:
                raise CapacityError("This instance has reached its storage allowance. Instant examples are still available.")
            job, token = self.store.create(repo_url)
            self._submitted.add(job.id)
        try:
            self.executor.submit(self._run, job.id, repo_url, github_token, private_access, theme)
        except Exception:
            with self._lock:
                self._submitted.discard(job.id)
            self.store.update(job.id, status="failed", error="Could not start analysis.")
            raise
        return job.public(), token

    def _run(
        self,
        job_id: str,
        repo_url: str,
        github_token: str | None,
        private_access: bool,
        theme: str,
    ) -> None:
        try:
            self.store.update(job_id, status="running", progress=18, message="Downloading repository safely")
            snapshot = fetch_repository(repo_url, token=github_token, private_access=private_access)
            github_token = None
            self.store.update(
                job_id,
                repo_slug=snapshot.slug,
                progress=48,
                message=f"Inspecting {len(snapshot.files)} architecture-bearing files",
            )
            model = analyze_repository(snapshot, theme=theme)
            directory = self.store.directory(job_id)
            model_path = directory / "architecture.json"
            model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.store.update(job_id, progress=76, message="Laying out editable Draw.io shapes")
            architecture = load_architecture(model_path)
            layout = compute_layout(architecture)
            render_drawio(architecture, layout, directory / "architecture.drawio", preserve_existing=False)
            render_svg(architecture, layout, directory / "architecture.svg")
            self.store.update(
                job_id,
                status="complete",
                progress=100,
                message=f"Created {len(architecture.nodes)} components and {len(architecture.edges)} connections",
            )
        except (RepositoryError, ModelError, OSError, ValueError) as exc:
            self.store.update(job_id, status="failed", progress=100, message="Generation failed", error=str(exc))
        except Exception:
            self.store.update(
                job_id,
                status="failed",
                progress=100,
                message="Generation failed",
                error="Unexpected analysis error. Check the server logs and retry.",
            )
        finally:
            with self._lock:
                self._submitted.discard(job_id)


def create_app(
    store: DiagramStore | None = None,
    runner: JobRunner | None = None,
) -> FastAPI:
    diagram_store = store or DiagramStore()
    job_runner = runner or JobRunner(diagram_store, workers=int(os.environ.get("REPO2DRAWIO_WORKERS", "2")))
    app = FastAPI(title="repo2drawio", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.state.store = diagram_store
    app.state.runner = job_runner
    limiter = RateLimiter(limit=max(1, int(os.environ.get("REPO2DRAWIO_RATE_LIMIT", "3"))))
    allow_private = os.environ.get("REPO2DRAWIO_ALLOW_PRIVATE", "true").lower() == "true"
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.exception_handler(StoreError)
    async def store_error(_: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    def example_info(example_id: str) -> dict:
        catalog = json.loads((STATIC_DIR / "examples" / "index.json").read_text())
        item = next((item for item in catalog if item["id"] == example_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Example not found.")
        return item

    @app.get("/api/config")
    async def config() -> dict:
        return {"allow_private": allow_private}

    @app.get("/examples/{example_id}", include_in_schema=False)
    async def example_editor(example_id: str) -> FileResponse:
        example_info(example_id)
        return FileResponse(STATIC_DIR / "editor.html")

    @app.get("/api/examples/{example_id}")
    async def example(example_id: str) -> dict:
        item = example_info(example_id)
        return {**item, "repo_slug": item["repository"], "xml": (STATIC_DIR / "examples" / f"{item['id']}.drawio").read_text()}

    @app.get("/d/{job_id}", include_in_schema=False)
    async def editor(job_id: str) -> FileResponse:
        job = diagram_store.load(job_id)
        if job.status != "complete":
            raise HTTPException(status_code=409, detail="Diagram is not ready yet.")
        return FileResponse(STATIC_DIR / "editor.html")

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
    async def create_job(payload: CreateJobRequest, request: Request) -> dict:
        github_token = payload.github_token.get_secret_value().strip() if payload.github_token else None
        if github_token and not allow_private:
            raise HTTPException(status_code=422, detail="This public demo accepts public repositories only. Self-host to use private repositories.")
        if not limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Too many requests. Try an instant example or retry in a minute.", headers={"Retry-After": "60"})
        try:
            job, token = job_runner.submit(
                payload.repo_url,
                github_token=github_token or None,
                private_access=bool(github_token),
                theme=payload.theme,
            )
        except RepositoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except CapacityError as exc:
            raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "60"}) from exc
        job["edit_token"] = token
        return job

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        return diagram_store.load(job_id).public()

    @app.get("/api/diagrams/{job_id}")
    async def get_diagram(job_id: str) -> dict:
        job = diagram_store.load(job_id)
        if job.status != "complete":
            raise HTTPException(status_code=409, detail="Diagram is not ready yet.")
        xml = diagram_store.path(job_id, "architecture.drawio").read_text(encoding="utf-8")
        return {"id": job_id, "repo_slug": job.repo_slug, "xml": xml, "message": job.message}

    @app.put("/api/diagrams/{job_id}")
    async def save_diagram(
        job_id: str,
        payload: SaveDiagramRequest,
        x_edit_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        try:
            diagram_store.save_diagram(job_id, payload.xml, x_edit_token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"status": "saved"}

    @app.get("/api/diagrams/{job_id}/download")
    async def download(job_id: str) -> FileResponse:
        job = diagram_store.load(job_id)
        filename = f"{(job.repo_slug or 'architecture').replace('/', '-')}.drawio"
        return FileResponse(
            diagram_store.path(job_id, "architecture.drawio"),
            media_type="application/vnd.jgraph.mxfile",
            filename=filename,
        )

    @app.get("/api/diagrams/{job_id}/preview.svg")
    async def preview(job_id: str) -> Response:
        return Response(
            diagram_store.path(job_id, "architecture.svg").read_text(encoding="utf-8"),
            media_type="image/svg+xml",
        )

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "repo2drawio.web:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
