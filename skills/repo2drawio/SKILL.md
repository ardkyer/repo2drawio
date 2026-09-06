---
name: repo2drawio
description: Analyze software repositories and create or update evidence-backed architecture diagrams as editable Draw.io files plus SVG previews. Use for system, container, deployment, data-flow, or integration diagrams grounded in code and infrastructure. Do not use for generic illustration or non-software flowcharts.
metadata:
  short-description: Create editable architecture diagrams from repositories
---

# Repo2Drawio

Create an architecture model grounded in inspected repository evidence, then use the
`repo2drawio` CLI for deterministic validation and rendering. The editable `.drawio`
file is the human workspace; the JSON model is the semantic source of truth.

## Workflow

1. Inspect the repository's own instructions first. Read architecture-bearing files such
   as README files, manifests, Compose/Terraform files, entry points, routers, database
   adapters, and deployment configuration. Do not open secret files merely to discover
   integrations.
2. Create or update `docs/architecture/architecture.json`. Use stable semantic IDs that
   survive file moves, and add file/line evidence for every repository-derived node and
   edge. User-supplied planned components may omit evidence.
3. Read [the IR reference](references/architecture-ir.md) when authoring or changing the
   model.
4. Validate and render:

   ```bash
   repo2drawio validate docs/architecture/architecture.json
   repo2drawio render docs/architecture/architecture.json \
     --drawio docs/architecture/architecture.drawio \
     --svg docs/architecture/architecture.svg
   ```

5. If the `.drawio` file already exists, render it in place. Stable IDs preserve manual
   geometry, style, and label overrides while semantic additions and removals follow the
   JSON model.
6. Inspect the SVG preview and the generated Draw.io XML. Confirm that labels are readable,
   boundaries contain their intended nodes, arrows have correct direction, and every
   non-obvious relationship has evidence.

## Grounding rules

- Never copy components from a visual reference unless the repository or user supplies
  evidence for them.
- Prefer a legible high-level view over a complete dependency dump.
- Keep runtime flow separate from deployment flow when combining them would be ambiguous.
- Do not expose credentials, connection strings, private hostnames, or tokens in labels or
  evidence notes.
- Preserve existing human edits by default. Replace them only when the user explicitly asks
  to regenerate the layout or styling.
