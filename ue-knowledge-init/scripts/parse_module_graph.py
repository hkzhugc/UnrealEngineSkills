#!/usr/bin/env python3
"""Phase 1: Parse all Build.cs files and produce module_graph.json.

Deterministic — no LLM required. Extracts module names, dependencies,
types, and computes topological layers with cycle detection.

Usage:
    python parse_module_graph.py                       # auto-detect engine root
    python parse_module_graph.py --engine-root /path   # explicit root
    python parse_module_graph.py --dry-run              # print stats, don't write
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Dependency extraction regexes
# ---------------------------------------------------------------------------

# Matches: .AddRange(new string[] { "A", "B", "C" })
_RE_ADD_RANGE = re.compile(
    r'(\w+)\.AddRange\s*\(\s*new\s+string\s*\[\s*\]\s*\{([^}]*)\}',
    re.DOTALL,
)

# Matches: .Add("ModuleName")
_RE_ADD_SINGLE = re.compile(
    r'(\w+)\.Add\s*\(\s*"([^"]+)"\s*\)',
)

# Matches: AddEngineThirdPartyPrivateStaticDependencies(Target, "A", "B", ...)
_RE_THIRD_PARTY = re.compile(
    r'AddEngineThirdPartyPrivateStaticDependencies\s*\(\s*Target\s*,([^)]+)\)',
    re.DOTALL,
)

# Extract quoted strings from a comma-separated list
_RE_QUOTED = re.compile(r'"([^"]+)"')

# Detect conditional blocks
_RE_CONDITION = re.compile(
    r'if\s*\(\s*Target\.(Type|Platform|bBuildEditor)\s*[!=]=\s*\S+',
)

# Category field names → our JSON key
_FIELD_MAP = {
    'PublicDependencyModuleNames': 'public_deps',
    'PrivateDependencyModuleNames': 'private_deps',
    'CircularlyReferencedDependentModules': 'circular_deps',
    'DynamicallyLoadedModuleNames': 'dynamic_deps',
}


def find_engine_root() -> Path:
    """Walk up from script location to find the engine root (contains Engine/)."""
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / 'Engine' / 'Source').is_dir():
            return parent
    return Path.cwd()


def classify_type(rel_path: str) -> str:
    """Classify module type from its relative path."""
    rel = rel_path.replace('\\', '/')
    if '/ThirdParty/' in rel:
        return 'ThirdParty'
    if '/Runtime/' in rel:
        return 'Runtime'
    if '/Editor/' in rel:
        return 'Editor'
    if '/Developer/' in rel:
        return 'Developer'
    if '/Programs/' in rel:
        return 'Program'
    if '/Plugins/' in rel:
        return 'Plugin'
    return 'Unknown'


def extract_deps(text: str) -> dict:
    """Extract all dependency lists from Build.cs source text."""
    deps = {
        'public_deps': [],
        'private_deps': [],
        'circular_deps': [],
        'dynamic_deps': [],
    }

    # AddRange patterns
    for match in _RE_ADD_RANGE.finditer(text):
        field_name = match.group(1)
        values_str = match.group(2)
        modules = _RE_QUOTED.findall(values_str)
        key = _FIELD_MAP.get(field_name)
        if key and modules:
            deps[key].extend(modules)

    # Single .Add("X") patterns
    for match in _RE_ADD_SINGLE.finditer(text):
        field_name = match.group(1)
        module = match.group(2)
        key = _FIELD_MAP.get(field_name)
        if key:
            deps[key].append(module)

    # Third-party static deps
    for match in _RE_THIRD_PARTY.finditer(text):
        modules = _RE_QUOTED.findall(match.group(1))
        deps['private_deps'].extend(modules)

    # Deduplicate while preserving order
    for key in deps:
        seen = set()
        unique = []
        for m in deps[key]:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        deps[key] = unique

    return deps


def extract_conditions(text: str) -> str:
    """Return a brief note about conditional dependencies if any."""
    conditions = set()
    for match in _RE_CONDITION.finditer(text):
        conditions.add(match.group(0).strip())
    if not conditions:
        return ''
    return '; '.join(sorted(conditions))


def module_name_from_path(build_cs_path: str) -> str:
    """Extract module name from the Build.cs filename."""
    basename = os.path.basename(build_cs_path)
    # Handle both cases: Core.Build.cs and CEF3.build.cs (Windows glob is case-insensitive)
    # Use case-insensitive replacement
    name = re.sub(r'\.build\.cs$', '', basename, flags=re.IGNORECASE)
    return name


def compute_layers(modules: dict) -> dict:
    """Compute topological layers. Handles cycles by grouping cycle members.

    Returns a dict mapping module name -> layer number.
    """
    # Build adjacency from public + private deps (excluding circular)
    all_deps = {}
    for name, info in modules.items():
        # Only consider deps that are actually in our module set
        deps = set()
        for d in info.get('public_deps', []) + info.get('private_deps', []):
            if d in modules:
                deps.add(d)
        all_deps[name] = deps

    # Tarjan's SCC to find cycles
    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = set()
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in all_deps.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for v in modules:
        if v not in index:
            strongconnect(v)

    # Map each module to its SCC id
    scc_id = {}
    for i, scc in enumerate(sccs):
        for m in scc:
            scc_id[m] = i

    # Build SCC-level DAG
    scc_deps = defaultdict(set)
    for name, deps in all_deps.items():
        sid = scc_id[name]
        for d in deps:
            did = scc_id.get(d)
            if did is not None and did != sid:
                scc_deps[sid].add(did)

    # Compute layer for each SCC via BFS
    scc_layer = {}

    def get_scc_layer(sid, visited=None):
        if sid in scc_layer:
            return scc_layer[sid]
        if visited is None:
            visited = set()
        if sid in visited:
            return 0  # safety: shouldn't happen after SCC collapse
        visited.add(sid)
        if not scc_deps[sid]:
            scc_layer[sid] = 0
        else:
            scc_layer[sid] = max(
                get_scc_layer(d, visited) for d in scc_deps[sid]
            ) + 1
        return scc_layer[sid]

    for sid in range(len(sccs)):
        get_scc_layer(sid)

    # Map back to modules
    layers = {}
    for name in modules:
        sid = scc_id.get(name, 0)
        layers[name] = scc_layer.get(sid, 0)

    return layers


def get_git_commit(engine_root: Path) -> str:
    """Get short git commit hash."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, cwd=str(engine_root),
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


