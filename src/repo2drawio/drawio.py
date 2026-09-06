from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

from .brand import Brand, brand_for_node, fetch_brand_svg
from .layout import Box, Layout, runtime_side_detour
from .model import Architecture, Edge, Evidence, Node


COLORS = {
    "actor": ("#f8fafc", "#334155"),
    "service": ("#eff6ff", "#2563eb"),
    "gateway": ("#ecfeff", "#0891b2"),
    "database": ("#eef2ff", "#4f46e5"),
    "storage": ("#ecfdf5", "#059669"),
    "cloud": ("#faf5ff", "#7c3aed"),
    "model": ("#fff7ed", "#ea580c"),
    "queue": ("#fefce8", "#ca8a04"),
    "external": ("#fff7ed", "#c2410c"),
    "generic": ("#ffffff", "#475569"),
    "boundary": ("#ffffff", "#64748b"),
}

SEMANTIC_ICON_COLORS = {
    "rank": "#7c3aed",
    "merge": "#2563eb",
    "eligibility": "#059669",
    "category": "#db2777",
    "rules": "#d97706",
    "chat": "#0284c7",
    "rag": "#7c3aed",
    "content": "#0d9488",
    "inference": "#ea580c",
    "image": "#0891b2",
}


@dataclass
class Preserved:
    label: str | None
    generated_label: str | None
    style: str | None
    generated_style: str | None
    geometry: ET.Element | None


def _evidence_text(items: tuple[Evidence, ...]) -> str:
    return "\n".join(item.display() for item in items)


def _semantic_icon_key(node: Node) -> str | None:
    text = f"{node.label} {node.subtitle or ''}".lower()
    if "hybrid" in text and any(word in text for word in ("recommend", "rank")):
        return "merge"
    if any(word in text for word in ("eligibility", "eligible", "candidate filter")):
        return "eligibility"
    if any(word in text for word in ("rule engine", "rule-based", "deterministic rule")):
        return "rules"
    if any(word in text for word in ("category predictor", "classification", "categor")):
        return "category"
    if any(word in text for word in ("chatbot", "chat bot", "assistant orchestrator")):
        return "chat"
    if any(word in text for word in ("analytical rag", "retrieval", "retriever")):
        return "rag"
    if any(word in text for word in ("content studio", "content generation", "generate · verify")):
        return "content"
    if any(word in text for word in ("family ranker", "recommendation ranker", "ranking")):
        return "rank"
    if any(word in text for word in ("ml inference", "model server", "inference service")):
        return "inference"
    if any(word in text for word in ("image processing", "cutout", "upscale", "vision service")):
        return "image"
    return None


def _icon_key(node: Node) -> str:
    semantic = _semantic_icon_key(node)
    if semantic:
        return semantic
    text = f"{node.label} {node.subtitle or ''}".lower()
    if node.kind == "actor" or any(word in text for word in ("user", "browser", "client")):
        return "browser"
    if node.kind == "database":
        return "database"
    if node.kind == "storage":
        return "storage"
    if node.kind in {"cloud", "external"}:
        return "cloud"
    if node.kind == "queue":
        return "queue"
    if node.kind == "gateway":
        return "gateway"
    if node.kind == "model" or any(word in text for word in ("ml ", "model", "inference", "ai ")):
        return "model"
    if any(word in text for word in ("image", "cutout", "vision", "media")):
        return "image"
    if any(word in text for word in ("web", "react", "frontend", "vite")):
        return "web"
    return "server"


