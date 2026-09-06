from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from repo2drawio.drawio import _display_brand, _icon_key, render_drawio
from repo2drawio.layout import compute_layout
from repo2drawio.model import ModelError, Node, load_architecture
from repo2drawio.svg import render_svg


BASE = {
    "version": 1,
    "title": "Test Architecture",
    "direction": "LR",
    "sketch": True,
    "groups": [{"id": "runtime", "label": "Runtime"}],
    "nodes": [
        {"id": "user", "label": "User", "kind": "actor"},
        {
            "id": "api",
            "label": "API",
            "kind": "service",
            "parent": "runtime",
            "evidence": [{"path": "app.py", "line": 12}],
        },
    ],
    "edges": [
        {
            "id": "user-api",
            "from": "user",
            "to": "api",
            "label": "HTTPS",
            "evidence": [{"path": "app.py", "line": 20}],
        }
    ],
}


class Repo2DrawioTests(unittest.TestCase):
    def write_model(self, directory: Path, data: dict | None = None) -> Path:
        path = directory / "architecture.json"
        path.write_text(json.dumps(data or BASE), encoding="utf-8")
        return path

    def test_load_and_render_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            architecture = load_architecture(self.write_model(directory))
            layout = compute_layout(architecture)
            drawio = render_drawio(architecture, layout, directory / "architecture.drawio")
            svg = render_svg(architecture, layout, directory / "architecture.svg")

            root = ET.parse(drawio).getroot()
            objects = {obj.get("archId"): obj for obj in root.iter("object")}
            self.assertEqual({"runtime", "user", "api", "user-api"}, set(objects))
            self.assertEqual("app.py:12", objects["api"].get("evidence"))
            self.assertIn("Test Architecture", svg.read_text(encoding="utf-8"))

    def test_icon_sketch_theme_embeds_portable_vector_icons(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            themed = json.loads(json.dumps(BASE))
            themed["theme"] = "icon-sketch"
            architecture = load_architecture(self.write_model(directory, themed))
            layout = compute_layout(architecture)
            drawio = render_drawio(architecture, layout, directory / "architecture.drawio")
            svg = render_svg(architecture, layout, directory / "architecture.svg")

            objects = {obj.get("archId"): obj for obj in ET.parse(drawio).getroot().iter("object")}
            style = objects["api"].find("mxCell").get("style")
            self.assertIn("shape=label", style)
            self.assertIn("image=data:image/svg+xml", style)
            preview = svg.read_text(encoding="utf-8")
            self.assertIn('data-theme="icon-sketch"', preview)
            self.assertIn('data-icon="server"', preview)

    def test_brand_logo_theme_embeds_detected_technology_svg(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            themed = json.loads(json.dumps(BASE))
            themed["theme"] = "brand-logos"
            themed["nodes"][1]["subtitle"] = "FastAPI"
            architecture = load_architecture(self.write_model(directory, themed))
            layout = compute_layout(architecture)
            logo = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
            with patch("repo2drawio.drawio.fetch_brand_svg", return_value=logo):
                drawio = render_drawio(architecture, layout, directory / "architecture.drawio")
                svg = render_svg(architecture, layout, directory / "architecture.svg")

            objects = {obj.get("archId"): obj for obj in ET.parse(drawio).getroot().iter("object")}
            self.assertEqual("fastapi", objects["api"].get("brand"))
            node_style = objects["api"].find("mxCell").get("style")
            edge_style = objects["user-api"].find("mxCell").get("style")
            group_style = objects["runtime"].find("mxCell").get("style")
            self.assertIn("image=data:image/svg+xml", node_style)
            self.assertIn("fillColor=#ffffff", node_style)
            self.assertNotIn("sketch=1", node_style)
            self.assertIn("rounded=0", edge_style)
            self.assertNotIn("sketch=1", edge_style)
            self.assertNotIn("sketch=1", group_style)
            preview = svg.read_text(encoding="utf-8")
            self.assertIn('data-theme="brand-logos"', preview)
            self.assertIn('data-brand="fastapi"', preview)
            self.assertNotIn('stroke-dasharray="5 3"', preview)

    def test_brand_logo_theme_uses_role_specific_pictograms_for_domain_nodes(self) -> None:
        cases = {
            "ML Family Ranker": "rank",
            "Hybrid Recommendation Ranker": "merge",
            "Rule-based Eligibility": "eligibility",
            "ML Category Predictor": "category",
            "Voucher Rule Engine": "rules",
            "AI Chatbot Orchestrator": "chat",
            "Analytical RAG": "rag",
            "Content Studio Pipeline": "content",
            "ML Inference Service": "inference",
            "Image Processing Service": "image",
        }
        for index, (label, expected) in enumerate(cases.items()):
            with self.subTest(label=label):
                node = Node(id=f"node-{index}", label=label, kind="model", subtitle="FastAPI")
                self.assertEqual(expected, _icon_key(node))
                self.assertIsNone(_display_brand(node, "brand-logos"))

        backend = Node(id="backend", label="Backend API", kind="service", subtitle="FastAPI")
        self.assertEqual("fastapi", _display_brand(backend, "brand-logos").key)
        voucher_rules = Node(
            id="voucher-rules",
            label="Voucher Rule Engine",
            kind="model",
            subtitle="Deterministic subcategory rules",
        )
        self.assertEqual("rules", _icon_key(voucher_rules))

    def test_semantic_pictogram_is_embedded_in_drawio_and_svg(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            themed = json.loads(json.dumps(BASE))
            themed["theme"] = "brand-logos"
            themed["nodes"][1].update(
                {"label": "AI Chatbot Orchestrator", "kind": "model", "subtitle": "FastAPI"}
            )
            architecture = load_architecture(self.write_model(directory, themed))
            layout = compute_layout(architecture)
            drawio = render_drawio(architecture, layout, directory / "architecture.drawio")
            svg = render_svg(architecture, layout, directory / "architecture.svg")

            api = next(
                obj for obj in ET.parse(drawio).getroot().iter("object") if obj.get("archId") == "api"
            )
            self.assertEqual("chat", api.get("icon"))
            self.assertEqual("", api.get("brand"))
            self.assertIn("image=data:image/svg+xml", api.find("mxCell").get("style") or "")
            preview = svg.read_text(encoding="utf-8")
            self.assertIn('data-icon="chat" data-brand=""', preview)

    def test_unknown_theme_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            broken = json.loads(json.dumps(BASE))
            broken["theme"] = "photo"
            with self.assertRaisesRegex(ModelError, "theme"):
                load_architecture(self.write_model(directory, broken))

    def test_round_trip_preserves_manual_geometry_style_and_label(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            model_path = self.write_model(directory)
            architecture = load_architecture(model_path)
            layout = compute_layout(architecture)
            output = render_drawio(architecture, layout, directory / "architecture.drawio")

            tree = ET.parse(output)
            for obj in tree.getroot().iter("object"):
                if obj.get("archId") != "api":
                    continue
                obj.set("label", "Human API Label")
                cell = obj.find("mxCell")
                assert cell is not None
                cell.set("style", (cell.get("style") or "") + "fillColor=#ff0000;")
                geometry = cell.find("mxGeometry")
                assert geometry is not None
                geometry.set("x", "777")
                geometry.set("y", "333")
            tree.write(output, encoding="utf-8", xml_declaration=True)

            changed = json.loads(model_path.read_text(encoding="utf-8"))
            changed["nodes"][1]["label"] = "Generated API v2"
            model_path.write_text(json.dumps(changed), encoding="utf-8")
            updated = load_architecture(model_path)
            render_drawio(updated, compute_layout(updated), output)

            api = next(obj for obj in ET.parse(output).getroot().iter("object") if obj.get("archId") == "api")
            cell = api.find("mxCell")
            assert cell is not None
            geometry = cell.find("mxGeometry")
            assert geometry is not None
            self.assertEqual("Human API Label", api.get("label"))
            self.assertIn("fillColor=#ff0000", cell.get("style") or "")
            self.assertEqual("777", geometry.get("x"))
            self.assertEqual("333", geometry.get("y"))

    def test_generated_label_updates_when_not_manually_changed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            model_path = self.write_model(directory)
            architecture = load_architecture(model_path)
            output = render_drawio(architecture, compute_layout(architecture), directory / "architecture.drawio")

            changed = json.loads(model_path.read_text(encoding="utf-8"))
            changed["nodes"][1]["label"] = "API v2"
            model_path.write_text(json.dumps(changed), encoding="utf-8")
            updated = load_architecture(model_path)
            render_drawio(updated, compute_layout(updated), output)

            api = next(obj for obj in ET.parse(output).getroot().iter("object") if obj.get("archId") == "api")
            self.assertEqual("API v2", api.get("label"))

    def test_fresh_render_discards_manual_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            model_path = self.write_model(directory)
            architecture = load_architecture(model_path)
            layout = compute_layout(architecture)
            output = render_drawio(architecture, layout, directory / "architecture.drawio")

            tree = ET.parse(output)
            api = next(obj for obj in tree.getroot().iter("object") if obj.get("archId") == "api")
            geometry = api.find("mxCell/mxGeometry")
            assert geometry is not None
            geometry.set("x", "999")
            tree.write(output, encoding="utf-8", xml_declaration=True)

            render_drawio(architecture, layout, output, preserve_existing=False)
            api = next(obj for obj in ET.parse(output).getroot().iter("object") if obj.get("archId") == "api")
            geometry = api.find("mxCell/mxGeometry")
            assert geometry is not None
            self.assertNotEqual("999", geometry.get("x"))

    def test_vertical_direction_places_successor_below_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            vertical = json.loads(json.dumps(BASE))
            vertical["direction"] = "TB"
            architecture = load_architecture(self.write_model(directory, vertical))
            layout = compute_layout(architecture)
            self.assertGreater(layout.nodes["api"].y, layout.nodes["user"].y)

    def test_grouped_layout_keeps_boundaries_separate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            grouped = {
                "version": 1,
                "title": "Grouped",
                "direction": "LR",
                "groups": [
                    {"id": "runtime", "label": "Runtime"},
                    {"id": "data", "label": "Data"},
                    {"id": "integrations", "label": "External"},
                ],
                "nodes": [
                    {"id": "user", "label": "User", "kind": "actor"},
                    {"id": "web", "label": "Web", "kind": "service", "parent": "runtime"},
                    {"id": "api", "label": "API", "kind": "service", "parent": "runtime"},
                    {"id": "db", "label": "DB", "kind": "database", "parent": "data"},
                    {"id": "llm", "label": "LLM", "kind": "external", "parent": "integrations"},
                ],
                "edges": [
                    {"id": "user-web", "from": "user", "to": "web"},
                    {"id": "web-api", "from": "web", "to": "api"},
                    {"id": "api-db", "from": "api", "to": "db"},
                    {"id": "api-llm", "from": "api", "to": "llm"},
                ],
            }
            architecture = load_architecture(self.write_model(directory, grouped))
            layout = compute_layout(architecture)

            def overlaps(left, right) -> bool:
                return not (
                    left.right <= right.x
                    or right.right <= left.x
                    or left.bottom <= right.y
                    or right.bottom <= left.y
                )

            group_boxes = list(layout.groups.values())
            for index, left in enumerate(group_boxes):
                for right in group_boxes[index + 1 :]:
                    self.assertFalse(overlaps(left, right))

            output = render_drawio(architecture, layout, directory / "grouped.drawio")
            routed = list(ET.parse(output).getroot().iter("Array"))
            self.assertEqual(2, len(routed))

    def test_unknown_edge_endpoint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            broken = json.loads(json.dumps(BASE))
            broken["edges"][0]["to"] = "missing"
            with self.assertRaisesRegex(ModelError, "unknown target"):
                load_architecture(self.write_model(directory, broken))

    def test_duplicate_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            broken = json.loads(json.dumps(BASE))
            broken["nodes"][1]["id"] = "user"
            with self.assertRaisesRegex(ModelError, "globally unique"):
                load_architecture(self.write_model(directory, broken))

    def test_unknown_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            broken = json.loads(json.dumps(BASE))
            broken["nodes"][0]["colour"] = "blue"
            with self.assertRaisesRegex(ModelError, "unknown fields"):
                load_architecture(self.write_model(directory, broken))


if __name__ == "__main__":
    unittest.main()
