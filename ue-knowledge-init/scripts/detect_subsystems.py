#!/usr/bin/env python3
"""Detect submodule boundaries within large UE4 modules.

Uses two complementary methods:
  A) Subdirectory detection: qualifying subdirs in Private/, Public/, Classes/
  B) Filename prefix clustering: CamelCase prefix groups in flat directories

Usage:
    python detect_submodules.py Renderer
    python detect_submodules.py Renderer,Engine,Core
    python detect_submodules.py --auto --min-files 100
    python detect_submodules.py Renderer --min-subdir 5 --min-prefix 6
    python detect_submodules.py --auto --save-index

Output (stdout): JSON with detected submodules per module.
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from _resolve import find_engine_root, knowledge_dir

SOURCE_EXTS = {'.h', '.hpp', '.cpp', '.c', '.inl'}
SOURCE_ROOTS = ('Private', 'Public', 'Classes')
SKIP_DIRS = {'Tests', 'Test', 'ThirdParty'}
PLATFORM_DIRS = {
    'Windows', 'Win32', 'Win64', 'Mac', 'Linux', 'IOS', 'Android',
    'PS4', 'XboxOne', 'Switch', 'Lumin', 'HoloLens',
}

# Minimum total files for a module to have submodules detected
MIN_MODULE_FILES = 30


def count_source_files(directory: Path) -> int:
    """Count source files in a directory (non-recursive)."""
    if not directory.is_dir():
        return 0
    return sum(1 for f in directory.iterdir() if f.is_file() and f.suffix in SOURCE_EXTS)


def count_source_files_recursive(directory: Path) -> int:
    """Count source files in a directory recursively."""
    if not directory.is_dir():
        return 0
    count = 0
    for f in directory.rglob('*'):
        if f.is_file() and f.suffix in SOURCE_EXTS:
            count += 1
    return count


def get_key_files(directory: Path, max_files: int = 5) -> list:
    """Get a sample of source files from a directory, preferring headers."""
    files = []
    for f in directory.rglob('*'):
        if f.is_file() and f.suffix in SOURCE_EXTS:
            files.append(f)
    # Sort: headers first, then by name
    files.sort(key=lambda f: (0 if f.suffix in ('.h', '.hpp') else 1, f.name))
    return files[:max_files]


def extract_camel_prefix(stem: str) -> str:
    """Extract the first CamelCase token from a filename stem.

    Examples:
        MobileBasePassRendering -> Mobile
        PostProcessBokehDOF    -> PostProcess  (2 tokens to get meaningful prefix)
        FSceneRenderer         -> Scene  (skip F prefix)
    """
    # Strip common UE prefixes
    clean = stem
    if len(clean) > 1 and clean[0] in ('F', 'U', 'A', 'I', 'E', 'T') and clean[1].isupper():
        clean = clean[1:]

    tokens = re.findall(r'[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z0-9]*', clean)
    if not tokens:
        return ''
    return tokens[0]


def detect_subdirectory_submodules(module_path: Path, min_subdir: int) -> list:
    """Method A: Detect submodules from subdirectories in source roots.

    Scans Private/, Public/, Classes/ for subdirectories with >= min_subdir
    source files. Same-named dirs across roots merge into one submodule.
    """
    submodules = {}  # name -> {dirs: [], file_count: 0, files: []}

    for root_name in SOURCE_ROOTS:
        root_dir = module_path / root_name
        if not root_dir.is_dir():
            continue

        for subdir in sorted(root_dir.iterdir()):
            if not subdir.is_dir():
                continue
            name = subdir.name

            # Skip test and third-party dirs
            if name in SKIP_DIRS:
                continue

            # Skip platform dirs unless they have many files
            if name in PLATFORM_DIRS:
                fc = count_source_files_recursive(subdir)
                if fc < 20:
                    continue

            fc = count_source_files_recursive(subdir)
            if fc < min_subdir:
                continue

            rel_dir = f'{root_name}/{name}'
            if name not in submodules:
                submodules[name] = {
                    'dirs': [],
                    'file_count': 0,
                    'files': [],
                }
            submodules[name]['dirs'].append(rel_dir)
            submodules[name]['file_count'] += fc
            submodules[name]['files'].extend(get_key_files(subdir, 3))

    result = []
    for name, info in sorted(submodules.items(), key=lambda x: -x[1]['file_count']):
        key_files = sorted(set(
            str(f.relative_to(module_path)).replace('\\', '/')
            for f in info['files']
        ))[:5]
        result.append({
            'name': name,
            'detection': 'subdirectory',
            'file_count': info['file_count'],
            'source_dirs': info['dirs'],
            'key_files': key_files,
        })

    return result


def detect_prefix_cluster_submodules(module_path: Path, min_prefix: int,
                                     subdir_names: set) -> list:
    """Method B: Detect submodules from filename prefix clustering.

    For files directly in Private/ (not in subdirectories), extract CamelCase
    prefix and cluster. Clusters with >= min_prefix files become submodules.

    subdir_names: set of names already claimed by subdirectory detection,
    used for deduplication.
    """
    prefix_files = {}  # prefix -> [files]

    for root_name in SOURCE_ROOTS:
        root_dir = module_path / root_name
        if not root_dir.is_dir():
            continue

        for f in sorted(root_dir.iterdir()):
            if not f.is_file() or f.suffix not in SOURCE_EXTS:
                continue

            prefix = extract_camel_prefix(f.stem)
            if not prefix or len(prefix) < 2:
                continue

            if prefix not in prefix_files:
                prefix_files[prefix] = []
            prefix_files[prefix].append(f)

    result = []
    for prefix, files in sorted(prefix_files.items(), key=lambda x: -len(x[1])):
        if len(files) < min_prefix:
            continue

        # Skip if subdirectory detection already covers this name
        if prefix in subdir_names:
            continue

        key_files = sorted(
            str(f.relative_to(module_path)).replace('\\', '/')
            for f in files
        )[:5]

        # Determine which source dirs contain these files
        source_dirs = sorted(set(
            str(f.parent.relative_to(module_path)).replace('\\', '/')
            for f in files
        ))

        result.append({
            'name': prefix,
            'detection': 'prefix_cluster',
            'file_count': len(files),
            'source_dirs': source_dirs,
            'key_files': key_files,
        })

    return result


def detect_submodules(module_path: Path, min_subdir: int = 5,
                      min_prefix: int = 6) -> dict:
    """Run both detection methods and merge results for a single module."""
    module_path = Path(module_path)
    if not module_path.is_dir():
        return {'error': f'Module path not found: {module_path}'}

    # Count total source files
    total_files = count_source_files_recursive(module_path)
    if total_files < MIN_MODULE_FILES:
        return {
            'module_name': module_path.name,
            'module_path': str(module_path).replace('\\', '/'),
            'total_files': total_files,
            'submodules': [],
            'uncategorized_file_count': total_files,
            'note': f'Module has < {MIN_MODULE_FILES} files, submodule detection skipped',
        }

    # Method A: subdirectory detection
    subdir_submodules = detect_subdirectory_submodules(module_path, min_subdir)
    subdir_names = {s['name'] for s in subdir_submodules}

    # Method B: prefix clustering (excludes names already found by subdirs)
    prefix_submodules = detect_prefix_cluster_submodules(
        module_path, min_prefix, subdir_names
    )

    # Merge: subdirectory wins over prefix cluster on name overlap (already handled)
    all_submodules = subdir_submodules + prefix_submodules
    all_submodules.sort(key=lambda s: -s['file_count'])

    # Calculate uncategorized count
    categorized = sum(s['file_count'] for s in all_submodules)
    uncategorized = max(0, total_files - categorized)

    return {
        'module_name': module_path.name,
        'module_path': str(module_path).replace('\\', '/'),
        'total_files': total_files,
        'submodules': all_submodules,
        'uncategorized_file_count': uncategorized,
    }


def find_module_path(engine_root: Path, module_name: str) -> Path:
    """Find the source directory for a module by name.

    Searches common UE source locations.
    """
    search_roots = [
        engine_root / 'Engine' / 'Source' / 'Runtime',
        engine_root / 'Engine' / 'Source' / 'Editor',
        engine_root / 'Engine' / 'Source' / 'Developer',
        engine_root / 'Engine' / 'Source' / 'Programs',
        engine_root / 'Engine' / 'Source' / 'ThirdParty',
    ]

    # Also search plugins
    plugins_dir = engine_root / 'Engine' / 'Plugins'
    if plugins_dir.is_dir():
        for plugin_root in plugins_dir.rglob('Source'):
            if plugin_root.is_dir():
                search_roots.append(plugin_root)

    for root in search_roots:
        if not root.is_dir():
            continue
        candidate = root / module_name
        if candidate.is_dir():
            return candidate
        # Some modules are nested (e.g., Engine/Source/Runtime/Core)
        for d in root.rglob(module_name):
            if d.is_dir() and d.name == module_name:
                # Verify it looks like a module (has Private/ or Public/ or a .Build.cs)
                if ((d / 'Private').is_dir() or (d / 'Public').is_dir() or
                        list(d.glob('*.Build.cs'))):
                    return d

    return None


def find_large_modules(engine_root: Path, min_files: int,
                       graph_path: Path = None) -> list:
    """Find all modules with >= min_files source files.

    If graph_path exists, use it for module paths. Otherwise scan the filesystem.
    """
    modules = []

    if graph_path and graph_path.exists():
        with open(graph_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for name, info in data.get('modules', {}).items():
            mod_path = engine_root / info.get('path', '')
            if mod_path.is_dir():
                fc = count_source_files_recursive(mod_path)
                if fc >= min_files:
                    modules.append((name, mod_path, fc))
    else:
        # Scan filesystem
        for source_type in ('Runtime', 'Editor', 'Developer'):
            source_dir = engine_root / 'Engine' / 'Source' / source_type
            if not source_dir.is_dir():
                continue
            for d in sorted(source_dir.iterdir()):
                if not d.is_dir():
                    continue
                if (d / 'Private').is_dir() or (d / 'Public').is_dir():
                    fc = count_source_files_recursive(d)
                    if fc >= min_files:
                        modules.append((d.name, d, fc))

    modules.sort(key=lambda x: -x[2])
    return modules


def main():
    parser = argparse.ArgumentParser(
        description='Detect submodule boundaries within UE4 modules'
    )
    parser.add_argument('modules', nargs='?', type=str,
                        help='Comma-separated module names (or use --auto)')
    parser.add_argument('--auto', action='store_true',
                        help='Auto-detect all large modules')
    parser.add_argument('--min-files', type=int, default=100,
                        help='Minimum files for --auto detection (default: 100)')
    parser.add_argument('--min-subdir', type=int, default=5,
                        help='Minimum files in a subdirectory to qualify (default: 5)')
    parser.add_argument('--min-prefix', type=int, default=6,
                        help='Minimum files with same prefix to qualify (default: 6)')
    parser.add_argument('--engine-root', type=str,
                        help='Path to engine root')
    parser.add_argument('--save-index', action='store_true',
                        help='Write subsystem_index.json to knowledge dir')
    args = parser.parse_args()

    if not args.modules and not args.auto:
        parser.print_help()
        sys.exit(1)

    engine_root = Path(args.engine_root) if args.engine_root else find_engine_root()
    graph_path = knowledge_dir(engine_root) / 'module_graph.json'

    # Determine which modules to analyze
    if args.auto:
        module_list = find_large_modules(engine_root, args.min_files, graph_path)
        targets = [(name, path) for name, path, _ in module_list]
    else:
        names = [n.strip() for n in args.modules.split(',')]
        targets = []
        for name in names:
            path = find_module_path(engine_root, name)
            if path:
                targets.append((name, path))
            else:
                print(json.dumps({'error': f'Module not found: {name}'}),
                      file=sys.stderr)

    if not targets:
        print(json.dumps({'error': 'No modules to analyze'}))
        sys.exit(1)

    # Run detection
    results = []
    for name, path in targets:
        result = detect_submodules(path, args.min_subdir, args.min_prefix)
        results.append(result)

    # Output
    if len(results) == 1:
        print(json.dumps(results[0], indent=2, ensure_ascii=False))
    else:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    # Save index if requested
    if args.save_index:
        index = {
            'metadata': {
                'generated_at': str(date.today()),
                'min_subdir': args.min_subdir,
                'min_prefix': args.min_prefix,
            },
            'modules': {},
        }
        for r in results:
            if 'error' in r:
                continue
            name = r['module_name']
            index['modules'][name] = {
                'submodules': [s['name'] for s in r.get('submodules', [])],
                'file_count': r.get('total_files', 0),
            }

        kn_dir = knowledge_dir(engine_root)
        kn_dir.mkdir(parents=True, exist_ok=True)
        index_path = kn_dir / 'subsystem_index.json'
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        print(f'\nIndex written to: {index_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
