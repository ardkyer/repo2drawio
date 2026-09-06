from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import posixpath
import re
from typing import Any

import yaml

from .github import RepositorySnapshot


DATABASE_MARKERS = {
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "sqlite": "SQLite",
    "duckdb": "DuckDB",
}
QUEUE_MARKERS = {
    "redis": "Redis",
    "kafka": "Kafka",
    "rabbitmq": "RabbitMQ",
    "celery": "Celery",
}
EXTERNAL_MARKERS = {
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "stripe": "Stripe",
    "slack": "Slack",
    "twilio": "Twilio",
    "sendgrid": "SendGrid",
    "s3": "Amazon S3",
    "firebase": "Firebase",
    "supabase": "Supabase",
}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-_.:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"n-{cleaned}"
    return cleaned[:64]


def _line(text: str, pattern: str) -> int:
    lowered = pattern.lower()
    for index, row in enumerate(text.splitlines(), start=1):
        if lowered in row.lower():
            return index
    return 1


def _evidence(path: str, text: str, marker: str, note: str) -> list[dict[str, Any]]:
    return [{"path": path, "line": _line(text, marker), "note": note}]


@dataclass
class Builder:
    title: str
    theme: str
    nodes: dict[str, dict[str, Any]]
    edges: dict[str, dict[str, Any]]
    groups: dict[str, dict[str, Any]]

    @classmethod
    def create(cls, title: str, theme: str = "classic") -> "Builder":
        return cls(title=title, theme=theme, nodes={}, edges={}, groups={})

    def group(self, group_id: str, label: str, evidence: list[dict[str, Any]] | None = None) -> None:
        self.groups.setdefault(group_id, {"id": group_id, "label": label, "evidence": evidence or []})

    def node(
        self,
        node_id: str,
        label: str,
        kind: str,
        subtitle: str,
        evidence: list[dict[str, Any]],
        parent: str | None = "runtime",
    ) -> str:
        node_id = _slug(node_id)
        incoming = {
            "id": node_id,
            "label": label,
            "kind": kind,
            "subtitle": subtitle,
            "evidence": evidence,
        }
        if parent:
            incoming["parent"] = parent
        if node_id not in self.nodes:
            self.nodes[node_id] = incoming
        else:
            current = self.nodes[node_id]
            known = {(item["path"], item.get("line")) for item in current["evidence"]}
            current["evidence"].extend(
                item for item in evidence if (item["path"], item.get("line")) not in known
            )
        return node_id

    def edge(
        self,
        source: str,
        target: str,
        label: str,
        evidence: list[dict[str, Any]],
    ) -> None:
        if source == target or source not in self.nodes or target not in self.nodes:
            return
        edge_id = _slug(f"edge-{source}-{target}")
        if edge_id not in self.edges:
            self.edges[edge_id] = {
                "id": edge_id,
                "from": source,
                "to": target,
                "label": label,
                "evidence": evidence,
            }
            return
        current = self.edges[edge_id]
        known = {(item["path"], item.get("line")) for item in current["evidence"]}
        current["evidence"].extend(
            item for item in evidence if (item["path"], item.get("line")) not in known
        )
        if current["label"] in {"depends on", "uses"} and label not in {"depends on", "uses"}:
            current["label"] = label

    def model(self) -> dict[str, Any]:
        return {
            "version": 1,
            "title": self.title,
            "direction": "LR",
            "sketch": True,
            "theme": self.theme,
            "groups": list(self.groups.values()),
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
        }

    def collapse_node(self, source: str | None, target: str | None) -> str | None:
        if not source or not target or source == target or source not in self.nodes or target not in self.nodes:
            return source
        detected = self.nodes.pop(source)
        container = self.nodes[target]
        container["label"] = detected["label"]
        container["subtitle"] = detected.get("subtitle") or container.get("subtitle", "Docker service")
        known = {(item["path"], item.get("line")) for item in container["evidence"]}
        container["evidence"].extend(
            item for item in detected["evidence"] if (item["path"], item.get("line")) not in known
        )
        affected = [edge for edge in self.edges.values() if edge["from"] == source or edge["to"] == source]
        for edge in affected:
            self.edges.pop(edge["id"], None)
            self.edge(
                target if edge["from"] == source else edge["from"],
                target if edge["to"] == source else edge["to"],
                edge["label"],
                edge["evidence"],
            )
        return target