def _icon_markup(node: Node) -> str:
    key = _icon_key(node)
    _, default_stroke = COLORS[node.kind]
    stroke = SEMANTIC_ICON_COLORS.get(key, default_stroke)
    common = f'fill="none" stroke="{stroke}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"'
    icons = {
        "browser": (
            f'<rect x="5" y="7" width="38" height="34" rx="5" {common}/>'
            f'<path d="M5 15h38" {common}/><circle cx="24" cy="23" r="4" {common}/>'
            f'<path d="M16 35c1.5-5 14.5-5 16 0" {common}/>'
        ),
        "web": (
            f'<rect x="4" y="7" width="40" height="34" rx="4" {common}/>'
            f'<path d="M4 16h40M10 11h.1M15 11h.1M20 11h.1M12 25h10M12 31h18" {common}/>'
        ),
        "server": (
            f'<rect x="7" y="7" width="34" height="13" rx="3" {common}/>'
            f'<rect x="7" y="28" width="34" height="13" rx="3" {common}/>'
            f'<path d="M13 13h.1M18 13h.1M13 34h.1M18 34h.1M25 13h10M25 34h10" {common}/>'
        ),
        "database": (
            f'<ellipse cx="24" cy="10" rx="16" ry="6" {common}/>'
            f'<path d="M8 10v13c0 3.3 7.2 6 16 6s16-2.7 16-6V10M8 23v13c0 3.3 7.2 6 16 6s16-2.7 16-6V23" {common}/>'
        ),
        "storage": (
            f'<path d="M5 14a4 4 0 0 1 4-4h10l4 5h16a4 4 0 0 1 4 4v18a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4Z" {common}/>'
            f'<path d="M5 20h38" {common}/>'
        ),
        "cloud": (
            f'<path d="M14 38h22a8 8 0 0 0 1-15.9A13 13 0 0 0 12.2 19 9.5 9.5 0 0 0 14 38Z" {common}/>'
            f'<path d="m20 28 3 3 6-7" {common}/>'
        ),
        "model": (
            f'<path d="M24 5v6M24 37v6M5 24h6M37 24h6M10.5 10.5l4.2 4.2M33.3 33.3l4.2 4.2M37.5 10.5l-4.2 4.2M14.7 33.3l-4.2 4.2" {common}/>'
            f'<circle cx="24" cy="24" r="10" {common}/><path d="m20 25 3 3 6-8" {common}/>'
        ),
        "image": (
            f'<rect x="5" y="7" width="38" height="34" rx="4" {common}/>'
            f'<circle cx="16" cy="17" r="4" {common}/><path d="m9 36 10-10 7 7 5-5 8 8" {common}/>'
        ),
        "queue": (
            f'<path d="M8 12h27l-5-5M35 12l-5 5M40 24H13l5-5M13 24l5 5M8 36h27l-5-5M35 36l-5 5" {common}/>'
        ),
        "gateway": (
            f'<path d="m24 5 17 10v18L24 43 7 33V15Z" {common}/>'
            f'<path d="M15 24h18M28 19l5 5-5 5" {common}/>'
        ),
        "rank": (
            f'<path d="M7 41h35M11 37V27h7v10M21 37V20h7v17M31 37V11h7v26" {common}/>'
            f'<path d="m9 20 9-7 8 4 12-10M34 7h4v4" {common}/>'
        ),
        "merge": (
            f'<path d="M7 12h10c5 0 6 8 11 12 3 2 6 3 13 3M7 36h10c5 0 6-8 11-12" {common}/>'
            f'<path d="m36 22 5 5-5 5" {common}/><circle cx="8" cy="12" r="2" {common}/>'
            f'<circle cx="8" cy="36" r="2" {common}/>'
        ),
        "eligibility": (
            f'<path d="M24 5 39 11v11c0 10-6 17-15 21C15 39 9 32 9 22V11Z" {common}/>'
            f'<path d="m17 24 5 5 10-12" {common}/>'
        ),
        "category": (
            f'<rect x="6" y="7" width="15" height="15" rx="3" {common}/>'
            f'<rect x="27" y="7" width="15" height="15" rx="3" {common}/>'
            f'<rect x="6" y="28" width="15" height="13" rx="3" {common}/>'
            f'<path d="M30 34h9M34.5 29.5v9" {common}/>'
        ),
        "rules": (
            f'<rect x="9" y="8" width="30" height="35" rx="4" {common}/>'
            f'<path d="M18 8V5h12v3M16 19l3 3 5-6M28 20h6M16 31l3 3 5-6M28 32h6" {common}/>'
        ),
        "chat": (
            f'<path d="M6 9h27a5 5 0 0 1 5 5v12a5 5 0 0 1-5 5H18l-8 7v-7H6Z" {common}/>'
            f'<path d="M14 18h16M14 24h10" {common}/>'
        ),
        "rag": (
            f'<rect x="7" y="8" width="25" height="31" rx="3" {common}/>'
            f'<path d="M13 16h13M13 22h10" {common}/><circle cx="32" cy="31" r="8" {common}/>'
            f'<path d="m38 37 5 5" {common}/>'
        ),
        "content": (
            f'<path d="M8 7h23l7 7v28H8Z" {common}/><path d="M31 7v8h7M14 25h14M14 32h10" {common}/>'
            f'<path d="m37 22 1.5 3.5L42 27l-3.5 1.5L37 32l-1.5-3.5L32 27l3.5-1.5Z" {common}/>'
        ),
        "inference": (
            f'<circle cx="9" cy="13" r="3" {common}/><circle cx="9" cy="35" r="3" {common}/>'
            f'<circle cx="25" cy="18" r="3" {common}/><circle cx="25" cy="31" r="3" {common}/>'
            f'<circle cx="41" cy="24" r="3" {common}/>'
            f'<path d="M12 13l10 5M12 35l10-4M28 18l10 6M28 31l10-7" {common}/>'
        ),
    }
    return icons[key]


