from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from repo2drawio.analyzer import analyze_repository
from repo2drawio.drawio import render_drawio
from repo2drawio.github import (
    ArchiveTooLarge,
    RepositoryError,
    RepositorySnapshot,
    _request,
    fetch_repository,
    parse_github_url,
    snapshot_from_archive,
    snapshot_from_git_tree,
)
from repo2drawio.layout import compute_layout
from repo2drawio.model import load_architecture
from repo2drawio.store import DiagramStore
from repo2drawio.web import create_app


def archive(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for path, content in entries.items():
            zipped.writestr(f"owner-repo-deadbeef/{path}", content)
    return output.getvalue()


class GitHubTests(unittest.TestCase):
    def test_parse_public_repository_url(self) -> None:
        self.assertEqual(("octocat", "Hello-World"), parse_github_url("https://github.com/octocat/Hello-World.git"))

    def test_reject_non_github_or_subpath(self) -> None:
        with self.assertRaises(RepositoryError):
            parse_github_url("https://example.com/owner/repo")
        with self.assertRaises(RepositoryError):
            parse_github_url("https://github.com/owner/repo/issues")

    def test_archive_skips_secrets_and_dependencies(self) -> None:
        snapshot = snapshot_from_archive(
            "owner",
            "repo",
            archive(
                {
                    "README.md": "hello",
                    ".env": "SECRET=value",
                    "src/app.py": "print('safe')",
                    "node_modules/pkg/index.js": "ignored",
                    "tests/test_app.py": "ignored test fixture",
                    "assets/generated.json": "ignored asset",
                }
            ),
        )
        self.assertEqual({"README.md", "src/app.py"}, set(snapshot.files))

    def test_github_token_is_explicit_not_read_from_process_environment(self) -> None:
        self.assertIsNone(_request("https://api.github.com/repos/demo/repo").get_header("Authorization"))
        self.assertEqual(
            "Bearer user-token",
            _request("https://api.github.com/repos/demo/repo", "user-token").get_header("Authorization"),
        )

    def test_large_archive_falls_back_to_selective_api_reader(self) -> None:
        expected = RepositorySnapshot("owner", "repo", "https://github.com/owner/repo", {"README.md": "ok"})
        with (
            patch("repo2drawio.github._download_archive", side_effect=ArchiveTooLarge("large")),
            patch("repo2drawio.github._fetch_repository_via_api", return_value=expected) as api_reader,
        ):
            actual = fetch_repository("https://github.com/owner/repo", token="token", private_access=True)
        self.assertEqual(expected, actual)
        api_reader.assert_called_once_with("owner", "repo", "token", True)

    def test_tree_reader_skips_binary_assets(self) -> None:
        tree = {
            "tree": [
                {"path": "assets/demo.mp4", "type": "blob", "size": 50_000_000, "url": "asset"},
                {"path": "README.md", "type": "blob", "size": 5, "url": "readme"},
                {"path": "docker-compose.yml", "type": "blob", "size": 12, "url": "compose"},
            ]
        }

        def fake_file(owner, name, branch, entry, token, private_access):
            content = {"README.md": b"hello", "docker-compose.yml": b"services: {}"}
            return str(entry["path"]), content[str(entry["path"])]

        with patch("repo2drawio.github._raw_file", side_effect=fake_file):
            snapshot = snapshot_from_git_tree("owner", "repo", "main", tree, token="token")
        self.assertEqual({"README.md", "docker-compose.yml"}, set(snapshot.files))

    def test_archive_prioritizes_architecture_sources_before_file_limit(self) -> None:
        entries = {f"misc/file-{index:04}.py": "value = 1" for index in range(605)}
        entries["backend/app/engine/recommend.py"] = "def recommend():\n    evaluate_conditions()\n"
        snapshot = snapshot_from_archive("owner", "repo", archive(entries))
        self.assertIn("backend/app/engine/recommend.py", snapshot.files)


class AnalyzerTests(unittest.TestCase):
    def test_detects_frontend_backend_and_external_api(self) -> None:
        snapshot = RepositorySnapshot(
            owner="demo",
            name="shop",
            url="https://github.com/demo/shop",
            files={
                "frontend/package.json": json.dumps({"dependencies": {"react": "latest"}}),
                "backend/requirements.txt": "fastapi\npsycopg\nopenai\n",
                "backend/main.py": "from fastapi import FastAPI\nfrom openai import OpenAI\n",
            },
        )
        model = analyze_repository(snapshot)
        labels = {node["label"] for node in model["nodes"]}
        self.assertIn("Web Application", labels)
        self.assertIn("Backend API", labels)
        self.assertIn("OpenAI API", labels)
        connections = {(edge["from"], edge["to"]) for edge in model["edges"]}
        self.assertTrue(any(source.startswith("web-") and target.startswith("api-") for source, target in connections))

    def test_compose_dependencies_become_connections(self) -> None:
        snapshot = RepositorySnapshot(
            owner="demo",
            name="compose",
            url="https://github.com/demo/compose",
            files={
                "docker-compose.yml": "services:\n  api:\n    build: .\n    depends_on: [db]\n  db:\n    image: postgres:16\n",
            },
        )
        model = analyze_repository(snapshot)
        self.assertIn(
            ("compose-api", "compose-db"),
            {(edge["from"], edge["to"]) for edge in model["edges"]},
        )

    def test_semantic_inventory_merges_compose_and_filters_false_externals(self) -> None:
        snapshot = RepositorySnapshot(
            owner="demo",
            name="platform",
            url="https://github.com/demo/platform",
            files={
                "README.md": "React, FastAPI, and MariaDB production application.",
                "docker-compose.yml": (
                    "services:\n"
                    "  app:\n"
                    "    build: .\n"
                    "    depends_on: [ml-server]\n"
                    "    environment:\n"
                    "      ML_API_URL: http://ml-server:8890/predict\n"
                    "      UPSCALE_URL: http://image-worker:8000/upscale\n"
                    "      APP_DB_HOST: database.internal\n"
                    "  ml-server:\n"
                    "    build: ./ml_server\n"
                ),
                "cutout/docker-compose.yml": (
                    "services:\n  image-worker:\n    build: .\n    image: image-worker:latest\n"
                ),
                "frontend/package.json": json.dumps({"dependencies": {"react": "latest"}}),
                "frontend/src/api/client.js": "fetch('/api/recommend')",
                "frontend/e2e/app.spec.ts": "Slack and s3 are only test words",
                "backend/requirements.txt": "fastapi\npymysql\n",
                "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "backend/app/routers/images.py": (
                    "from openai import OpenAI\n"
                    "OPENAI_URL = 'https://api.openai.com/v1/images/generations'\n"
                ),
                "ml_server/requirements.txt": "fastapi\nlightgbm\n",
                "ml_server/app.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "cutout/requirements.txt": "fastapi\nrembg\n",
                "cutout/Dockerfile": 'CMD ["uvicorn", "serve:app"]\n',
                "prototype.html": "s3 and Slack are mock labels",
            },
        )
        model = analyze_repository(snapshot)
        labels = [node["label"] for node in model["nodes"]]
        self.assertEqual(1, labels.count("Backend API"))
        self.assertIn("ML Inference Service", labels)
        self.assertIn("Image Processing Service", labels)
        self.assertIn("MariaDB", labels)
        self.assertIn("OpenAI API", labels)
        self.assertNotIn("Slack", labels)
        self.assertNotIn("Amazon S3", labels)

        ids = {node["label"]: node["id"] for node in model["nodes"]}
        edges = {(edge["from"], edge["to"]): edge["label"] for edge in model["edges"]}
        self.assertEqual("REST API", edges[(ids["Web Application"], ids["Backend API"])])
        self.assertEqual("/predict", edges[(ids["Backend API"], ids["ML Inference Service"])])
        self.assertEqual("/upscale", edges[(ids["Backend API"], ids["Image Processing Service"])])
        self.assertIn((ids["Backend API"], ids["MariaDB"]), edges)

    def test_promotes_rule_ml_chatbot_rag_and_studio_capabilities(self) -> None:
        snapshot = RepositorySnapshot(
            owner="demo",
            name="recommendation-platform",
            url="https://github.com/demo/recommendation-platform",
            files={
                "frontend/package.json": json.dumps({"dependencies": {"react": "latest"}}),
                "backend/requirements.txt": "fastapi\nduckdb\ngoogle-genai\nanthropic\n",
                "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "ml_server/requirements.txt": "fastapi\nlightgbm\n",
                "ml_server/app.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "backend/app/export_voucher/api/router.py": (
                    "@router.post('/recommend')\ndef recommend_route(): pass\n"
                    "@router.post('/ml/categories')\ndef category_route(): pass\n"
                ),
                "backend/app/export_voucher/engine/recommend.py": (
                    "def recommend():\n    evaluate_conditions()\n    prioritize()  # deterministic\n"
                ),
                "backend/app/export_voucher/ml/provider.py": (
                    "class Provider:\n    def predict(self): return fallback()\n"
                ),
                "backend/app/routers/domestic.py": (
                    "@router.post('/domestic/quick')\ndef quick(): return predict_families()\n"
                    "@router.post('/domestic/judge')\ndef judge_route(): return judge()\n"
                ),
                "backend/app/services/domestic.py": "def judge():\n    return eligible_by_rule()\n",
                "backend/app/services/domestic_ml.py": (
                    "def predict_families():\n    return post('/predict/domestic')\n"
                ),
                "backend/app/services/domestic_mvp.py": (
                    "def quick(family_prediction):\n    eligible = _basic_eligible()\n"
                    "    return deterministic(eligible, family_prediction)\n"
                ),
                "backend/app/routers/assistant.py": (
                    "@router.post('/assistant/message')\ndef message(): return answer_message()\n"
                ),
                "backend/app/services/assistant.py": (
                    "def answer_message(context):\n    return understand(context)\n"
                ),
                "backend/app/services/assistant_analytics_runtime.py": (
                    "import duckdb\ndef analytics(): return retrieve_evidence()  # RAG\n"
                ),
                "backend/app/services/assistant_gemini.py": (
                    "from google import genai\nclient = genai.Client()\n"
                ),
                "backend/studio_app/api/studio.py": "def generate(): return pipeline()\n",
                "backend/studio_app/core/service.py": (
                    "def run_pipeline():\n    generate()\n    verify()\n"
                ),
                "backend/studio_app/adapters/claude_llm.py": (
                    "from anthropic import Anthropic\nclient = Anthropic()\n"
                ),
            },
        )
        model = analyze_repository(snapshot)
        ids = {node["label"]: node["id"] for node in model["nodes"]}
        expected = {
            "Voucher Rule Engine",
            "ML Category Predictor",
            "Rule-based Eligibility",
            "ML Family Ranker",
            "Hybrid Recommendation Ranker",
            "AI Chatbot Orchestrator",
            "Analytical RAG",
            "Content Studio Pipeline",
            "DuckDB",
        }
        self.assertTrue(expected.issubset(ids))
        groups = {group["id"]: group["label"] for group in model["groups"]}
        self.assertEqual("Domestic Recommendation", groups["domestic"])
        self.assertEqual("Export Voucher Recommendation", groups["voucher"])
        self.assertEqual("AI Assistant & Retrieval", groups["assistant"])
        self.assertEqual("Content Generation", groups["content"])
        self.assertEqual("Shared Infrastructure & Data", groups["infrastructure"])
        edges = {(edge["from"], edge["to"]): edge["label"] for edge in model["edges"]}
        self.assertEqual(
            "eligible candidates",
            edges[(ids["Rule-based Eligibility"], ids["Hybrid Recommendation Ranker"])],
        )
        self.assertEqual(
            "family scores",
            edges[(ids["ML Family Ranker"], ids["Hybrid Recommendation Ranker"])],
        )
        self.assertEqual(
            "retrieve + analyze",
            edges[(ids["AI Chatbot Orchestrator"], ids["Analytical RAG"])],
        )
        self.assertEqual(
            "read-only SQL",
            edges[(ids["Analytical RAG"], ids["DuckDB"])],
        )
        self.assertEqual(
            "generate content",
            edges[(ids["Content Studio Pipeline"], ids["Anthropic API"])],
        )

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "architecture.json"
            model_path.write_text(json.dumps(model), encoding="utf-8")
            architecture = load_architecture(model_path)
            layout = compute_layout(architecture)
        self.assertLess(layout.groups["runtime"].bottom, layout.groups["domestic"].y)
        self.assertLess(layout.groups["domestic"].bottom, layout.groups["voucher"].y)
        self.assertLess(layout.groups["voucher"].bottom, layout.groups["assistant"].y)
        self.assertLess(layout.groups["assistant"].bottom, layout.groups["content"].y)
        self.assertLess(layout.groups["content"].bottom, layout.groups["infrastructure"].y)
        self.assertGreater(layout.groups["integrations"].x, layout.groups["runtime"].right)
        for node in architecture.nodes:
            if node.parent is None:
                continue
            node_box = layout.nodes[node.id]
            group_box = layout.groups[node.parent]
            self.assertGreaterEqual(node_box.x, group_box.x)
            self.assertGreaterEqual(node_box.y, group_box.y)
            self.assertLessEqual(node_box.right, group_box.right)
            self.assertLessEqual(node_box.bottom, group_box.bottom)