@dataclass(frozen=True)
class Component:
    node_id: str
    root: str
    role: str
    framework: str


@dataclass
class ComposeService:
    name: str
    path: str
    text: str
    config: dict[str, Any]
    build_root: str
    node_id: str | None = None


def _root(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def _under(path: str, root: str) -> bool:
    return not root or path == root or path.startswith(f"{root}/")


def _runtime_path(snapshot: RepositorySnapshot, root: str) -> tuple[str, str] | None:
    entrypoints = {"main.py", "app.py", "server.py", "serve.py", "manage.py", "wsgi.py", "asgi.py"}
    for path, text in snapshot.files.items():
        if _under(path, root) and PurePosixPath(path).name.lower() in entrypoints:
            return path, text
    for path, text in snapshot.files.items():
        if _under(path, root) and PurePosixPath(path).name.lower() == "dockerfile":
            if any(marker in text.lower() for marker in ("uvicorn", "gunicorn", "node ", "npm start", "java -jar")):
                return path, text
    return None


def _component_label(root: str, framework: str, role: str) -> str:
    classifier = root.lower().replace("-", "_")
    if role == "frontend":
        return "Web Application"
    if any(marker in classifier for marker in ("ml_server", "ml-service", "model_server", "inference")):
        return "ML Inference Service"
    if any(marker in classifier for marker in ("cutout", "upscale", "image_processing", "image-service")):
        return "Image Processing Service"
    if framework == "Apache Airflow":
        return "Workflow Orchestrator"
    if any(marker in classifier for marker in ("worker", "consumer", "jobs")):
        return "Background Worker"
    return "Backend API"


def _discover_components(snapshot: RepositorySnapshot, builder: Builder) -> tuple[list[Component], str | None, str | None]:
    components: dict[str, Component] = {}
    frontend: str | None = None
    backend: str | None = None

    for path, text in snapshot.files.items():
        if PurePosixPath(path).name.lower() != "package.json":
            continue
        try:
            package = json.loads(text)
        except json.JSONDecodeError:
            continue
        dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        root = _root(path)
        framework = next(
            (
                label
                for marker, label in (
                    ("next", "Next.js"),
                    ("react", "React"),
                    ("vue", "Vue"),
                    ("svelte", "Svelte"),
                    ("@angular/core", "Angular"),
                )
                if marker in dependencies
            ),
            None,
        )
        if framework:
            node_id = builder.node(
                f"web-{root or 'frontend'}",
                _component_label(root, framework, "frontend"),
                "service",
                framework,
                _evidence(path, text, framework.split(".")[0], f"{framework} application manifest"),
            )
            components[node_id] = Component(node_id, root, "frontend", framework)
            frontend = frontend or node_id
        backend_framework = next(
            (
                label
                for marker, label in (
                    ("express", "Express"),
                    ("@nestjs/core", "NestJS"),
                    ("fastify", "Fastify"),
                    ("koa", "Koa"),
                )
                if marker in dependencies
            ),
            None,
        )
        if backend_framework and _runtime_path(snapshot, root):
            node_id = builder.node(
                f"service-{root or 'node'}",
                _component_label(root, backend_framework, "backend"),
                "service",
                backend_framework,
                _evidence(path, text, backend_framework, f"{backend_framework} application manifest"),
            )
            components[node_id] = Component(node_id, root, "backend", backend_framework)
            backend = backend or node_id

    frameworks = (
        ("fastapi", "FastAPI"),
        ("django", "Django"),
        ("flask", "Flask"),
        ("airflow", "Apache Airflow"),
        ("streamlit", "Streamlit"),
    )
    for path, text in snapshot.files.items():
        name = PurePosixPath(path).name.lower()
        if name not in {"requirements.txt", "pyproject.toml", "pipfile"}:
            continue
        root = _root(path)
        runtime = _runtime_path(snapshot, root)
        match = next(((marker, label) for marker, label in frameworks if marker in text.lower()), None)
        if not match or not runtime:
            continue
        marker, framework = match
        label = _component_label(root, framework, "backend")
        node_id = _slug(f"{'api' if label == 'Backend API' else 'service'}-{root or 'python'}")
        node_id = builder.node(
            node_id,
            label,
            "service",
            framework,
            _evidence(path, text, marker, f"{framework} application manifest"),
        )
        builder.node(
            node_id,
            label,
            "service",
            framework,
            [{"path": runtime[0], "line": 1, "note": "runtime entry point"}],
        )
        components[node_id] = Component(node_id, root, "backend", framework)
        if label == "Backend API":
            backend = backend or node_id

    return list(components.values()), frontend, backend


def _normalise_build_root(compose_path: str, config: dict[str, Any]) -> str:
    build = config.get("build", "")
    context = build if isinstance(build, str) else build.get("context", "") if isinstance(build, dict) else ""
    if not isinstance(context, str) or not context.strip():
        return ""
    base = str(PurePosixPath(compose_path).parent)
    combined = posixpath.normpath(posixpath.join("" if base == "." else base, context))
    return "" if combined == "." else combined.lstrip("./")


def _compose_services(snapshot: RepositorySnapshot) -> list[ComposeService]:
    result: list[ComposeService] = []
    for path, text in snapshot.files.items():
        if PurePosixPath(path).name.lower() not in {
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        }:
            continue
        try:
            document = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue
        services = document.get("services", {})
        if not isinstance(services, dict):
            continue
        for name, raw_config in services.items():
            config = raw_config if isinstance(raw_config, dict) else {}
            result.append(
                ComposeService(
                    name=str(name),
                    path=path,
                    text=text,
                    config=config,
                    build_root=_normalise_build_root(path, config),
                )
            )
    return result


def _component_for_root(components: list[Component], root: str, service_name: str) -> Component | None:
    exact = [component for component in components if component.root == root]
    if exact:
        return exact[0]
    contained = [component for component in components if _under(component.root, root)]
    if not contained:
        return None
    classifier = service_name.lower()
    if any(marker in classifier for marker in ("front", "web", "ui")):
        return next((item for item in contained if item.role == "frontend"), contained[0])
    return next(
        (
            item
            for item in contained
            if item.role == "backend" and not any(marker in item.root.lower() for marker in ("ml", "cutout", "upscale"))
        ),
        contained[0],
    )


def _add_compose(snapshot: RepositorySnapshot, builder: Builder, components: list[Component]) -> list[ComposeService]:
    services = _compose_services(snapshot)
    by_name: dict[str, str] = {}
    for service in services:
        image = str(service.config.get("image", ""))
        classifier = f"{service.name} {image} {service.build_root}".lower()
        component = (
            _component_for_root(components, service.build_root, service.name)
            if service.config.get("build")
            else None
        )
        kind = "service"
        label = service.name.replace("-", " ").replace("_", " ").title()
        parent = "runtime"
        for marker, known_label in DATABASE_MARKERS.items():
            if marker in classifier and marker != "sqlite":
                kind, label, parent = "database", known_label, "data"
                break
        else:
            for marker, known_label in QUEUE_MARKERS.items():
                if marker in classifier:
                    kind, label, parent = "queue", known_label, "data"
                    break
            if any(marker in classifier for marker in ("nginx", "traefik", "caddy")):
                kind = "gateway"

        if component and kind == "service":
            service.node_id = component.node_id
            current = builder.nodes[component.node_id]
            builder.node(
                component.node_id,
                current["label"],
                current["kind"],
                current.get("subtitle", "Application service"),
                _evidence(service.path, service.text, service.name, "Docker Compose deployment"),
            )
        else:
            service.node_id = builder.node(
                f"compose-{service.name}",
                label,
                kind,
                image.split(":")[0] or "Docker service",
                _evidence(service.path, service.text, service.name, "Docker Compose service"),
                parent=parent,
            )
        by_name.setdefault(service.name, service.node_id)

    url_pattern = re.compile(r"https?://([A-Za-z0-9_.-]+)(?::\d+)?([^\s$}]*)")
    for service in services:
        if not service.node_id:
            continue
        environment = service.config.get("environment", {})
        items = environment.items() if isinstance(environment, dict) else []
        for key, value in items:
            match = url_pattern.search(str(value))
            if not match or match.group(1) not in by_name:
                continue
            path = match.group(2).split("?")[0].rstrip("/)")
            label = path if path and path != "/" else "HTTP"
            builder.edge(
                service.node_id,
                by_name[match.group(1)],
                label,
                _evidence(service.path, service.text, str(key), "internal service URL"),
            )

    for service in services:
        if not service.node_id:
            continue
        depends = service.config.get("depends_on", [])
        names = list(depends) if isinstance(depends, dict) else depends if isinstance(depends, list) else []
        for target_name in names:
            target = by_name.get(str(target_name))
            if target:
                builder.edge(
                    service.node_id,
                    target,
                    "depends on",
                    _evidence(service.path, service.text, "depends_on", "Docker Compose dependency"),
                )
    return services


def _component_for_path(components: list[Component], path: str) -> Component | None:
    matches = [component for component in components if _under(path, component.root)]
    return max(matches, key=lambda item: len(item.root), default=None)


def _is_operational_source(path: str) -> bool:
    parsed = PurePosixPath(path)
    excluded = {"tests", "test", "e2e", "fixtures", "data", "docs", "examples", "legacy", "public", "scripts"}
    if {part.lower() for part in parsed.parts} & excluded:
        return False
    if parsed.name.lower().startswith("readme"):
        return False
    if any(marker in parsed.name.lower() for marker in (".spec.", ".test.")):
        return False
    if parsed.name.lower().startswith(("playwright.", "vitest.", "jest.")):
        return False
    return parsed.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".php"}


