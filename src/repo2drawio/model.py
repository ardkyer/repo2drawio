from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
NODE_KINDS = {
    "actor",
    "service",
    "gateway",
    "database",
    "storage",
    "cloud",
    "model",
    "queue",
    "external",
    "generic",
}
DIRECTIONS = {"LR", "RL", "TB", "BT"}
THEMES = {"classic", "icon-sketch", "brand-logos"}


class ModelError(ValueError):
    """Raised when the architecture IR is invalid."""


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], context: str) -> "Evidence":
        if not isinstance(raw, dict):
            raise ModelError(f"{context} must be an object")
        unknown = sorted(set(raw) - {"path", "line", "note"})
        if unknown:
            raise ModelError(f"{context} contains unknown fields: {', '.join(unknown)}")
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ModelError(f"{context}.path must be a non-empty string")
        line = raw.get("line")
        if line is not None and (not isinstance(line, int) or line < 1):
            raise ModelError(f"{context}.line must be a positive integer")
        note = raw.get("note")
        if note is not None and not isinstance(note, str):
            raise ModelError(f"{context}.note must be a string")
        return cls(path=path, line=line, note=note)

    def display(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location} — {self.note}" if self.note else location


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    width: float | None = None
    height: float | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], context: str) -> "Position":
        unknown = sorted(set(raw) - {"x", "y", "width", "height"})
        if unknown:
            raise ModelError(f"{context} contains unknown fields: {', '.join(unknown)}")
        values: dict[str, float | None] = {}
        for key in ("x", "y", "width", "height"):
            value = raw.get(key)
            if key in {"x", "y"} and not isinstance(value, (int, float)):
                raise ModelError(f"{context}.{key} must be a number")
            if key in {"width", "height"} and value is not None and (
                not isinstance(value, (int, float)) or value <= 0
            ):
                raise ModelError(f"{context}.{key} must be a positive number")
            values[key] = float(value) if value is not None else None
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    kind: str = "boundary"
    evidence: tuple[Evidence, ...] = ()
    position: Position | None = None


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    kind: str = "generic"
    subtitle: str | None = None
    parent: str | None = None
    evidence: tuple[Evidence, ...] = ()
    position: Position | None = None


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    label: str = ""
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class Architecture:
    title: str
    direction: str
    groups: tuple[Group, ...] = field(default_factory=tuple)
    nodes: tuple[Node, ...] = field(default_factory=tuple)
    edges: tuple[Edge, ...] = field(default_factory=tuple)
    sketch: bool = True
    theme: str = "classic"