def main():
    parser = argparse.ArgumentParser(description='Parse UE4 Build.cs files into module_graph.json')
    parser.add_argument('--engine-root', type=str, help='Path to engine root (auto-detected if omitted)')
    parser.add_argument('--dry-run', action='store_true', help='Print stats without writing')
    parser.add_argument('--output', type=str, help='Override output path')
    args = parser.parse_args()

    engine_root = Path(args.engine_root) if args.engine_root else find_engine_root()
    engine_dir = engine_root / 'Engine'

    if not (engine_dir / 'Source' / 'Runtime' / 'Core' / 'Core.Build.cs').exists():
        print(f'ERROR: Cannot find Core.Build.cs under {engine_dir}', file=sys.stderr)
        print('Use --engine-root to specify the correct path.', file=sys.stderr)
        sys.exit(1)

    print(f'Engine root: {engine_root}')

    # Discover all Build.cs files
    patterns = [
        str(engine_dir / 'Source' / '**' / '*.Build.cs'),
        str(engine_dir / 'Plugins' / '**' / '*.Build.cs'),
    ]
    build_files = []
    for pattern in patterns:
        build_files.extend(glob.glob(pattern, recursive=True))

    print(f'Found {len(build_files)} Build.cs files')

    # Parse each file
    modules = {}
    errors = []
    for bf in build_files:
        try:
            name = module_name_from_path(bf)
            rel_path = os.path.relpath(os.path.dirname(bf), str(engine_root))
            rel_path = rel_path.replace('\\', '/')

            with open(bf, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()

            deps = extract_deps(text)
            conditions = extract_conditions(text)
            mod_type = classify_type(rel_path)

            modules[name] = {
                'path': rel_path,
                'type': mod_type,
                'public_deps': deps['public_deps'],
                'private_deps': deps['private_deps'],
                'circular_deps': deps['circular_deps'],
                'dynamic_deps': deps['dynamic_deps'],
                'layer': 0,  # computed below
                'conditions': conditions,
                'last_updated': str(date.today()),
            }
        except Exception as e:
            errors.append(f'{bf}: {e}')

    if errors:
        print(f'\nWarnings ({len(errors)} files had issues):')
        for err in errors[:10]:
            print(f'  {err}')
        if len(errors) > 10:
            print(f'  ... and {len(errors) - 10} more')

    # Compute layers
    print('Computing topological layers...')
    layers = compute_layers(modules)
    for name in modules:
        modules[name]['layer'] = layers.get(name, 0)

    max_layer = max(layers.values()) if layers else 0
    print(f'Layer range: 0-{max_layer}')

    # Stats
    type_counts = defaultdict(int)
    for m in modules.values():
        type_counts[m['type']] += 1
    print('\nModule counts by type:')
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f'  {t}: {c}')

    # Layer 0 modules
    layer0 = sorted(n for n, l in layers.items() if l == 0)
    print(f'\nLayer 0 ({len(layer0)} modules): {", ".join(layer0[:15])}{"..." if len(layer0) > 15 else ""}')

    if args.dry_run:
        print('\n[DRY RUN] Would write module_graph.json')
        return

    # Build output
    git_commit = get_git_commit(engine_root)
    output = {
        'metadata': {
            'engine_version': '4.26',
            'generated_at': str(date.today()),
            'total_modules': len(modules),
            'git_commit': git_commit,
        },
        'modules': dict(sorted(modules.items())),
    }

    out_path = Path(args.output) if args.output else engine_dir / '.claude' / 'knowledge' / 'module_graph.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f'\nWrote {out_path} ({len(modules)} modules)')


if __name__ == '__main__':
    main()
