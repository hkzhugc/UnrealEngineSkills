#!/usr/bin/env python3
"""Phase 2 Planner: Compute the batch plan for module summary generation.

Pure planner — no LLM invocation. Outputs a JSON batch plan that the
calling agent (any LLM client) uses to dispatch sub-agents.

Prerequisites:
    - module_graph.json must exist (run parse_module_graph.py first)

Usage:
    python generate_summaries.py                          # full plan, batch of 5
    python generate_summaries.py --tier 1                 # tier 1 only (10 modules)
    python generate_summaries.py --modules Core,Engine    # specific modules
    python generate_summaries.py --batch-size 3           # smaller batches
    python generate_summaries.py --resume                 # skip existing .md files

    # Submodule mode:
    python generate_summaries.py --submodules --module Renderer --resume
    python generate_summaries.py --submodules --auto --min-files 100 --resume
    python generate_summaries.py --submodules --module Renderer --only PostProcess,Mobile

Output (stdout): JSON batch plan consumed by the orchestrating agent.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from _resolve import find_engine_root, knowledge_dir

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

TIERS = {
    1: [
        'Core', 'CoreUObject', 'Engine', 'RHI', 'RenderCore',
        'Renderer', 'ApplicationCore', 'SlateCore', 'Slate', 'InputCore',
    ],
    2: [
        'NavigationSystem', 'AIModule', 'PhysicsCore', 'Chaos',
        'AnimationCore', 'AnimGraphRuntime', 'Landscape', 'Niagara',
        'UMG', 'MovieScene',
    ],
    3: [
        'UnrealEd', 'BlueprintGraph', 'Kismet', 'PropertyEditor',
        'GraphEditor', 'ContentBrowser', 'Sequencer', 'Persona',
    ],
}


def load_module_graph(graph_path: Path) -> dict:
    """Load module_graph.json and return the modules dict."""
    with open(graph_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('modules', {})


def get_existing_summaries(modules_dir: Path) -> set:
    """Return set of module names that already have .md files."""
    if not modules_dir.is_dir():
        return set()
    return {p.stem for p in modules_dir.glob('*.md')}


def get_existing_submodule_summaries(modules_dir: Path, module_name: str) -> set:
    """Return set of submodule names that already have .md files for a module."""
    subdir = modules_dir / module_name
    if not subdir.is_dir():
        return set()
    return {p.stem for p in subdir.glob('*.md')}


def order_modules(module_names: list, tier: int = None) -> list:
    """Order modules by tier priority, then alphabetically."""
    if tier is not None:
        tier_modules = TIERS.get(tier, [])
        return [m for m in tier_modules if m in module_names]

    ordered = []
    for t in sorted(TIERS.keys()):
        for m in TIERS[t]:
            if m in module_names and m not in ordered:
                ordered.append(m)

    remaining = sorted(m for m in module_names if m not in ordered)
    ordered.extend(remaining)
    return ordered


def main():
    parser = argparse.ArgumentParser(description='Plan batch summary generation for UE4 modules')
    parser.add_argument('--engine-root', type=str, help='Path to engine root')
    parser.add_argument('--tier', type=int, choices=[1, 2, 3, 4], help='Only process this tier')
    parser.add_argument('--modules', type=str, help='Comma-separated module names')
    parser.add_argument('--batch-size', type=int, default=5, help='Modules per batch (default: 5)')
    parser.add_argument('--resume', action='store_true', help='Skip modules that already have .md files')
    parser.add_argument('--output-dir', type=str, help='Override output directory for resume check')
    # Submodule mode arguments
    parser.add_argument('--submodules', action='store_true', help='Generate submodule summary plan')
    parser.add_argument('--module', type=str, help='Single module name for submodule mode')
    parser.add_argument('--auto', action='store_true', help='Auto-detect large modules for submodule mode')
    parser.add_argument('--min-files', type=int, default=100, help='Min files for --auto (default: 100)')
    parser.add_argument('--only', type=str, help='Comma-separated submodule names to include')
    args = parser.parse_args()

    engine_root = Path(args.engine_root) if args.engine_root else find_engine_root()
    engine_dir = engine_root / 'Engine'

    if args.submodules:
        plan_submodule_summaries(args, engine_root, engine_dir)
    else:
        plan_module_summaries(args, engine_root, engine_dir)


def plan_submodule_summaries(args, engine_root: Path, engine_dir: Path):
    """Plan submodule summary generation using detect_submodules."""
    # Import the detection module
    scripts_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(scripts_dir))
    from detect_submodules import detect_submodules, find_module_path, find_large_modules

    modules_dir = Path(args.output_dir) if args.output_dir else knowledge_dir(engine_root) / 'modules'
    graph_path = knowledge_dir(engine_root) / 'module_graph.json'

    # Load module graph for metadata
    module_graph = {}
    if graph_path.exists():
        module_graph = load_module_graph(graph_path)

    # Determine which modules to process
    if args.auto:
        large_modules = find_large_modules(engine_root, args.min_files, graph_path)
        targets = [(name, path) for name, path, _ in large_modules]
    elif args.module:
        names = [n.strip() for n in args.module.split(',')]
        targets = []
        for name in names:
            path = find_module_path(engine_root, name)
            if path:
                targets.append((name, path))
            else:
                print(json.dumps({'warning': f'Module not found: {name}'}),
                      file=sys.stderr)
    elif args.modules:
        # Also support --modules for consistency
        names = [n.strip() for n in args.modules.split(',')]
        targets = []
        for name in names:
            path = find_module_path(engine_root, name)
            if path:
                targets.append((name, path))
    else:
        print(json.dumps({'error': 'Submodule mode requires --module, --modules, or --auto'}))
        sys.exit(1)

    if not targets:
        print(json.dumps({'error': 'No modules found to analyze'}))
        sys.exit(1)

    # Filter submodule names if --only specified
    only_submodules = None
    if args.only:
        only_submodules = {n.strip() for n in args.only.split(',')}

    batch_size = args.batch_size if args.batch_size != 5 else 4  # default 4 for submodules

    all_plans = []

    for module_name, module_path in targets:
        # Run detection
        detection = detect_submodules(module_path)
        submodules = detection.get('submodules', [])

        if not submodules:
            continue

        # Filter by --only
        if only_submodules:
            submodules = [s for s in submodules if s['name'] in only_submodules]

        # Resume: skip existing submodule summaries
        if args.resume:
            existing = get_existing_submodule_summaries(modules_dir, module_name)
            skipped = [s for s in submodules if s['name'] in existing]
            submodules = [s for s in submodules if s['name'] not in existing]
        else:
            skipped = []

        if not submodules:
            continue

        # Get parent module info from graph
        parent_info = module_graph.get(module_name, {})
        parent_module = {
            'name': module_name,
            'path': str(module_path).replace('\\', '/'),
            'type': parent_info.get('type', 'Unknown'),
            'layer': parent_info.get('layer', 0),
        }

        # Split into batches
        batches = []
        for i in range(0, len(submodules), batch_size):
            batches.append(submodules[i:i + batch_size])

        plan = {
            'mode': 'submodules',
            'parent_module': parent_module,
            'total_submodules': len(submodules),
            'total_batches': len(batches),
            'batch_size': batch_size,
            'skipped': [s['name'] for s in skipped],
            'batches': batches,
        }
        all_plans.append(plan)

    # Output
    if len(all_plans) == 1:
        output = all_plans[0]
    else:
        output = {
            'mode': 'submodules',
            'engine_root': str(engine_root).replace('\\', '/'),
            'modules_dir': str(modules_dir).replace('\\', '/'),
            'total_modules': len(all_plans),
            'plans': all_plans,
        }

    output['engine_root'] = str(engine_root).replace('\\', '/')
    output['modules_dir'] = str(modules_dir).replace('\\', '/')

    print(json.dumps(output, indent=2, ensure_ascii=False))


def plan_module_summaries(args, engine_root: Path, engine_dir: Path):
    """Original module summary planning logic."""
    # Load module graph
    graph_path = knowledge_dir(engine_root) / 'module_graph.json'
    if not graph_path.exists():
        print(json.dumps({'error': f'{graph_path} not found. Run parse_module_graph.py first.'}))
        sys.exit(1)

    modules = load_module_graph(graph_path)

    # Determine which modules to process
    if args.modules:
        target_names = [m.strip() for m in args.modules.split(',')]
        target_names = [m for m in target_names if m in modules]
    elif args.tier == 4:
        in_tiers = set()
        for t in (1, 2, 3):
            in_tiers.update(TIERS[t])
        target_names = sorted(m for m in modules if m not in in_tiers)
    elif args.tier:
        target_names = [m for m in TIERS.get(args.tier, []) if m in modules]
    else:
        target_names = list(modules.keys())

    # Order by priority
    ordered = order_modules(target_names, tier=args.tier if args.tier and args.tier != 4 else None)
    if not args.tier and not args.modules:
        ordered = order_modules(target_names)

    # Resume: skip existing
    modules_dir = Path(args.output_dir) if args.output_dir else knowledge_dir(engine_root) / 'modules'
    existing = get_existing_summaries(modules_dir)
    skipped = []

    if args.resume or not args.modules:
        skipped = [m for m in ordered if m in existing]
        ordered = [m for m in ordered if m not in existing]

    # Split into batches
    batches = []
    for i in range(0, len(ordered), args.batch_size):
        batch_modules = ordered[i:i + args.batch_size]
        batch_info = []
        for name in batch_modules:
            info = modules.get(name, {})
            batch_info.append({
                'name': name,
                'path': info.get('path', ''),
                'type': info.get('type', 'Unknown'),
                'layer': info.get('layer', 0),
                'public_deps': info.get('public_deps', [])[:10],
                'private_deps': info.get('private_deps', [])[:10],
            })
        batches.append(batch_info)

    # Output the plan as JSON
    plan = {
        'engine_root': str(engine_root).replace('\\', '/'),
        'modules_dir': str(modules_dir).replace('\\', '/'),
        'total_modules': len(ordered),
        'total_batches': len(batches),
        'batch_size': args.batch_size,
        'skipped': skipped,
        'batches': batches,
    }

    print(json.dumps(plan, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
