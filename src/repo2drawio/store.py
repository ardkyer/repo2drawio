from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any
import uuid
import xml.etree.ElementTree as ET


MAX_DIAGRAM_BYTES = 5 * 1024 * 1024


class StoreError(ValueError):
    """Raised when a persisted diagram or job is invalid."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Job:
    id: str
    repo_url: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    repo_slug: str | None = None
    error: str | None = None
    edit_token_hash: str | None = None

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("edit_token_hash", None)
        if self.status == "complete":
            result["result_url"] = f"/d/{self.id}"
            result["drawio_url"] = f"/api/diagrams/{self.id}/download"
            result["svg_url"] = f"/api/diagrams/{self.id}/preview.svg"
        return result


class DiagramStore:
    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.environ.get("REPO2DRAWIO_DATA_DIR", ".repo2drawio-data")
        self.root = Path(configured).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def directory(self, job_id: str) -> Path:
        try:
            uuid.UUID(job_id)
        except ValueError as exc:
            raise StoreError("Invalid diagram ID.") from exc
        return self.root / job_id

    def create(self, repo_url: str) -> tuple[Job, str]:
        job_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(24)
        now = _now()
        job = Job(
            id=job_id,
            repo_url=repo_url,
            status="queued",
            progress=5,
            message="Waiting to inspect repository",
            created_at=now,
            updated_at=now,
            edit_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        directory = self.directory(job_id)
        directory.mkdir(parents=True, exist_ok=False)
        self.save(job)
        return job, token

    def save(self, job: Job) -> None:
        job.updated_at = _now()
        directory = self.directory(job.id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "job.json"
        temporary = directory / "job.json.tmp"
        with self._lock:
            temporary.write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(destination)

    def load(self, job_id: str) -> Job:
        path = self.directory(job_id) / "job.json"
        try:
            return Job(**json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise StoreError("Diagram not found.") from exc
        except (json.JSONDecodeError, TypeError) as exc:
            raise StoreError("Stored diagram metadata is invalid.") from exc

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self.load(job_id)
            for key, value in changes.items():
                if not hasattr(job, key):
                    raise StoreError(f"Unknown job field: {key}")
                setattr(job, key, value)
            self.save(job)
            return job

    def path(self, job_id: str, filename: str) -> Path:
        if filename not in {"architecture.json", "architecture.drawio", "architecture.svg"}:
            raise StoreError("Invalid artifact name.")
        path = self.directory(job_id) / filename
        if not path.is_file():
            raise StoreError("Diagram artifact not found.")
        return path

    def verify_token(self, job: Job, token: str | None) -> bool:
        if not token or not job.edit_token_hash:
            return False
        candidate = hashlib.sha256(token.encode()).hexdigest()
        return hmac.compare_digest(candidate, job.edit_token_hash)

    def save_diagram(self, job_id: str, xml: str, token: str | None) -> Path:
        job = self.load(job_id)
        if not self.verify_token(job, token):
            raise PermissionError("A valid edit token is required.")
        encoded = xml.encode("utf-8")
        if len(encoded) > MAX_DIAGRAM_BYTES:
            raise StoreError("Diagram is larger than the 5 MB edit limit.")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise StoreError("Diagram contains unsupported XML declarations.")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise StoreError("Diagram XML is invalid.") from exc
        if root.tag != "mxfile":
            raise StoreError("Diagram must be a Draw.io mxfile document.")
        destination = self.directory(job_id) / "architecture.drawio"
        temporary = destination.with_suffix(".drawio.tmp")
        with self._lock:
            temporary.write_bytes(encoded)
            temporary.replace(destination)
            self.update(job_id, message="Saved from the Draw.io editor")
        return destination
