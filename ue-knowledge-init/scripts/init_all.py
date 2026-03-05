#!/usr/bin/env python3
"""Master orchestrator: run deterministic phases and generate the
summary batch plan for the calling LLM agent to dispatch.

Phases 1 & 3 are fully automated (no LLM). Phase 2 outputs a JSON
batch plan that the LLM agent executes via sub-agents. Phase 2b
generates subsystem summaries for large modules.

Usage:
    python init_all.py                    # run phases 1, 2, 2b & 3
    python init_all.py --phase 1          # only module graph
    python init_all.py --phase 2 --tier 1 # only plan tier-1 summaries
    python init_all.py --phase 2b         # only plan subsystem summaries
    python init_all.py --phase 3          # only shader map
    python init_all.py --resume           # skip completed phases
"""

import argparse
import subprocess
import sys
from pathlib import Path


def find_engine_root() -> Path:
    """Walk up from script location to find the engine root."""
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / 'Engine' / 'Source').is_dir():
            return parent
    return Path.cwd()


def phase_complete(engine_dir: Path, phase) -> bool:
    """Check whether a phase's output already exists."""
    knowledge_dir = engine_dir / '.claude' / 'knowledge'
    if phase == 1:
        return (knowledge_dir / 'module_graph.json').exists()
    elif phase == 2:
        modules_dir = knowledge_dir / 'modules'
        if not modules_dir.is_dir():
            return False
        return len(list(modules_dir.glob('*.md'))) >= 10  # at least tier 1
    elif phase == '2b':
        modules_dir = knowledge_dir / 'modules'
        if not modules_dir.is_dir():
            return False
        # Complete if at least one module has a subsystem subdirectory with .md files
        for d in modules_dir.iterdir():
            if d.is_dir() and list(d.glob('*.md')):
                return True
        return False
    elif phase == 3:
        return (knowledge_dir / 'shader_map.json').exists()
    return False


def run_script(script_name: str, extra_args: list, engine_root: Path) -> bool:
    """Run a phase script, returning True on success."""
    scripts_dir = (
        engine_root / 'Engine' / '.claude' / 'skills' /
        'ue-knowledge-init' / 'scripts'
    )
    script_path = scripts_dir / script_name

    if not script_path.exists():
        print(f'  ERROR: Script not found: {script_path}')
        return False

    cmd = [sys.executable, str(script_path), '--engine-root', str(engine_root)]
    cmd.extend(extra_args)

    print(f'  Running: {" ".join(cmd)}')
    try:
        result = subprocess.run(cmd, timeout=1800)  # 30 min max
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f'  ERROR: {script_name} timed out')
        return False
    except Exception as e:
        print(f'  ERROR: {e}')
        return False


def main():
    parser = argparse.ArgumentParser(description='UE Knowledge Graph - Full Initialization')
    parser.add_argument('--engine-root', type=str, help='Path to engine root')
    parser.add_argument('--phase', type=str, choices=['1', '2', '2b', '3'],
                        help='Run only this phase')
    parser.add_argument('--tier', type=int, choices=[1, 2, 3, 4], help='Tier for phase 2')
    parser.add_argument('--modules', type=str, help='Comma-separated modules for phase 2')
    parser.add_argument('--batch-size', type=int, default=5, help='Batch size for phase 2')
    parser.add_argument('--min-files', type=int, default=100, help='Min files for phase 2b auto-detection')
    parser.add_argument('--resume', action='store_true', help='Skip completed phases')
    args = parser.parse_args()

    engine_root = Path(args.engine_root) if args.engine_root else find_engine_root()
    engine_dir = engine_root / 'Engine'

    # Pre-flight
    if not (engine_dir / 'Source' / 'Runtime' / 'Core' / 'Core.Build.cs').exists():
        print(f'ERROR: Engine root not found at {engine_root}')
        print('Use --engine-root to specify the correct path.')
        sys.exit(1)

    print(f'Engine root: {engine_root}')
    print(f'Knowledge dir: {engine_dir / ".claude" / "knowledge"}')

    # Determine which phases to run
    if args.phase:
        phases = [int(args.phase) if args.phase != '2b' else '2b']
    else:
        phases = [1, 2, '2b', 3]

    results = {}

    for phase in phases:
        print(f'\n{"="*60}')
        print(f'Phase {phase}')
        print(f'{"="*60}')

        if args.resume and phase_complete(engine_dir, phase):
            print(f'  Phase {phase} already complete, skipping.')
            results[phase] = 'skipped'
            continue

        if phase == 1:
            ok = run_script('parse_module_graph.py', [], engine_root)
            results[phase] = 'ok' if ok else 'FAILED'

        elif phase == 2:
            # Phase 2 is LLM-driven: we only generate the batch plan here.
            # The calling agent reads the JSON output and dispatches sub-agents.
            extra = ['--resume']
            if args.tier:
                extra.extend(['--tier', str(args.tier)])
            if args.modules:
                extra.extend(['--modules', args.modules])
            extra.extend(['--batch-size', str(args.batch_size)])
            print('  Phase 2 generates a batch plan (JSON on stdout).')
            print('  The LLM agent must dispatch sub-agents for each batch.')
            print('  ---')
            ok = run_script('generate_summaries.py', extra, engine_root)
            results[phase] = 'plan-ready' if ok else 'FAILED'

        elif phase == '2b':
            # Phase 2b: subsystem summaries for large modules
            extra = ['--subsystems', '--auto', '--resume',
                     '--min-files', str(args.min_files)]
            extra.extend(['--batch-size', str(args.batch_size)])
            print('  Phase 2b generates a subsystem batch plan (JSON on stdout).')
            print('  The LLM agent must dispatch sub-agents for each batch.')
            print('  ---')
            ok = run_script('generate_summaries.py', extra, engine_root)
            results[phase] = 'plan-ready' if ok else 'FAILED'

        elif phase == 3:
            ok = run_script('generate_shader_map.py', [], engine_root)
            results[phase] = 'ok' if ok else 'FAILED'

        print(f'  Phase {phase}: {results[phase]}')

    # Summary
    print(f'\n{"="*60}')
    print('Summary')
    print(f'{"="*60}')
    for phase, status in sorted(results.items(), key=lambda x: str(x[0])):
        label = {
            1: 'Module graph',
            2: 'Summaries (batch plan)',
            '2b': 'Subsystem summaries (batch plan)',
            3: 'Shader map',
        }[phase]
        print(f'  Phase {phase} ({label}): {status}')

    if any(v == 'FAILED' for v in results.values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