EXTERNAL_DETECTORS = (
    (
        "anthropic",
        "Anthropic API",
        "LLM provider",
        (r"api\.anthropic\.com", r"from\s+anthropic\s+import", r"anthropic\.Anthropic\s*\("),
    ),
    (
        "openai",
        "OpenAI API",
        "AI provider",
        (r"api\.openai\.com", r"from\s+openai\s+import", r"\bOpenAI\s*\("),
    ),
    (
        "gemini",
        "Google Gemini API",
        "AI provider",
        (r"generativelanguage\.googleapis\.com", r"google\.genai", r"genai\.Client\s*\("),
    ),
    ("stripe", "Stripe", "Payment API", (r"stripe\.com/v1", r"stripe\.[A-Za-z]+\.create\s*\(")),
    ("slack", "Slack", "Messaging API", (r"hooks\.slack\.com", r"slack_sdk", r"chat\.postMessage")),
    ("twilio", "Twilio", "Messaging API", (r"api\.twilio\.com", r"from\s+twilio")),
    ("s3", "Amazon S3", "Object storage", (r"boto3\.client\(['\"]s3", r"s3://")),
)


def _add_externals(snapshot: RepositorySnapshot, builder: Builder, components: list[Component]) -> None:
    for key, label, subtitle, patterns in EXTERNAL_DETECTORS:
        for path, text in snapshot.files.items():
            if not _is_operational_source(path):
                continue
            match = next(
                (found for pattern in patterns if (found := re.search(pattern, text, re.IGNORECASE))),
                None,
            )
            if not match:
                continue
            owner = _component_for_path(components, path)
            if not owner:
                continue
            external = builder.node(
                f"external-{key}",
                label,
                "storage" if key == "s3" else "external",
                subtitle,
                _evidence(path, text, match.group(0), f"{label} client call"),
                parent="integrations",
            )
            builder.edge(
                owner.node_id,
                external,
                "API",
                _evidence(path, text, match.group(0), f"calls {label}"),
            )


