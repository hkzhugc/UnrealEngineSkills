#!/usr/bin/env python3
"""Phase 3: Map shader files to their C++ counterparts.

Deterministic — no LLM required. Scans Engine/Shaders/ for .usf/.ush,
extracts #include directives, and finds C++ files that reference each shader.

Usage:
    python generate_shader_map.py                       # auto-detect engine root
    python generate_shader_map.py --engine-root /path   # explicit root
    python generate_shader_map.py --dry-run              # print stats, don't write
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

from _resolve import find_engine_root, knowledge_dir


_RE_INCLUDE = re.compile(r'#include\s+"([^"]+)"')

# Matches IMPLEMENT_GLOBAL_SHADER_PARAMETER_STRUCT, IMPLEMENT_GLOBAL_SHADER, etc.
_RE_SHADER_IMPL = re.compile(
    r'(?:IMPLEMENT_GLOBAL_SHADER|IMPLEMENT_MATERIAL_SHADER_TYPE|'
    r'IMPLEMENT_SHADER_TYPE|DECLARE_GLOBAL_SHADER)\s*\([^,]*,\s*'
    r'(?:TEXT\()?\s*"([^"]+)"',
)

# Matches: FShaderFilenameToContentMap with virtual path references
_RE_SHADER_PATH = re.compile(r'"/Engine/([^"]+\.(?:usf|ush))"')


def extract_includes(text: str) -> list:
    """Extract #include file references from shader source."""
    includes = []
    for match in _RE_INCLUDE.finditer(text):
        inc = match.group(1)
        # Normalize path separators
        inc = inc.replace('\\', '/')
        includes.append(inc)
    return includes


def find_cpp_counterparts(shader_basename: str, engine_dir: Path, cpp_shader_refs: dict) -> list:
    """Find C++ files that are counterparts to a given shader file.

    Uses:
    1. Filename stem matching (e.g., Foo.usf -> Foo.cpp / Foo.h)
    2. Pre-built index of C++ files that reference shader virtual paths
    """
    stem = Path(shader_basename).stem
    results = set()

    # Strategy 1: Search for matching C++ filename
    for ext in ('.cpp', '.h'):
        pattern = str(engine_dir / 'Source' / '**' / f'{stem}{ext}')
        for match in glob.glob(pattern, recursive=True):
            rel = os.path.relpath(match, str(engine_dir)).replace('\\', '/')
            results.add(rel)

    # Strategy 2: Check pre-built reference index
    # Shader virtual paths look like "/Engine/Private/Foo.usf"
    for virtual_path, cpp_files in cpp_shader_refs.items():
        if shader_basename in virtual_path or stem in virtual_path:
            for cf in cpp_files:
                results.add(cf)

    return sorted(results)


def guess_module(cpp_path: str) -> str:
    """Guess which module a C++ file belongs to based on path."""
    parts = cpp_path.replace('\\', '/').split('/')
    # Typical: Source/Runtime/Renderer/Private/Foo.cpp
    # We want "Renderer"
    for i, part in enumerate(parts):
        if part in ('Runtime', 'Editor', 'Developer') and i + 1 < len(parts):
            return parts[i + 1]
        if part == 'Plugins' and i + 2 < len(parts):
            return parts[i + 2] if i + 2 < len(parts) else parts[i + 1]
    return 'Unknown'