def _icon_data(node: Node) -> str:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{_icon_markup(node)}</svg>'
    return "data:image/svg+xml," + quote(svg, safe="")


def _node_image_data(node: Node, theme: str) -> str:
    if theme == "brand-logos" and _semantic_icon_key(node) is None:
        brand = brand_for_node(node)
        if brand:
            svg = fetch_brand_svg(brand)
            if svg:
                return "data:image/svg+xml," + quote(svg, safe="")
    return _icon_data(node)


def _display_brand(node: Node, theme: str) -> Brand | None:
    if theme != "brand-logos" or _semantic_icon_key(node) is not None:
        return None
    return brand_for_node(node)


def _node_style(node: Node, sketch: bool, theme: str) -> str:
    kind = node.kind
    fill, stroke = COLORS[kind]
    if theme == "brand-logos":
        return (
            "shape=label;rounded=1;arcSize=10;whiteSpace=wrap;html=1;"
            f"image={_node_image_data(node, theme)};imageWidth=42;imageHeight=42;"
            "imageAlign=left;imageVerticalAlign=middle;spacingLeft=64;"
            "fillColor=#ffffff;strokeColor=#94a3b8;strokeWidth=1.5;"
            "fontSize=15;fontFamily=Helvetica;fontColor=#0f172a;fontStyle=0;"
            "align=left;verticalAlign=middle;spacing=11;shadow=0;"
        )
    if theme == "icon-sketch":
        style = (
            "shape=label;rounded=1;arcSize=14;whiteSpace=wrap;html=1;"
            f"image={_node_image_data(node, theme)};imageWidth=42;imageHeight=42;"
            "imageAlign=left;imageVerticalAlign=middle;spacingLeft=64;"
            f"fillColor={fill};strokeColor={stroke};strokeWidth=2;"
            "fontSize=15;fontFamily=Helvetica;fontColor=#0f172a;fontStyle=0;"
            "align=left;verticalAlign=middle;spacing=11;shadow=1;"
        )
        if sketch:
            style += "sketch=1;curveFitting=1;jiggle=2;"
        return style
    shape = "rounded=1;arcSize=14;"
    if kind == "database":
        shape = "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;"
    elif kind == "cloud":
        shape = "shape=cloud;"
    elif kind == "actor":
        shape = "shape=mxgraph.basic.person;"
    style = (
        f"{shape}whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        "strokeWidth=2;fontSize=15;fontFamily=Helvetica;fontColor=#0f172a;"
        "align=center;verticalAlign=middle;spacing=10;shadow=0;"
    )
    if sketch:
        style += "sketch=1;curveFitting=1;jiggle=2;"
    return style


def _group_style(sketch: bool, theme: str) -> str:
    if theme == "brand-logos":
        return (
            "swimlane;html=1;rounded=1;arcSize=10;startSize=36;horizontal=1;collapsible=0;"
            "fillColor=#ffffff;swimlaneFillColor=#f8fafc;strokeColor=#cbd5e1;"
            "strokeWidth=1.5;fontSize=16;fontStyle=1;fontColor=#334155;"
            "align=left;spacingLeft=14;verticalAlign=top;shadow=0;"
        )
    style = (
        "swimlane;html=1;rounded=1;startSize=36;horizontal=1;collapsible=0;"
        "fillColor=#ffffff;swimlaneFillColor=#f8fafc;strokeColor=#94a3b8;"
        "strokeWidth=2;fontSize=16;fontStyle=1;fontColor=#334155;"
        "align=left;spacingLeft=14;verticalAlign=top;"
    )
    if sketch:
        style += "sketch=1;curveFitting=1;jiggle=2;"
    return style


def _edge_style(sketch: bool, theme: str) -> str:
    if theme == "brand-logos":
        return (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
            "html=1;endArrow=blockThin;endFill=1;strokeColor=#475569;strokeWidth=1.5;"
            "fontSize=13;fontColor=#334155;labelBackgroundColor=#ffffff;"
        )
    style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
        "html=1;endArrow=block;endFill=1;strokeColor=#334155;strokeWidth=2;"
        "fontSize=13;fontColor=#334155;labelBackgroundColor=#ffffff;"
    )
    if sketch:
        style += "sketch=1;curveFitting=1;jiggle=2;"
    return style


