"""Reproducible public-only smoke audit; never executes downloaded repository code."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, UTC
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from repo2drawio.github import snapshot_from_archive
from repo2drawio.analyzer import analyze_repository

REPOS = [
    "fastapi/full-stack-fastapi-template",
    "dockersamples/example-voting-app",
    "mher/flower",
    "gothinkster/flask-realworld-example-app",
    "gothinkster/react-redux-realworld-example-app",
    "tiangolo/uwsgi-nginx-flask-docker",
    "streamlit/hello",
    "docker/awesome-compose",
    "pallets/flask",
    "encode/httpx",
]
CACHE = Path(".launch-audit")


def audit(slug):
    started = time.monotonic()
    directory = CACHE / slug.replace("/", "--")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_file = directory / "snapshot.json"
        if snapshot_file.exists():
            cached = json.loads(snapshot_file.read_text())
            from repo2drawio.github import RepositorySnapshot
            snapshot = RepositorySnapshot(**cached["snapshot"])
            commit = cached["commit"]
        else:
            request = Request(f"https://api.github.com/repos/{slug}/commits/HEAD", headers={"User-Agent": "repo2drawio-launch-audit"})
            with urlopen(request, timeout=25) as response:
                commit = json.load(response)["sha"]
            request = Request(f"https://codeload.github.com/{slug}/zip/{commit}", headers={"User-Agent": "repo2drawio-launch-audit"})
            with urlopen(request, timeout=40) as response:
                raw = response.read(100 * 1024 * 1024 + 1)
            if len(raw) > 100 * 1024 * 1024:
                raise ValueError("Audit archive exceeds 100 MB; skipped")
            owner, name = slug.split("/")
            snapshot = snapshot_from_archive(owner, name, raw)
            snapshot_file.write_text(json.dumps({"commit": commit, "snapshot": snapshot.__dict__}))
        model = analyze_repository(snapshot)
        (directory / "architecture.json").write_text(json.dumps(model, indent=2) + "\n")
        result = {"repository": slug, "commit": commit, "files": len(snapshot.files), "nodes": len(model["nodes"]), "edges": len(model["edges"]), "labels": [n["label"] for n in model["nodes"]], "status": "generated", "seconds": round(time.monotonic() - started, 2)}
    except Exception as exc:
        result = {"repository": slug, "status": "failed", "error": str(exc)}
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    CACHE.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(audit, REPOS))
    (CACHE / "results.json").write_text(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "note": "Generation smoke test, NOT an architecture accuracy benchmark. Cached commit snapshots are reused on reruns.", "results": results}, indent=2) + "\n")
