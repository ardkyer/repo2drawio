# Public repository audit

Run: 2026-09-06. Ten distinct public repositories, pinned by commit. Downloaded source
was read as data; no repository code or dependencies were executed. All ten produced
JSON models. **This is not a 100% accuracy result.** The sample is small, deliberately
includes negative cases, and is not representative of all GitHub repositories.

| Repository / pinned commit | Nodes / edges | Assessment |
| --- | --- | --- |
| [FastAPI template](https://github.com/fastapi/full-stack-fastapi-template/tree/cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7) | 6 / 4 | Useful dependency draft; proxy routing and overrides missing |
| [Docker voting app](https://github.com/dockersamples/example-voting-app/tree/63e9150ca17af4ed05880d4245e486481f73fcb4) | 7 / 7 | Useful Compose inventory; dependencies are not message-flow arrows; seed profile included |
| [Flower](https://github.com/mher/flower/tree/e6cf8ef78776098bf8d3f1674056fc00dd62e388) | 6 / 7 | Useful Compose inventory; Celery flow and Prometheus scraping missing |
| [Flask RealWorld](https://github.com/gothinkster/flask-realworld-example-app/tree/4b95fb2227dfeb5dd1a45d89b2bf48630b93fd28) | 2 / 1 | Too sparse; generic application fallback misses the actual architecture |
| [React RealWorld](https://github.com/gothinkster/react-redux-realworld-example-app/tree/ee72eba4056392c95a27bc48d385d3f54ba38a18) | 2 / 1 | Detects frontend only; external backend not shown |
| [Flask Docker image](https://github.com/tiangolo/uwsgi-nginx-flask-docker/tree/b52206b6bc1b38a45095ce651ac5aadba46de87a) | 2 / 1 | Partial; image/example repository is not an entire application |
| [Streamlit Hello](https://github.com/streamlit/hello/tree/4bb3b195b4dbb148d4e4a4cb384599e206b0aaab) | 2 / 1 | Too sparse; Streamlit application not recognized in this layout |
| [Awesome Compose](https://github.com/docker/awesome-compose/tree/30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562) | 43 / 45 | Misleading as one system; independent examples and service names become conflated |
| [Flask library](https://github.com/pallets/flask/tree/d318b683471101618febed18996405ad26462110) | 3 / 2 | Misleading: library/development metadata interpreted as a deployed backend |
| [HTTPX library](https://github.com/encode/httpx/tree/b5addb64f0161ff6bfe94c124ef76f6a1fba5254) | 2 / 1 | Generic fallback is not a useful library architecture |

The first three are bundled as examples with no manual node, edge, label, or layout
corrections. Assessments are an engineering review of output and supporting manifests/
Compose files, not independent maintainer validation or full call-graph verification.

## Changes prompted by the audit

The FastAPI template originally had two PostgreSQL nodes: a Compose service and a
client-dependency node. The analyzer now reuses an unambiguous, already-connected
Compose database. A regression test verifies that an unrelated second database is
not merged. Inferred user entry is no longer labeled as a proven HTTPS connection.
Other Compose services with published ports are shown as additional possible entries.

## Reproduce

```bash
python -m pip install -e '.[dev]'
python scripts/benchmark_public_repos.py
python scripts/build_launch_examples.py
```

Snapshots are cached in ignored `.launch-audit/` and reused on reruns. An empty cache
resolves the then-current HEAD; use the pinned links above to compare against this
report. Timings from cached reruns are not download or user-facing latency measurements.
The audit uses GitHub's public commit endpoint plus a pinned codeload archive, rather
than the web reader's default-branch ZIP/API fallback. The web API needs a separate
end-to-end generation check before deployment.

An initial candidate, `testdrivenio/fastapi-docker-tdd`, returned HTTP 404 and was
replaced with Docker's voting app. It is not counted among the ten successful reads.