def read_preserved(path: Path | None) -> dict[str, Preserved]:
    if path is None or not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {}
    preserved: dict[str, Preserved] = {}
    for obj in root.iter("object"):
        arch_id = obj.get("archId")
        if not arch_id:
            continue
        cell = obj.find("mxCell")
        geometry = cell.find("mxGeometry") if cell is not None else None
        preserved[arch_id] = Preserved(
            label=obj.get("label"),
            generated_label=obj.get("generatedLabel"),
            style=cell.get("style") if cell is not None else None,
            generated_style=obj.get("generatedStyle"),
            geometry=deepcopy(geometry) if geometry is not None else None,
        )
    return preserved


def _resolved_label(new_label: str, old: Preserved | None) -> str:
    if old and old.label is not None and old.generated_label is not None:
        if old.label != old.generated_label:
            return old.label
    return new_label


def _resolved_style(new_style: str, old: Preserved | None) -> str:
    if old and old.style is not None and old.generated_style is not None:
        if old.style != old.generated_style:
            return old.style
    return new_style


def _geometry(box: Box, old: Preserved | None, relative: bool = False) -> ET.Element:
    if old and old.geometry is not None:
        return deepcopy(old.geometry)
    attrs = {"as": "geometry"}
    if relative:
        attrs["relative"] = "1"
    else:
        attrs.update(
            {
                "x": f"{box.x:.1f}",
                "y": f"{box.y:.1f}",
                "width": f"{box.width:.1f}",
                "height": f"{box.height:.1f}",
            }
        )
    return ET.Element("mxGeometry", attrs)


def _edge_geometry(
    architecture: Architecture,
    layout: Layout,
    edge: Edge,
    index: int,
    old: Preserved | None,
) -> ET.Element:
    geometry = _geometry(Box(0, 0, 0, 0), old, relative=True)
    if old and old.geometry is not None:
        return geometry
    nodes = {node.id: node for node in architecture.nodes}
    source = nodes[edge.source]
    target = nodes[edge.target]
    feature_groups = {"domestic", "voucher", "assistant", "content"}
    feature_mode = bool(feature_groups & set(layout.groups)) and "infrastructure" in layout.groups
    source_box = layout.nodes[edge.source]
    target_box = layout.nodes[edge.target]
    if feature_mode:
        route: list[tuple[float, float]] = []
        if source.parent == "runtime" and target.parent in feature_groups:
            target_group = layout.groups[target.parent]
            top_y = target_group.y - 24.0 - (index % 5) * 9.0
            spine_x = target_group.x - 32.0 - (index % 6) * 10.0
            route = [
                (source_box.center[0], top_y),
                (spine_x, top_y),
                (spine_x, target_box.center[1]),
            ]
        elif source.parent in feature_groups and target.parent == "infrastructure":
            spine_x = layout.groups[source.parent].x - 32.0 - (index % 6) * 10.0
            top_y = layout.groups["infrastructure"].y - 24.0 - (index % 6) * 9.0
            route = [
                (spine_x, source_box.center[1]),
                (spine_x, top_y),
                (target_box.center[0], top_y),
                (target_box.center[0], target_box.y),
            ]
        elif source.parent == "runtime" and target.parent == "infrastructure":
            spine_x = layout.groups["runtime"].right + 34.0 + (index % 6) * 12.0
            top_y = layout.groups["infrastructure"].y - 24.0 - (index % 6) * 9.0
            route = [
                (spine_x, source_box.center[1]),
                (spine_x, top_y),
                (target_box.center[0], top_y),
                (target_box.center[0], target_box.y),
            ]
        if not route:
            return geometry
        points = ET.SubElement(geometry, "Array", {"as": "points"})
        for x, y in route:
            ET.SubElement(points, "mxPoint", {"x": f"{x:.1f}", "y": f"{y:.1f}"})
        return geometry
    if target.parent not in {"data", "integrations"} or "runtime" not in layout.groups:
        return geometry
    points = ET.SubElement(geometry, "Array", {"as": "points"})
    if source.parent == "runtime":
        corridor_x = layout.groups["runtime"].right + 76.0 + index * 18.0
        detour = runtime_side_detour(layout, edge.source)
        if detour is not None:
            ET.SubElement(points, "mxPoint", {"x": f"{source_box.center[0]:.1f}", "y": f"{detour:.1f}"})
        route_y = detour if detour is not None else source_box.center[1]
        ET.SubElement(points, "mxPoint", {"x": f"{corridor_x:.1f}", "y": f"{route_y:.1f}"})
        ET.SubElement(points, "mxPoint", {"x": f"{corridor_x:.1f}", "y": f"{target_box.center[1]:.1f}"})
        return geometry
    detail_bottom = max(
        (
            box.bottom
            for group_id, box in layout.groups.items()
            if group_id not in {"runtime", "data", "integrations"}
        ),
        default=source_box.bottom,
    )
    bottom_y = detail_bottom + 42.0 + index * 10.0
    side_left = min(
        (
            box.x
            for group_id, box in layout.groups.items()
            if group_id in {"data", "integrations"}
        ),
        default=target_box.x,
    )
    corridor_x = side_left - 62.0 - index * 12.0
    ET.SubElement(points, "mxPoint", {"x": f"{source_box.center[0]:.1f}", "y": f"{bottom_y:.1f}"})
    ET.SubElement(points, "mxPoint", {"x": f"{corridor_x:.1f}", "y": f"{bottom_y:.1f}"})
    ET.SubElement(points, "mxPoint", {"x": f"{corridor_x:.1f}", "y": f"{target_box.center[1]:.1f}"})
    return geometry


