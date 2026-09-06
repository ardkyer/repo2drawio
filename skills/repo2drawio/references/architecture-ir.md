# Architecture IR

`architecture.json` is the semantic source used to regenerate editable and preview files.

## Top-level fields

- `version`: currently `1`.
- `title`: diagram title.
- `direction`: `LR`, `RL`, `TB`, or `BT`.
- `sketch`: enables Draw.io sketch styling.
- `theme`: `brand-logos` for embedded technology marks, `icon-sketch` for semantic vector-icon
  cards, or `classic` for compact native shapes.
- `groups`: visual system boundaries.
- `nodes`: independently editable components.
- `edges`: directed relationships between nodes.

The complete machine-readable contract is `schema/architecture.schema.json` in the
repo2drawio repository.

## Stable IDs

Choose semantic IDs such as `edge-api-orders-db` or `service-checkout`, not array indexes,
coordinates, or filenames. The renderer uses these IDs to match generated elements to an
existing Draw.io file and preserve human changes.

IDs must start with a letter and may contain letters, digits, dots, colons, underscores,
and hyphens. IDs are globally unique across groups, nodes, and edges.

## Evidence

Repository-derived groups, nodes, and edges should include at least one evidence item:

```json
{
  "path": "docker-compose.yml",
  "line": 42,
  "note": "app calls the internal prediction service"
}
```

Use repository-relative paths. Keep the note short and factual. Never include secret values.

## Optional positions

Normally omit `position` and let the renderer lay out the graph. Add it only for a curated
example or when the user explicitly requests a fixed composition:

```json
"position": { "x": 640, "y": 320, "width": 240, "height": 92 }
```

After the first render, prefer moving elements in Draw.io. Subsequent renders preserve those
manual coordinates.
