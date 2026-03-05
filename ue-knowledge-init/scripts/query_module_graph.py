#!/usr/bin/env python3
"""Query the module graph without loading the full JSON into LLM context.

This script is the primary interface for LLM agents to access module_graph.json.
The full graph is ~727KB / 27K lines — far too large for any context window.
This script loads it in Python and returns only the requested slice.

Usage:
    python query_module_graph.py info Core
    python query_module_graph.py info Core,Engine,RHI
    python query_module_graph.py deps Core
    python query_module_graph.py rdeps Core
    python query_module_graph.py layer 0
    python query_module_graph.py path Engine/Source/Runtime/Renderer
    python query_module_graph.py tree Core --depth 2
    python query_module_graph.py stats
    python query_module_graph.py overview
"""

import argparse
import json
import sys
from pathlib import Path


def find_engine_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / 'Engine' / 'Source').is_dir():
            return parent
    return Path.cwd()


def load_graph(engine_root: Path) -> dict:
    graph_path = engine_root / 'Engine' / '.claude' / 'knowledge' / 'module_graph.json'
    if not graph_path.exists():
        print(f'{{"error": "module_graph.json not found at {graph_path}. Run parse_module_graph.py first."}}')
        sys.exit(1)
    with open(graph_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def cmd_info(modules: dict, names: list):
    """Show full info for specific modules."""
    result = {}
    for name in names:
        if name in modules:
            result[name] = modules[name]
        else:
            result[name] = {"error": "not found"}
    print(json.dumps(result, indent=2))


def cmd_deps(modules: dict, name: str):
    """Show what a module depends on (upstream)."""
    if name not in modules:
        print(json.dumps({"error": f"module '{name}' not found"}))
        return
    m = modules[name]
    result = {
        "module": name,
        "public_deps": m.get("public_deps", []),
        "private_deps": m.get("private_deps", []),
        "circular_deps": m.get("circular_deps", []),
        "dynamic_deps": m.get("dynamic_deps", []),
        "conditions": m.get("conditions", ""),
    }
    print(json.dumps(result, indent=2))


def cmd_rdeps(modules: dict, name: str):
    """Show what depends on a module (downstream / reverse deps)."""
    if name not in modules:
        print(json.dumps({"error": f"module '{name}' not found"}))
        return
    public_dependents = []
    private_dependents = []
    for mod_name, mod_info in modules.items():
        if name in mod_info.get("public_deps", []):
            public_dependents.append(mod_name)
        elif name in mod_info.get("private_deps", []):
            private_dependents.append(mod_name)
    result = {
        "module": name,
        "public_dependents": sorted(public_dependents),
        "private_dependents": sorted(private_dependents),
        "total_dependents": len(public_dependents) + len(private_dependents),
    }
    print(json.dumps(result, indent=2))


def cmd_layer(modules: dict, layer: int):
    """List all modules at a given layer."""
    matches = sorted(
        [(name, info.get("type", "?"))
         for name, info in modules.items()
         if info.get("layer") == layer],
        key=lambda x: x[0]
    )
    result = {
        "layer": layer,
        "count": len(matches),
        "modules": [{"name": n, "type": t} for n, t in matches],
    }
    print(json.dumps(result, indent=2))


def cmd_path(modules: dict, path_prefix: str):
    """Find module(s) whose path matches the given prefix."""
    path_prefix = path_prefix.replace("\\", "/")
    matches = {}
    for name, info in modules.items():
        mod_path = info.get("path", "").replace("\\", "/")
        if mod_path.startswith(path_prefix) or path_prefix in mod_path:
            matches[name] = {
                "path": mod_path,
                "type": info.get("type"),
                "layer": info.get("layer"),
            }
    print(json.dumps(matches, indent=2))


def cmd_tree(modules: dict, name: str, depth: int):
    """Show dependency tree up to given depth."""
    if name not in modules:
        print(json.dumps({"error": f"module '{name}' not found"}))
        return

    visited = set()
    def build_tree(mod_name, current_depth):
        if current_depth > depth or mod_name in visited:
            return None
        visited.add(mod_name)
        if mod_name not in modules:
            return {"name": mod_name, "status": "external"}
        info = modules[mod_name]
        node = {
            "name": mod_name,
            "layer": info.get("layer"),
            "type": info.get("type"),
        }
        if current_depth < depth:
            deps = info.get("public_deps", []) + info.get("private_deps", [])
            children = []
            for d in deps:
                child = build_tree(d, current_depth + 1)
                if child:
                    children.append(child)
            if children:
                node["deps"] = children
        return node

    tree = build_tree(name, 0)
    print(json.dumps(tree, indent=2))


def cmd_stats(data: dict):
    """Show graph statistics."""
    modules = data.get("modules", {})
    metadata = data.get("metadata", {})

    type_counts = {}
    layer_counts = {}
    max_layer = 0
    for info in modules.values():
        t = info.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
        l = info.get("layer", 0)
        layer_counts[l] = layer_counts.get(l, 0) + 1
        max_layer = max(max_layer, l)

    result = {
        "metadata": metadata,
        "by_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "by_layer": {str(k): v for k, v in sorted(layer_counts.items())},
        "max_layer": max_layer,
    }
    print(json.dumps(result, indent=2))


def cmd_overview(modules: dict):
    """Show a compact layer-by-layer overview (names only, key modules highlighted)."""
    layers = {}
    for name, info in modules.items():
        l = info.get("layer", 0)
        if l not in layers:
            layers[l] = []
        layers[l].append(name)

    result = {}
    for l in sorted(layers.keys()):
        names = sorted(layers[l])
        if len(names) > 20:
            result[f"layer_{l}"] = {
                "count": len(names),
                "sample": names[:15],
                "truncated": True,
            }
        else:
            result[f"layer_{l}"] = {
                "count": len(names),
                "modules": names,
            }
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description='Query module_graph.json without loading the full file into LLM context'
    )
    parser.add_argument('--engine-root', type=str, help='Path to engine root')

    sub = parser.add_subparsers(dest='command')

    p_info = sub.add_parser('info', help='Full info for module(s)')
    p_info.add_argument('names', help='Comma-separated module names')

    p_deps = sub.add_parser('deps', help='What a module depends on (upstream)')
    p_deps.add_argument('name', help='Module name')

    p_rdeps = sub.add_parser('rdeps', help='What depends on a module (downstream)')
    p_rdeps.add_argument('name', help='Module name')

    p_layer = sub.add_parser('layer', help='List modules at a layer')
    p_layer.add_argument('number', type=int, help='Layer number')

    p_path = sub.add_parser('path', help='Find module by source path')
    p_path.add_argument('prefix', help='Path prefix to match')

    p_tree = sub.add_parser('tree', help='Dependency tree')
    p_tree.add_argument('name', help='Root module name')
    p_tree.add_argument('--depth', type=int, default=2, help='Max depth (default: 2)')

    p_stats = sub.add_parser('stats', help='Graph statistics')
    p_overview = sub.add_parser('overview', help='Compact layer-by-layer overview')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    engine_root = Path(args.engine_root) if args.engine_root else find_engine_root()
    data = load_graph(engine_root)
    modules = data.get("modules", {})

    if args.command == 'info':
        names = [n.strip() for n in args.names.split(',')]
        cmd_info(modules, names)
    elif args.command == 'deps':
        cmd_deps(modules, args.name)
    elif args.command == 'rdeps':
        cmd_rdeps(modules, args.name)
    elif args.command == 'layer':
        cmd_layer(modules, args.number)
    elif args.command == 'path':
        cmd_path(modules, args.prefix)
    elif args.command == 'tree':
        cmd_tree(modules, args.name, args.depth)
    elif args.command == 'stats':
        cmd_stats(data)
    elif args.command == 'overview':
        cmd_overview(modules)


if __name__ == '__main__':
    main()