def render_drawio(
    architecture: Architecture,
    layout: Layout,
    output: str | Path,
    previous: str | Path | None = None,
    preserve_existing: bool = True,
) -> Path:
    destination = Path(output)
    previous_path = None
    if preserve_existing:
        previous_path = Path(previous) if previous else (destination if destination.exists() else None)
    preserved = read_preserved(previous_path)

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "repo2drawio",
            "agent": "repo2drawio",
            "version": "1",
            "compressed": "false",
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "architecture", "name": architecture.title})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1422",
            "dy": "794",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": f"{max(1169, int(layout.width))}",
            "pageHeight": f"{max(827, int(layout.height))}",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # Boundaries are emitted first so nodes remain visually on top.
    for group in architecture.groups:
        style = _group_style(architecture.sketch, architecture.theme)
        old = preserved.get(group.id)
        generated_label = escape(group.label)
        obj = ET.SubElement(
            root,
            "object",
            {
                "id": f"group-{group.id}",
                "archId": group.id,
                "archType": "group",
                "label": _resolved_label(generated_label, old),
                "generatedLabel": generated_label,
                "generatedStyle": style,
                "evidence": _evidence_text(group.evidence),
            },
        )
        cell = ET.SubElement(
            obj,
            "mxCell",
            {
                "style": _resolved_style(style, old),
                "vertex": "1",
                "parent": "1",
            },
        )
        cell.append(_geometry(layout.groups[group.id], old))

    for node in architecture.nodes:
        style = _node_style(node, architecture.sketch, architecture.theme)
        brand = _display_brand(node, architecture.theme)
        old = preserved.get(node.id)
        label = escape(node.label)
        subtitle = escape(node.subtitle) if node.subtitle else None
        display_label = label if not subtitle else f"<b>{label}</b><br><font style='font-size:12px'>{subtitle}</font>"
        obj = ET.SubElement(
            root,
            "object",
            {
                "id": f"node-{node.id}",
                "archId": node.id,
                "archType": "node",
                "kind": node.kind,
                "icon": _icon_key(node),
                "brand": brand.key if brand else "",
                "group": node.parent or "",
                "label": _resolved_label(display_label, old),
                "generatedLabel": display_label,
                "generatedStyle": style,
                "evidence": _evidence_text(node.evidence),
            },
        )
        cell = ET.SubElement(
            obj,
            "mxCell",
            {
                "style": _resolved_style(style, old),
                "vertex": "1",
                "parent": "1",
            },
        )
        cell.append(_geometry(layout.nodes[node.id], old))

    for edge_index, edge in enumerate(architecture.edges):
        style = _edge_style(architecture.sketch, architecture.theme)
        old = preserved.get(edge.id)
        generated_label = escape(edge.label)
        obj = ET.SubElement(
            root,
            "object",
            {
                "id": f"edge-{edge.id}",
                "archId": edge.id,
                "archType": "edge",
                "label": _resolved_label(generated_label, old),
                "generatedLabel": generated_label,
                "generatedStyle": style,
                "evidence": _evidence_text(edge.evidence),
            },
        )
        cell = ET.SubElement(
            obj,
            "mxCell",
            {
                "style": _resolved_style(style, old),
                "edge": "1",
                "parent": "1",
                "source": f"node-{edge.source}",
                "target": f"node-{edge.target}",
            },
        )
        cell.append(_edge_geometry(architecture, layout, edge, edge_index, old))

    ET.indent(mxfile, space="  ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(mxfile).write(destination, encoding="utf-8", xml_declaration=True)
    return destination