def build_cpp_shader_reference_index(engine_dir: Path) -> dict:
    """Scan key C++ directories for shader path references.

    Returns dict mapping virtual_path -> [cpp_file_rel_paths]
    """
    refs = defaultdict(list)

    # Directories most likely to contain shader references
    search_dirs = [
        engine_dir / 'Source' / 'Runtime' / 'Renderer',
        engine_dir / 'Source' / 'Runtime' / 'RenderCore',
        engine_dir / 'Source' / 'Runtime' / 'RHI',
        engine_dir / 'Source' / 'Runtime' / 'Engine',
        engine_dir / 'Source' / 'Runtime' / 'Landscape',
        engine_dir / 'Source' / 'Runtime' / 'Niagara',
    ]

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for cpp_path in glob.glob(str(search_dir / '**' / '*.cpp'), recursive=True):
            try:
                with open(cpp_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except Exception:
                continue

            rel_cpp = os.path.relpath(cpp_path, str(engine_dir)).replace('\\', '/')

            # Find IMPLEMENT_GLOBAL_SHADER / IMPLEMENT_SHADER_TYPE references
            for match in _RE_SHADER_IMPL.finditer(text):
                virtual_path = match.group(1)
                refs[virtual_path].append(rel_cpp)

            # Find direct string references to shader paths
            for match in _RE_SHADER_PATH.finditer(text):
                virtual_path = match.group(1)
                refs[virtual_path].append(rel_cpp)

    # Deduplicate
    for key in refs:
        refs[key] = sorted(set(refs[key]))

    return dict(refs)


def main():
    parser = argparse.ArgumentParser(description='Map UE4 shader files to C++ counterparts')
    parser.add_argument('--engine-root', type=str, help='Path to engine root')
    parser.add_argument('--dry-run', action='store_true', help='Print stats without writing')
    parser.add_argument('--output', type=str, help='Override output path')
    args = parser.parse_args()

    engine_root = Path(args.engine_root) if args.engine_root else find_engine_root()
    engine_dir = engine_root / 'Engine'

    shaders_dir = engine_dir / 'Shaders'
    if not shaders_dir.is_dir():
        print(f'ERROR: Shaders directory not found at {shaders_dir}', file=sys.stderr)
        sys.exit(1)

    print(f'Engine root: {engine_root}')

    # Step 1: Find all shader files
    shader_files = []
    for ext in ('*.usf', '*.ush'):
        shader_files.extend(glob.glob(str(shaders_dir / '**' / ext), recursive=True))

    print(f'Found {len(shader_files)} shader files')

    # Step 2: Build C++ reference index
    print('Building C++ shader reference index (scanning renderer sources)...')
    cpp_refs = build_cpp_shader_reference_index(engine_dir)
    print(f'Found {len(cpp_refs)} shader virtual path references in C++')

    # Step 3: Process each shader
    shaders = {}
    for sf in sorted(shader_files):
        try:
            rel_path = os.path.relpath(sf, str(shaders_dir)).replace('\\', '/')

            with open(sf, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()

            includes = extract_includes(text)

            # Find C++ counterparts
            cpp_files = find_cpp_counterparts(rel_path, engine_dir, cpp_refs)

            # Determine module from C++ counterparts
            module = 'Unknown'
            if cpp_files:
                module = guess_module(cpp_files[0])

            shaders[rel_path] = {
                'module': module,
                'cpp_files': cpp_files,
                'includes': includes,
            }
        except Exception as e:
            print(f'  Warning: {sf}: {e}', file=sys.stderr)

    # Stats
    with_cpp = sum(1 for s in shaders.values() if s['cpp_files'])
    modules_seen = set(s['module'] for s in shaders.values() if s['module'] != 'Unknown')
    print(f'\nShaders with C++ counterparts: {with_cpp}/{len(shaders)}')
    print(f'Modules referenced: {len(modules_seen)}')

    ext_counts = defaultdict(int)
    for p in shaders:
        ext = Path(p).suffix
        ext_counts[ext] += 1
    for ext, count in sorted(ext_counts.items()):
        print(f'  {ext}: {count}')

    if args.dry_run:
        print('\n[DRY RUN] Would write shader_map.json')
        # Print a few examples
        print('\nSample entries:')
        for name, info in list(shaders.items())[:5]:
            print(f'  {name}: module={info["module"]}, cpp={info["cpp_files"][:2]}')
        return

    # Build output
    output = {
        'metadata': {
            'generated_at': str(date.today()),
            'total_shaders': len(shaders),
        },
        'shaders': shaders,
    }

    out_path = Path(args.output) if args.output else knowledge_dir(engine_root) / 'shader_map.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f'\nWrote {out_path} ({len(shaders)} shader entries)')


if __name__ == '__main__':
    main()