class FakeRunner:
    def __init__(self, store: DiagramStore) -> None:
        self.store = store

        self.last_github_token = None
        self.last_private_access = False
        self.last_theme = None

    def submit(
        self,
        repo_url: str,
        github_token: str | None = None,
        private_access: bool = False,
        theme: str = "brand-logos",
    ):
        parse_github_url(repo_url)
        self.last_github_token = github_token
        self.last_private_access = private_access
        self.last_theme = theme
        job, token = self.store.create(repo_url)
        self.store.update(job.id, status="running", progress=20, message="Testing")
        return self.store.load(job.id).public(), token


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = DiagramStore(self.temporary.name)
        self.runner = FakeRunner(self.store)
        self.client = TestClient(create_app(self.store, self.runner))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_home_and_create_job(self) -> None:
        home = self.client.get("/")
        self.assertEqual(200, home.status_code)
        self.assertIn("Only select repositories", home.text)
        self.assertIn("Contents → Read-only", home.text)
        self.assertIn("personal-access-tokens/new", home.text)
        self.assertIn("Icon Sketch", home.text)
        self.assertIn("Brand Logos", home.text)
        self.assertIn("Classic", home.text)
        self.assertEqual({"status": "ok", "version": "0.12.0"}, self.client.get("/healthz").json())
        response = self.client.post("/api/jobs", json={"repo_url": "https://github.com/octocat/Hello-World"})
        self.assertEqual(202, response.status_code)
        body = response.json()
        self.assertEqual("running", self.client.get(f"/api/jobs/{body['id']}").json()["status"])
        self.assertTrue(body["edit_token"])
        self.assertEqual("brand-logos", self.runner.last_theme)

    def test_classic_theme_is_forwarded_and_unknown_theme_is_rejected(self) -> None:
        response = self.client.post(
            "/api/jobs",
            json={"repo_url": "https://github.com/octocat/Hello-World", "theme": "classic"},
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual("classic", self.runner.last_theme)
        rejected = self.client.post(
            "/api/jobs",
            json={"repo_url": "https://github.com/octocat/Hello-World", "theme": "photo"},
        )
        self.assertEqual(422, rejected.status_code)

    def test_private_pat_is_used_for_job_but_never_persisted(self) -> None:
        response = self.client.post(
            "/api/jobs",
            json={"repo_url": "https://github.com/octocat/private", "github_token": "github_pat_private"},
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual("github_pat_private", self.runner.last_github_token)
        self.assertTrue(self.runner.last_private_access)
        job_id = response.json()["id"]
        self.assertNotIn(
            "github_pat_private",
            (self.store.directory(job_id) / "job.json").read_text(encoding="utf-8"),
        )

    def test_pat_size_is_bounded(self) -> None:
        response = self.client.post(
            "/api/jobs",
            json={"repo_url": "https://github.com/octocat/private", "github_token": "x" * 513},
        )
        self.assertEqual(422, response.status_code)

    def test_save_requires_edit_token_and_valid_drawio(self) -> None:
        job, token = self.store.create("https://github.com/demo/repo")
        directory = self.store.directory(job.id)
        model_path = directory / "architecture.json"
        model_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "title": "Demo",
                    "nodes": [{"id": "app", "label": "App"}],
                    "edges": [],
                }
            ),
            encoding="utf-8",
        )
        architecture = load_architecture(model_path)
        render_drawio(architecture, compute_layout(architecture), directory / "architecture.drawio")
        (directory / "architecture.svg").write_text("<svg></svg>", encoding="utf-8")
        self.store.update(job.id, status="complete", progress=100)
        xml = (directory / "architecture.drawio").read_text(encoding="utf-8")

        denied = self.client.put(f"/api/diagrams/{job.id}", json={"xml": xml})
        self.assertEqual(403, denied.status_code)
        saved = self.client.put(
            f"/api/diagrams/{job.id}",
            json={"xml": xml},
            headers={"X-Edit-Token": token},
        )
        self.assertEqual(200, saved.status_code)


if __name__ == "__main__":
    unittest.main()