def _add_data_stores(
    snapshot: RepositorySnapshot,
    builder: Builder,
    components: list[Component],
    services: list[ComposeService],
    backend: str | None,
) -> None:
    repo_text = "\n".join(snapshot.files.values()).lower()
    for service in services:
        if not service.node_id or builder.nodes[service.node_id]["kind"] not in {"service", "gateway"}:
            continue
        environment = service.config.get("environment", {})
        keys = list(environment) if isinstance(environment, dict) else []
        db_key = next((str(key) for key in keys if str(key).upper().endswith("DB_HOST")), None)
        if not db_key:
            continue
        label = "MariaDB" if "mariadb" in repo_text else "MySQL"
        data = builder.node(
            f"data-{label.lower()}",
            label,
            "database",
            "Application database",
            _evidence(service.path, service.text, db_key, "database host configuration"),
            parent="data",
        )
        builder.edge(
            service.node_id,
            data,
            "SQL",
            _evidence(service.path, service.text, db_key, "database connection"),
        )

    manifest_markers = (
        ("psycopg", "PostgreSQL"),
        ("postgres", "PostgreSQL"),
        ("pymysql", "MariaDB" if "mariadb" in repo_text else "MySQL"),
        ("mysqlclient", "MySQL"),
        ("pymongo", "MongoDB"),
        ("duckdb", "DuckDB"),
        ("sqlite", "SQLite"),
        ("redis", "Redis"),
        ("kafka", "Kafka"),
        ("rabbitmq", "RabbitMQ"),
    )
    for path, text in snapshot.files.items():
        if PurePosixPath(path).name.lower() not in {"requirements.txt", "package.json", "pyproject.toml"}:
            continue
        owner = _component_for_path(components, path)
        source = owner.node_id if owner else backend
        if not source:
            continue
        for marker, label in manifest_markers:
            if marker not in text.lower():
                continue
            kind = "queue" if label in QUEUE_MARKERS.values() else "database"
            # A client dependency is not a second database beside its Compose service.
            # Reuse only an unambiguous instance explicitly connected to this source.
            connected_data = {
                edge["to"]
                for edge in builder.edges.values()
                if edge["from"] == source
                and builder.nodes[edge["to"]]["label"] == label
                and builder.nodes[edge["to"]]["kind"] == kind
            }
            data_id = next(iter(connected_data)) if len(connected_data) == 1 else f"data-{label.lower()}"
            existing = builder.nodes.get(data_id)
            data = builder.node(
                data_id,
                label,
                kind,
                existing.get("subtitle", "Detected runtime dependency") if existing else "Detected runtime dependency",
                _evidence(path, text, marker, f"{label} client dependency"),
                parent="data",
            )
            builder.edge(source, data, "read / write", _evidence(path, text, marker, f"uses {label}"))


