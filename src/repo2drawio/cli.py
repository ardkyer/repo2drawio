from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .drawio import render_drawio
from .layout import compute_layout
from .model import ModelError, load_architecture
from .svg import render_svg


STARTER = {
    "version": 1,
    "title": "My Service Architecture",
    "direction": "LR",
    "sketch": True,
    "theme": "brand-logos",
    "groups": [{"id": "runtime", "label": "Runtime"}],
    "nodes": [
        {"id": "user", "label": "User", "kind": "actor"},
        {"id": "app", "label": "Application", "kind": "service", "parent": "runtime"},
        {"id": "db", "label": "Database", "kind": "database", "parent": "runtime"},
    ],
    "edges": [
        {"id": "user-app", "from": "user", "to": "app", "label": "HTTPS"},
        {"id": "app-db", "from": "app", "to": "db", "label": "read / write"},
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo2drawio",
        description="Render grounded architecture IR as editable Draw.io and SVG files.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate architecture JSON")
    validate.add_argument("input", type=Path)

    render = subparsers.add_parser("render", help="render Draw.io and SVG outputs")
    render.add_argument("input", type=Path)
    render.add_argument("--drawio", type=Path, help="editable .drawio output path")
    render.add_argument("--svg", type=Path, help="SVG preview output path")
    preservation = render.add_mutually_exclusive_group()
    preservation.add_argument(
        "--previous",
        type=Path,
        help="existing .drawio file whose manual layout and styling should be preserved",
    )
    preservation.add_argument(
        "--fresh",
        action="store_true",
        help="ignore an existing .drawio file and regenerate the layout and styling",
    )

    init = subparsers.add_parser("init", help="write a starter architecture.json")
    init.add_argument("output", type=Path, nargs="?", default=Path("architecture.json"))
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "init":
        if args.output.exists():
            print(f"refusing to overwrite existing file: {args.output}", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(STARTER, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(args.output)
        return 0

    architecture = load_architecture(args.input)
    if args.command == "validate":
        print(
            f"valid: {len(architecture.nodes)} nodes, {len(architecture.edges)} edges, "
            f"{len(architecture.groups)} groups"
        )
        return 0

    layout = compute_layout(architecture)
    drawio_path = args.drawio or args.input.with_suffix(".drawio")
    svg_path = args.svg or args.input.with_suffix(".svg")
    render_drawio(
        architecture,
        layout,
        drawio_path,
        previous=args.previous,
        preserve_existing=not args.fresh,
    )
    render_svg(architecture, layout, svg_path)
    print(drawio_path)
    print(svg_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return _run(parser.parse_args(argv))
    except (ModelError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
