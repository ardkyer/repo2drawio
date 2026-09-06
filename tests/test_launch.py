import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from repo2drawio.admission import CapacityError, RateLimiter
from repo2drawio.analyzer import analyze_repository
from repo2drawio.github import RepositorySnapshot
from repo2drawio.layout import Box, Layout, compute_layout, runtime_side_detour
from repo2drawio.model import load_architecture
from repo2drawio.store import DiagramStore
from repo2drawio.web import JobRunner, create_app


class LaunchTests(unittest.TestCase):
    def test_example_actor_has_clear_runtime_gutter(self):
        example = Path(__file__).parents[1] / "src/repo2drawio/static/examples/fastapi.json"
        architecture = load_architecture(example)
        layout = compute_layout(architecture)
        for node in architecture.nodes:
            if node.parent is None:
                self.assertLess(layout.nodes[node.id].right, layout.groups["runtime"].x)

    def test_support_edge_detour_avoids_peer_but_not_a_blocked_escape(self):
        layout = Layout(nodes={"source": Box(0, 0, 100, 80), "peer": Box(150, 0, 100, 80)},
                        groups={"runtime": Box(0, 0, 300, 200)}, width=500, height=400)
        self.assertEqual(224, runtime_side_detour(layout, "source"))
        layout.nodes["below"] = Box(0, 100, 100, 80)
        self.assertIsNone(runtime_side_detour(layout, "source"))

    def test_rate_window_recovers_and_client_map_is_bounded(self):
        limiter = RateLimiter(limit=2, window=60, max_clients=1)
        with patch("repo2drawio.admission.time.monotonic", return_value=0):
            self.assertTrue(limiter.allow("one"))
            self.assertTrue(limiter.allow("one"))
            self.assertFalse(limiter.allow("one"))
            self.assertFalse(limiter.allow("two"))
        with patch("repo2drawio.admission.time.monotonic", return_value=61):
            self.assertTrue(limiter.allow("two"))
            self.assertEqual(1, len(limiter.clients))

    def test_capacity_rejection_does_not_create_job(self):
        with tempfile.TemporaryDirectory() as root:
            store = DiagramStore(root)
            runner = JobRunner(store, workers=1)
            runner.max_pending = 1
            runner._submitted.add("in-progress")
            with self.assertRaises(CapacityError):
                runner.submit("https://github.com/demo/app")
            self.assertEqual([], list(Path(root).iterdir()))
            runner._submitted.clear()
            runner.max_jobs = 1
            store.create("https://github.com/demo/old")
            with self.assertRaises(CapacityError):
                runner.submit("https://github.com/demo/new")
            self.assertEqual(1, len(list(Path(root).glob("*/job.json"))))
            runner.executor.shutdown(wait=True)

    def test_public_demo_rejects_pat_and_rate_limit_is_http_429(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"REPO2DRAWIO_ALLOW_PRIVATE": "false", "REPO2DRAWIO_RATE_LIMIT": "1"}):
            store = DiagramStore(root)
            runner = JobRunner(store)
            with TestClient(create_app(store, runner)) as client:
                self.assertFalse(client.get("/api/config").json()["allow_private"])
                response = client.post("/api/jobs", json={"repo_url": "https://github.com/demo/app", "github_token": "private-token"})
                self.assertEqual(422, response.status_code)
                with patch.object(runner, "submit", side_effect=CapacityError("busy")):
                    self.assertEqual(503, client.post("/api/jobs", json={"repo_url": "https://github.com/demo/app"}).status_code)
                    response = client.post("/api/jobs", json={"repo_url": "https://github.com/demo/app"})
                    self.assertEqual(429, response.status_code)
                    self.assertEqual("60", response.headers["Retry-After"])
                self.assertEqual([], list(Path(root).iterdir()))
            runner.executor.shutdown(wait=True)

    def test_examples_are_instant_and_never_create_jobs(self):
        with tempfile.TemporaryDirectory() as root:
            store = DiagramStore(root)
            runner = JobRunner(store)
            with TestClient(create_app(store, runner)) as client:
                for key in ("fastapi", "voting", "flower"):
                    self.assertEqual(200, client.get(f"/examples/{key}").status_code)
                    result = client.get(f"/api/examples/{key}")
                    self.assertEqual(200, result.status_code)
                    self.assertIn("<mxfile", result.json()["xml"])
                    self.assertEqual(40, len(result.json()["commit"]))
                    self.assertFalse(result.json()["manually_corrected"])
                self.assertEqual(404, client.get("/api/examples/unknown").status_code)
                self.assertEqual([], list(Path(root).iterdir()))
            runner.executor.shutdown(wait=True)

    def test_database_client_reuses_only_connected_compose_database(self):
        snapshot = RepositorySnapshot("demo", "app", "https://github.com/demo/app", {
            "backend/requirements.txt": "fastapi\npsycopg\n",
            "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
            "compose.yml": "services:\n  api:\n    build: ./backend\n    depends_on: [db]\n  db:\n    image: postgres:16\n  reporting:\n    image: postgres:16\n",
        })
        model = analyze_repository(snapshot)
        databases = [n for n in model["nodes"] if n["label"] == "PostgreSQL"]
        self.assertEqual(2, len(databases))
        self.assertEqual({"compose-db", "compose-reporting"}, {n["id"] for n in databases})
        db_edges = [e for e in model["edges"] if e["to"] == "compose-db"]
        self.assertTrue(db_edges)
        self.assertFalse(any(e["to"] == "compose-reporting" for e in model["edges"]))


if __name__ == "__main__":
    unittest.main()