def _source_matches(
    snapshot: RepositorySnapshot,
    *,
    path_any: tuple[str, ...],
    text_any: tuple[str, ...] = (),
    text_all: tuple[str, ...] = (),
) -> list[tuple[str, str, str]]:
    """Return operational sources with the exact marker that justified a match."""
    matches: list[tuple[str, str, str]] = []
    for path, text in snapshot.files.items():
        if not _is_operational_source(path):
            continue
        if PurePosixPath(path).name.lower() == "__init__.py":
            continue
        lowered_path = path.lower()
        lowered_text = text.lower()
        if path_any and not any(marker in lowered_path for marker in path_any):
            continue
        if text_all and not all(marker in lowered_text for marker in text_all):
            continue
        marker = next((item for item in text_any if item in lowered_text), None)
        if text_any and marker is None:
            continue
        matches.append((path, text, marker or (text_all[0] if text_all else path_any[0])))
    return matches


def _first_match(
    snapshot: RepositorySnapshot,
    *,
    path_any: tuple[str, ...],
    text_any: tuple[str, ...] = (),
    text_all: tuple[str, ...] = (),
) -> tuple[str, str, str] | None:
    return next(
        iter(
            _source_matches(
                snapshot,
                path_any=path_any,
                text_any=text_any,
                text_all=text_all,
            )
        ),
        None,
    )


def _node_with_label(builder: Builder, label: str) -> str | None:
    return next((node_id for node_id, node in builder.nodes.items() if node["label"] == label), None)


def _remove_edge(builder: Builder, source: str, target: str) -> None:
    edge_id = _slug(f"edge-{source}-{target}")
    builder.edges.pop(edge_id, None)


