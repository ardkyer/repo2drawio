# Contributing

Start with an issue describing an incorrect or missing component. Include a **public**
repository URL, commit SHA, expected relationship, and the source file that supports it.
Do not attach private repository content, PATs, connection strings, or edit-link tokens.

Install Python 3.11+ and run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
```

Detection changes should include a small synthetic regression fixture. Distinguish
dependency evidence from a verified call or runtime flow; do not infer a service merely
because its name appears in documentation. Prefer framework-independent detection over
rules tailored to one repository. Keep rendering deterministic and preserve editability.

For the public smoke audit, run `python scripts/benchmark_public_repos.py`.
It reads remote public code without executing it and caches pinned snapshots locally.
Generation success is not an accuracy score. New examples need source attribution,
their commit SHA, and an honest account of what the diagram misses.
