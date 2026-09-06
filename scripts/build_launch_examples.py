"""Render unmodified analyzer output from pinned public benchmark snapshots."""
import json
from pathlib import Path

from repo2drawio.analyzer import analyze_repository
from repo2drawio.github import RepositorySnapshot
from repo2drawio.model import load_architecture
from repo2drawio.layout import compute_layout
from repo2drawio.drawio import render_drawio
from repo2drawio.svg import render_svg

EXAMPLES = [
    ("fastapi", "fastapi/full-stack-fastapi-template", "FastAPI full-stack template", "Dependency-level draft. Proxy routing and Compose overrides are not resolved."),
    ("voting", "dockersamples/example-voting-app", "Docker voting app", "Compose dependencies, not a message-flow trace. Includes the optional seed profile."),
    ("flower", "mher/flower", "Celery monitoring with Flower", "Compose dependencies. Prometheus scraping and Celery message flow are not inferred."),
]


if __name__ == "__main__":
    output = Path("src/repo2drawio/static/examples")
    output.mkdir(parents=True, exist_ok=True)
    catalog = []
    for key, slug, title, note in EXAMPLES:
        cached = json.loads((Path(".launch-audit") / slug.replace("/", "--") / "snapshot.json").read_text())
        model = analyze_repository(RepositorySnapshot(**cached["snapshot"]))
        path = output / f"{key}.json"
        path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
        architecture = load_architecture(path)
        layout = compute_layout(architecture)
        render_drawio(architecture, layout, output / f"{key}.drawio", preserve_existing=False)
        render_svg(architecture, layout, output / f"{key}.svg")
        catalog.append({"id": key, "repository": slug, "title": title, "commit": cached["commit"], "note": note, "nodes": len(model["nodes"]), "edges": len(model["edges"]), "manually_corrected": False})
        print(f"Rendered {slug}", flush=True)
    (output / "index.json").write_text(json.dumps(catalog, indent=2) + "\n")