def _add_capabilities(
    snapshot: RepositorySnapshot,
    builder: Builder,
    backend: str | None,
) -> None:
    """Promote code-level application capabilities into evidence-backed architecture nodes.

    These detectors intentionally require both a meaningful source location and implementation
    symbols. A README mention alone is never enough to create a capability or an edge.
    """
    if not backend:
        return

    ml_service = _node_with_label(builder, "ML Inference Service")

    voucher_router = _first_match(
        snapshot,
        path_any=("/export_voucher/api/", "/export-voucher/api/"),
        text_any=("/recommend", "ml/categories"),
    )
    voucher_rules = _first_match(
        snapshot,
        path_any=("/engine/recommend.", "/rules/recommend.", "rule_engine"),
        text_any=("evaluate_conditions", "deterministic", "prioritize"),
    )
    if voucher_router and voucher_rules:
        builder.group("voucher", "Export Voucher Recommendation")
        path, text, marker = voucher_rules
        rule_node = builder.node(
            "capability-voucher-rules",
            "Voucher Rule Engine",
            "model",
            "Deterministic subcategory rules",
            _evidence(path, text, marker, "deterministic voucher recommendation engine"),
            parent="voucher",
        )
        route_path, route_text, route_marker = voucher_router
        builder.edge(
            backend,
            rule_node,
            "/export-voucher/recommend",
            _evidence(route_path, route_text, route_marker, "voucher recommendation route"),
        )

    voucher_ml = _first_match(
        snapshot,
        path_any=("/export_voucher/ml/", "/export-voucher/ml/"),
        text_any=("predict", "provider", "fallback"),
    )
    if voucher_router and voucher_ml:
        builder.group("voucher", "Export Voucher Recommendation")
        path, text, marker = voucher_ml
        predictor = builder.node(
            "capability-voucher-ml",
            "ML Category Predictor",
            "model",
            "Top-category prediction + fallback",
            _evidence(path, text, marker, "voucher ML category provider"),
            parent="voucher",
        )
        route_path, route_text, _ = voucher_router
        builder.edge(
            backend,
            predictor,
            "/export-voucher/ml/categories",
            _evidence(route_path, route_text, "ml/categories", "ML category prediction route"),
        )
        if ml_service:
            builder.edge(
                predictor,
                ml_service,
                "inference API",
                _evidence(path, text, marker, "remote ML provider call"),
            )

    domestic_router = _first_match(
        snapshot,
        path_any=("/routers/domestic.", "/api/domestic."),
        text_any=("/domestic/quick", "predict_families", "judge"),
    )
    domestic_rules = _first_match(
        snapshot,
        path_any=("/services/domestic.", "/domain/domestic."),
        text_any=("def judge", "eligible", "rule"),
    )
    domestic_ml = _first_match(
        snapshot,
        path_any=("domestic_ml.", "/domestic/ml/"),
        text_any=("predict_families", "/predict/domestic", "family_prediction"),
    )
    domestic_hybrid = _first_match(
        snapshot,
        path_any=("domestic_mvp.", "domestic_recommend", "domestic_rank"),
        text_any=("family_prediction", "_basic_eligible", "deterministic"),
    )
    if domestic_router and domestic_rules:
        builder.group("domestic", "Domestic Recommendation")
        path, text, marker = domestic_rules
        rule_node = builder.node(
            "capability-eligibility-rules",
            "Rule-based Eligibility",
            "model",
            "Deterministic candidate filter",
            _evidence(path, text, marker, "deterministic eligibility rules"),
            parent="domestic",
        )
        route_path, route_text, _ = domestic_router
        builder.edge(
            backend,
            rule_node,
            "/domestic/judge",
            _evidence(route_path, route_text, "judge", "domestic eligibility route"),
        )
    else:
        rule_node = None

    if domestic_router and domestic_ml:
        builder.group("domestic", "Domestic Recommendation")
        path, text, marker = domestic_ml
        ml_node = builder.node(
            "capability-domestic-ml",
            "ML Family Ranker",
            "model",
            "Model scores + safe fallback",
            _evidence(path, text, marker, "domestic ML ranking adapter"),
            parent="domestic",
        )
        if ml_service:
            builder.edge(
                ml_node,
                ml_service,
                "/predict/domestic",
                _evidence(path, text, marker, "calls remote domestic inference"),
            )
    else:
        ml_node = None

    if domestic_router and domestic_hybrid:
        builder.group("domestic", "Domestic Recommendation")
        path, text, marker = domestic_hybrid
        hybrid = builder.node(
            "capability-domestic-hybrid",
            "Hybrid Recommendation Ranker",
            "model",
            "Eligibility rules + ML family scores",
            _evidence(path, text, marker, "hybrid deterministic and ML ranking"),
            parent="domestic",
        )
        route_path, route_text, _ = domestic_router
        builder.edge(
            backend,
            hybrid,
            "/domestic/quick",
            _evidence(route_path, route_text, "quick", "hybrid domestic recommendation route"),
        )
        if rule_node:
            builder.edge(
                rule_node,
                hybrid,
                "eligible candidates",
                _evidence(path, text, marker, "rules remain authoritative for eligibility"),
            )
        if ml_node:
            builder.edge(
                ml_node,
                hybrid,
                "family scores",
                _evidence(path, text, marker, "ML scores rank eligible candidates"),
            )

    assistant_router = _first_match(
        snapshot,
        path_any=("/routers/assistant.", "/routers/chat", "/api/assistant."),
        text_any=("/assistant/message", "answer_message", "chat"),
    )
    assistant_service = _first_match(
        snapshot,
        path_any=("/services/assistant.", "/services/chat", "chatbot"),
        text_any=("answer_message", "understand", "context"),
    )
    chatbot: str | None = None
    if assistant_router and assistant_service:
        builder.group("assistant", "AI Assistant & Retrieval")
        path, text, marker = assistant_service
        chatbot = builder.node(
            "capability-chatbot",
            "AI Chatbot Orchestrator",
            "model",
            "Intent · context · answer routing",
            _evidence(path, text, marker, "assistant request orchestration"),
            parent="assistant",
        )
        route_path, route_text, route_marker = assistant_router
        builder.edge(
            backend,
            chatbot,
            "/assistant/message",
            _evidence(route_path, route_text, route_marker, "assistant message route"),
        )

    analytics = _first_match(
        snapshot,
        path_any=("assistant_analytics", "assistant_retriever", "/rag/"),
        text_any=("duckdb", "retrieve_evidence", "analytics", "rag"),
    )
    if chatbot and analytics:
        builder.group("assistant", "AI Assistant & Retrieval")
        path, text, marker = analytics
        rag = builder.node(
            "capability-analytical-rag",
            "Analytical RAG",
            "model",
            "Retrieval + deterministic analytics",
            _evidence(path, text, marker, "assistant retrieval or analytical runtime"),
            parent="assistant",
        )
        builder.edge(
            chatbot,
            rag,
            "retrieve + analyze",
            _evidence(path, text, marker, "chatbot evidence retrieval"),
        )
        duckdb = _node_with_label(builder, "DuckDB")
        if duckdb:
            _remove_edge(builder, backend, duckdb)
            builder.edge(
                rag,
                duckdb,
                "read-only SQL",
                _evidence(path, text, marker, "analytical data queries"),
            )

    gemini = _node_with_label(builder, "Google Gemini API")
    assistant_gemini = _first_match(
        snapshot,
        path_any=("assistant_gemini", "/assistant/"),
        text_any=("gemini", "genai.client", "generate_content"),
    )
    if chatbot and gemini and assistant_gemini:
        path, text, marker = assistant_gemini
        _remove_edge(builder, backend, gemini)
        builder.edge(
            chatbot,
            gemini,
            "ground / rerank / answer",
            _evidence(path, text, marker, "chatbot Gemini integration"),
        )

    studio_api = _first_match(
        snapshot,
        path_any=("/studio_app/api/", "/studio/api/"),
        text_any=("pipeline", "generate", "studio"),
    )
    studio_pipeline = _first_match(
        snapshot,
        path_any=("/studio_app/modules/", "/studio_app/core/service.", "/studio/pipeline"),
        text_any=("pipeline", "verify", "generate", "run_"),
    )
    if studio_api and studio_pipeline:
        builder.group("content", "Content Generation")
        path, text, marker = studio_pipeline
        studio = builder.node(
            "capability-content-studio",
            "Content Studio Pipeline",
            "service",
            "Generate · verify · publish",
            _evidence(path, text, marker, "content generation pipeline"),
            parent="content",
        )
        api_path, api_text, api_marker = studio_api
        builder.edge(
            backend,
            studio,
            "/studio/*",
            _evidence(api_path, api_text, api_marker, "content studio API"),
        )
        anthropic = _node_with_label(builder, "Anthropic API")
        if anthropic and any("studio_app" in item for item in (path, api_path)):
            _remove_edge(builder, backend, anthropic)
            builder.edge(
                studio,
                anthropic,
                "generate content",
                _evidence(path, text, marker, "content pipeline LLM call"),
            )

    feature_groups = {"domestic", "voucher", "assistant", "content"} & set(builder.groups)
    if feature_groups:
        builder.group("infrastructure", "Shared Infrastructure & Data")
        support_labels = {"ML Inference Service", "Image Processing Service"}
        for node in builder.nodes.values():
            if node.get("parent") == "data" or node["label"] in support_labels:
                node["parent"] = "infrastructure"
        builder.groups.pop("data", None)