def _required_string(raw: dict[str, Any], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _reject_unknown(raw: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ModelError(f"{context} contains unknown fields: {', '.join(unknown)}")


def _id(raw: dict[str, Any], context: str) -> str:
    value = _required_string(raw, "id", context)
    if not ID_RE.fullmatch(value):
        raise ModelError(
            f"{context}.id must start with a letter and contain only letters, "
            "numbers, dots, colons, underscores, or hyphens"
        )
    return value


def _evidence(raw: Any, context: str) -> tuple[Evidence, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ModelError(f"{context} must be an array")
    return tuple(Evidence.from_dict(item, f"{context}[{index}]") for index, item in enumerate(raw))


def _position(raw: Any, context: str) -> Position | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ModelError(f"{context} must be an object")
    return Position.from_dict(raw, context)


def load_architecture(path: str | Path) -> Architecture:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelError(f"invalid JSON in {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelError("architecture document must be a JSON object")
    _reject_unknown(
        raw,
        {"$schema", "version", "title", "direction", "sketch", "theme", "groups", "nodes", "edges"},
        "architecture",
    )
    if raw.get("version") != 1:
        raise ModelError("version must be 1")

    title = _required_string(raw, "title", "architecture")
    direction = raw.get("direction", "LR")
    if direction not in DIRECTIONS:
        raise ModelError(f"direction must be one of {sorted(DIRECTIONS)}")
    sketch = raw.get("sketch", True)
    if not isinstance(sketch, bool):
        raise ModelError("sketch must be a boolean")
    theme = raw.get("theme", "classic")
    if theme not in THEMES:
        raise ModelError(f"theme must be one of {sorted(THEMES)}")

    raw_groups = raw.get("groups", [])
    raw_nodes = raw.get("nodes", [])
    raw_edges = raw.get("edges", [])
    if not isinstance(raw_groups, list) or not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ModelError("groups, nodes, and edges must be arrays")

    groups: list[Group] = []
    for index, item in enumerate(raw_groups):
        context = f"groups[{index}]"
        if not isinstance(item, dict):
            raise ModelError(f"{context} must be an object")
        _reject_unknown(item, {"id", "label", "kind", "evidence", "position"}, context)
        groups.append(
            Group(
                id=_id(item, context),
                label=_required_string(item, "label", context),
                kind=str(item.get("kind", "boundary")),
                evidence=_evidence(item.get("evidence"), f"{context}.evidence"),
                position=_position(item.get("position"), f"{context}.position"),
            )
        )

    nodes: list[Node] = []
    for index, item in enumerate(raw_nodes):
        context = f"nodes[{index}]"
        if not isinstance(item, dict):
            raise ModelError(f"{context} must be an object")
        _reject_unknown(
            item,
            {"id", "label", "kind", "subtitle", "parent", "evidence", "position"},
            context,
        )
        kind = str(item.get("kind", "generic"))
        if kind not in NODE_KINDS:
            raise ModelError(f"{context}.kind must be one of {sorted(NODE_KINDS)}")
        subtitle = item.get("subtitle")
        if subtitle is not None and not isinstance(subtitle, str):
            raise ModelError(f"{context}.subtitle must be a string")
        parent = item.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise ModelError(f"{context}.parent must be a string")
        nodes.append(
            Node(
                id=_id(item, context),
                label=_required_string(item, "label", context),
                kind=kind,
                subtitle=subtitle,
                parent=parent,
                evidence=_evidence(item.get("evidence"), f"{context}.evidence"),
                position=_position(item.get("position"), f"{context}.position"),
            )
        )

    edges: list[Edge] = []
    for index, item in enumerate(raw_edges):
        context = f"edges[{index}]"
        if not isinstance(item, dict):
            raise ModelError(f"{context} must be an object")
        _reject_unknown(item, {"id", "from", "to", "label", "evidence"}, context)
        label = item.get("label", "")
        if not isinstance(label, str):
            raise ModelError(f"{context}.label must be a string")
        edges.append(
            Edge(
                id=_id(item, context),
                source=_required_string(item, "from", context),
                target=_required_string(item, "to", context),
                label=label,
                evidence=_evidence(item.get("evidence"), f"{context}.evidence"),
            )
        )

    ids = [group.id for group in groups] + [node.id for node in nodes] + [edge.id for edge in edges]
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        raise ModelError(f"IDs must be globally unique: {', '.join(duplicates)}")

    group_ids = {group.id for group in groups}
    node_ids = {node.id for node in nodes}
    for node in nodes:
        if node.parent and node.parent not in group_ids:
            raise ModelError(f"node {node.id!r} references unknown group {node.parent!r}")
    for edge in edges:
        if edge.source not in node_ids:
            raise ModelError(f"edge {edge.id!r} references unknown source {edge.source!r}")
        if edge.target not in node_ids:
            raise ModelError(f"edge {edge.id!r} references unknown target {edge.target!r}")
        if edge.source == edge.target:
            raise ModelError(f"edge {edge.id!r} cannot connect a node to itself")

    return Architecture(
        title=title,
        direction=direction,
        groups=tuple(groups),
        nodes=tuple(nodes),
        edges=tuple(edges),
        sketch=sketch,
        theme=theme,
    )