def _frontend_api_evidence(snapshot: RepositorySnapshot, frontend: Component) -> list[dict[str, Any]]:
    for path, text in snapshot.files.items():
        if _under(path, frontend.root) and _is_operational_source(path):
            marker = next((item for item in ("/api", "fetch(", "axios") if item.lower() in text.lower()), None)
            if marker:
                return _evidence(path, text, marker, "frontend API client")
    return builder_evidence(frontend, "frontend and backend application boundary")


def builder_evidence(component: Component, note: str) -> list[dict[str, Any]]:
    return [{"path": f"{component.root}/package.json" if component.root else "package.json", "line": 1, "note": note}]


def analyze_repository(snapshot: RepositorySnapshot, theme: str = "brand-logos") -> dict[str, Any]:
    builder = Builder.create(f"{snapshot.name} Architecture", theme=theme)
    builder.group("runtime", "Application Runtime")
    builder.group("data", "Data Stores")
    builder.group("integrations", "External Services")
    readme = next((path for path in snapshot.files if PurePosixPath(path).name.lower().startswith("readme")), None)
    user = builder.node(
        "user",
        "User",
        "actor",
        "Web / API client",
        [{"path": readme or next(iter(snapshot.files)), "line": 1, "note": "user-facing application"}],
        parent=None,
    )

    components, frontend, backend = _discover_components(snapshot, builder)
    services = _add_compose(snapshot, builder, components)
    if not backend:
        backend = next(
            (
                component.node_id
                for component in components
                if component.role == "backend" and builder.nodes[component.node_id]["label"] == "Backend API"
            ),
            None,
        )
    if not frontend:
        frontend = next((component.node_id for component in components if component.role == "frontend"), None)

    compose_nodes = [service.node_id for service in services if service.node_id]
    entry = frontend or backend or next(
        (node for node in compose_nodes if builder.nodes[node]["kind"] in {"service", "gateway"}),
        None,
    )
    if not entry:
        evidence_path = readme or next(iter(snapshot.files))
        entry = builder.node(
            "application",
            "Application",
            "service",
            "Repository runtime",
            [{"path": evidence_path, "line": 1, "note": "primary repository"}],
        )
        backend = entry

    builder.edge(
        user,
        entry,
        "access (inferred)",
        [{"path": readme or next(iter(snapshot.files)), "line": 1, "note": "user entry point"}],
    )
    # Compose may expose several independent UIs. Avoid inventing one primary UI
    # simply because it appeared first in the YAML (e.g. Prometheus before Flower).
    for service in services:
        if (
            service.node_id and service.node_id != entry
            and service.config.get("ports")
            and builder.nodes[service.node_id]["kind"] in {"service", "gateway"}
        ):
            builder.edge(user, service.node_id, "published port", _evidence(service.path, service.text, "ports:", "Compose publishes a port; protocol and audience need review"))
    if frontend and backend and frontend != backend:
        frontend_component = next(item for item in components if item.node_id == frontend)
        builder.edge(frontend, backend, "REST API", _frontend_api_evidence(snapshot, frontend_component))

    _add_data_stores(snapshot, builder, components, services, backend)
    _add_externals(snapshot, builder, components)
    _add_capabilities(snapshot, builder, backend)

    connected = {
        endpoint
        for edge in builder.edges.values()
        for endpoint in (edge["from"], edge["to"])
    }
    for component in components:
        if component.node_id != entry and component.node_id not in connected:
            builder.nodes.pop(component.node_id, None)

    for group_id in ("data", "integrations"):
        if not any(node.get("parent") == group_id for node in builder.nodes.values()):
            builder.groups.pop(group_id, None)
    return builder.model()
