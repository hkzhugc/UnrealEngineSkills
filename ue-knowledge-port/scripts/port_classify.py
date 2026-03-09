"""port_classify.py — Classify UE modules for knowledge-graph porting.

Compares source engine (original) vs target engine (modded) by scanning
source files in each module, computing change rates, and outputting a JSON
plan consumed by the ue-knowledge-port skill's LLM dispatch phase.

Usage:
    python port_classify.py --source D:/UE4.26/UnrealEngine
    python port_classify.py --source D:/UE4.26/UnrealEngine --tier 1
    python port_classify.py --source D:/UE4.26/UnrealEngine --modules Core,Engine,Renderer
    python port_classify.py --source D:/UE4.26/UnrealEngine --target D:/MyProject
    python port_classify.py --source D:/UE4.26/UnrealEngine \\
        --source-agent-dir .claude --target-agent-dir .codebuddy
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: import _resolve.py from ue-knowledge-init/scripts/
# ---------------------------------------------------------------------------
_init_scripts = (
    Path(__file__).resolve().parent.parent.parent
    / "ue-knowledge-init"
    / "scripts"
)
sys.path.insert(0, str(_init_scripts))

try:
    from _resolve import find_engine_root, agent_dir_name, knowledge_dir
except ImportError as exc:
    sys.exit(
        f"ERROR: Cannot import _resolve.py from {_init_scripts}\n"
        f"  Make sure ue-knowledge-init/scripts/_resolve.py exists.\n"
        f"  Original error: {exc}"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE_EXTENSIONS = {".h", ".cpp", ".c", ".inl"}
SOURCE_SUBDIRS = ("Public", "Private", "Classes")
SIZE_DIFF_THRESHOLD = 0.10          # 10% size difference → modified
TIER1_MODULES = {
    "Core", "CoreUObject", "Engine", "RHI", "RenderCore", "Renderer",
    "ApplicationCore", "SlateCore", "Slate", "InputCore",
}

CATEGORY_THRESHOLDS = {
    "unchanged": 0.05,
    "minor":     0.30,
    "major":     0.70,
    # > 0.70  → rewritten
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def source_knowledge_dir(source_root: Path, source_agent_dir: Optional[str]) -> Path:
    """Resolve knowledge dir on the source side.

    If --source-agent-dir was given, use it directly.  Otherwise scan
    Engine/ for a hidden directory that contains a knowledge/ sub-dir.
    """
    if source_agent_dir:
        return source_root / "Engine" / source_agent_dir / "knowledge"

    engine = source_root / "Engine"
    if engine.is_dir():
        try:
            for d in sorted(engine.iterdir()):
                if d.is_dir() and d.name.startswith(".") and (d / "knowledge").is_dir():
                    return d / "knowledge"
        except PermissionError:
            pass

    # Fallback
    return source_root / "Engine" / ".claude" / "knowledge"


def find_module_dirs(engine_root: Path) -> Dict[str, Path]:
    """Return {ModuleName: path} for all modules under Engine/Source."""
    modules: Dict[str, Path] = {}
    src = engine_root / "Engine" / "Source"
    if not src.is_dir():
        return modules

    # Walk up to depth-3: Source/{layer}/{module}/
    for layer_dir in src.iterdir():
        if not layer_dir.is_dir():
            continue
        for mod_dir in layer_dir.iterdir():
            if mod_dir.is_dir():
                modules[mod_dir.name] = mod_dir

    return modules


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def scan_source_files(module_path: Path) -> Dict[str, int]:
    """Return {relative_path: file_size} for all source files in a module.

    Only walks Public/, Private/, and Classes/ sub-directories.
    """
    files: Dict[str, int] = {}
    for subdir in SOURCE_SUBDIRS:
        sub = module_path / subdir
        if not sub.is_dir():
            continue
        for p in sub.rglob("*"):
            if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS:
                rel = p.relative_to(module_path).as_posix()
                try:
                    files[rel] = p.stat().st_size
                except OSError:
                    files[rel] = 0
    return files


def classify_file_changes(
    src_files: Dict[str, int],
    tgt_files: Dict[str, int],
) -> Tuple[int, int, int, int]:
    """Return (added, removed, modified, common_unchanged).

    added    — file in target but not source
    removed  — file in source but not target
    modified — file in both but size differs by > SIZE_DIFF_THRESHOLD
    common_unchanged — file in both, size similar
    """
    src_set = set(src_files)
    tgt_set = set(tgt_files)

    added = len(tgt_set - src_set)
    removed = len(src_set - tgt_set)

    modified = 0
    common_unchanged = 0
    for rel in src_set & tgt_set:
        s_size = src_files[rel]
        t_size = tgt_files[rel]
        if s_size == 0 and t_size == 0:
            common_unchanged += 1
            continue
        denom = max(s_size, t_size)
        diff_ratio = abs(s_size - t_size) / denom if denom else 0.0
        if diff_ratio > SIZE_DIFF_THRESHOLD:
            modified += 1
        else:
            common_unchanged += 1

    return added, removed, modified, common_unchanged


def compute_change_rate(
    added: int, removed: int, modified: int, src_count: int
) -> float:
    return (added + removed + modified) / max(src_count, 1)


def categorize(change_rate: float) -> str:
    if change_rate < CATEGORY_THRESHOLDS["unchanged"]:
        return "unchanged"
    if change_rate < CATEGORY_THRESHOLDS["minor"]:
        return "minor"
    if change_rate < CATEGORY_THRESHOLDS["major"]:
        return "major"
    return "rewritten"


# ---------------------------------------------------------------------------
# Subsystem detection (lightweight — subdirectory-based)
# ---------------------------------------------------------------------------

def detect_subsystems(module_path: Path) -> List[str]:
    """Return names of subdirectory-based subsystems (>=5 source files)."""
    subsystems: List[str] = []
    for subdir_name in SOURCE_SUBDIRS:
        base = module_path / subdir_name
        if not base.is_dir():
            continue
        for candidate in base.iterdir():
            if not candidate.is_dir():
                continue
            count = sum(
                1 for p in candidate.rglob("*")
                if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS
            )
            if count >= 5 and candidate.name not in subsystems:
                subsystems.append(candidate.name)
    return subsystems


def classify_subsystem(
    subsystem_name: str,
    src_module: Path,
    tgt_module: Path,
) -> Dict:
    """Classify a single subsystem across source/target module dirs."""
    src_files: Dict[str, int] = {}
    tgt_files: Dict[str, int] = {}

    for subdir_name in SOURCE_SUBDIRS:
        for root, files_dict in [
            (src_module / subdir_name / subsystem_name, src_files),
            (tgt_module / subdir_name / subsystem_name, tgt_files),
        ]:
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS:
                    rel = p.relative_to(root).as_posix()
                    try:
                        files_dict[rel] = p.stat().st_size
                    except OSError:
                        files_dict[rel] = 0

    added, removed, modified, _ = classify_file_changes(src_files, tgt_files)
    rate = compute_change_rate(added, removed, modified, len(src_files))
    cat = categorize(rate)

    return {
        "name": subsystem_name,
        "source_file_count": len(src_files),
        "target_file_count": len(tgt_files),
        "added": added,
        "removed": removed,
        "modified": modified,
        "change_rate": round(rate, 4),
        "category": cat,
    }


# ---------------------------------------------------------------------------
# Per-module classification
# ---------------------------------------------------------------------------

def classify_module(
    name: str,
    src_path: Path,
    tgt_path: Optional[Path],
    src_kdir: Path,
    tgt_kdir: Path,
    source_root: Path,
    target_root: Path,
) -> Dict:
    """Build the classification dict for one module."""

    # Module absent in target
    if tgt_path is None or not tgt_path.is_dir():
        return {
            "name": name,
            "source_path": src_path.relative_to(source_root).as_posix(),
            "target_path": None,
            "source_file_count": 0,
            "target_file_count": 0,
            "added": 0,
            "removed": 0,
            "modified": 0,
            "change_rate": 0.0,
            "category": "removed",
            "source_summary_exists": (src_kdir / "modules" / f"{name}.md").is_file(),
            "target_summary_exists": False,
            "subsystems": [],
        }

    src_files = scan_source_files(src_path)
    tgt_files = scan_source_files(tgt_path)

    src_count = len(src_files)
    tgt_count = len(tgt_files)

    src_summary = (src_kdir / "modules" / f"{name}.md").is_file()
    tgt_summary = (tgt_kdir / "modules" / f"{name}.md").is_file()

    if src_count == 0:
        # New module (exists in target, not in source)
        return {
            "name": name,
            "source_path": None,
            "target_path": tgt_path.relative_to(target_root).as_posix(),
            "source_file_count": 0,
            "target_file_count": tgt_count,
            "added": tgt_count,
            "removed": 0,
            "modified": 0,
            "change_rate": 1.0,
            "category": "new",
            "source_summary_exists": src_summary,
            "target_summary_exists": tgt_summary,
            "subsystems": [],
        }

    added, removed, modified, _ = classify_file_changes(src_files, tgt_files)
    rate = compute_change_rate(added, removed, modified, src_count)

    # Force rewritten if no source summary exists
    if not src_summary:
        cat = "rewritten"
    else:
        cat = categorize(rate)

    # Subsystems (only for larger modules or when they exist in source)
    subsystems: List[Dict] = []
    if src_count >= 50 or tgt_count >= 50:
        sys_names = detect_subsystems(src_path)
        tgt_sys_names = detect_subsystems(tgt_path)
        all_sys = sorted(set(sys_names) | set(tgt_sys_names))
        for sname in all_sys:
            subsystems.append(classify_subsystem(sname, src_path, tgt_path))

    return {
        "name": name,
        "source_path": src_path.relative_to(source_root).as_posix(),
        "target_path": tgt_path.relative_to(target_root).as_posix(),
        "source_file_count": src_count,
        "target_file_count": tgt_count,
        "added": added,
        "removed": removed,
        "modified": modified,
        "change_rate": round(rate, 4),
        "category": cat,
        "source_summary_exists": src_summary,
        "target_summary_exists": tgt_summary,
        "subsystems": subsystems,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_module_list(
    source_root: Path,
    target_root: Path,
    tier: Optional[int],
    modules_filter: Optional[List[str]],
) -> List[Tuple[str, Path, Optional[Path]]]:
    """Return list of (name, src_path, tgt_path_or_None) to process."""

    src_modules = find_module_dirs(source_root)
    tgt_modules = find_module_dirs(target_root)

    # All names: union of source + target
    all_names = sorted(set(src_modules) | set(tgt_modules))

    if modules_filter:
        all_names = [n for n in all_names if n in modules_filter]
    elif tier == 1:
        all_names = [n for n in all_names if n in TIER1_MODULES]
    elif tier is not None:
        # tiers 2-4: load from module_graph if available, else fallback to all
        all_names = [n for n in all_names if n not in TIER1_MODULES]

    result = []
    for name in all_names:
        src_path = src_modules.get(name)
        tgt_path = tgt_modules.get(name)

        # Skip if only in target (new module) but source has no entry — keep as new
        if src_path is None and tgt_path is not None:
            # Treat as "new" — use a synthetic empty src path (same as tgt)
            result.append((name, tgt_path, tgt_path))
        elif src_path is not None:
            result.append((name, src_path, tgt_path))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify UE modules for knowledge-graph porting."
    )
    parser.add_argument(
        "--source", required=True, metavar="DIR",
        help="Source (original) engine root directory."
    )
    parser.add_argument(
        "--target", default=None, metavar="DIR",
        help="Target (modded) engine root. Defaults to auto-detected cwd engine root."
    )
    parser.add_argument(
        "--source-agent-dir", default=None, metavar="DIR",
        help="Agent config dir name in source engine (e.g. .claude). Auto-scanned if omitted."
    )
    parser.add_argument(
        "--target-agent-dir", default=None, metavar="DIR",
        help="Agent config dir name in target engine. Uses _resolve.py if omitted."
    )
    parser.add_argument(
        "--tier", type=int, default=None, choices=[1, 2, 3, 4],
        help="Process only modules belonging to this tier."
    )
    parser.add_argument(
        "--modules", default=None, metavar="A,B,C",
        help="Comma-separated list of module names to process."
    )
    args = parser.parse_args()

    source_root = Path(args.source).resolve()
    if not (source_root / "Engine" / "Source").is_dir():
        sys.exit(f"ERROR: Source engine not found at {source_root}\n"
                 f"  Expected Engine/Source/ to exist.")

    if args.target:
        target_root = Path(args.target).resolve()
    else:
        target_root = find_engine_root()

    if not (target_root / "Engine" / "Source").is_dir():
        sys.exit(f"ERROR: Target engine not found at {target_root}\n"
                 f"  Expected Engine/Source/ to exist.")

    # Resolve agent dirs
    _src_agent = args.source_agent_dir  # may be None → auto-scan in helper
    _tgt_agent = args.target_agent_dir or agent_dir_name()

    src_kdir = source_knowledge_dir(source_root, _src_agent)
    tgt_kdir = knowledge_dir(target_root)
    if args.target_agent_dir:
        tgt_kdir = target_root / "Engine" / args.target_agent_dir / "knowledge"

    # Determine source agent dir name for reporting
    if _src_agent:
        src_agent_display = _src_agent
    else:
        _p = src_kdir.parent
        src_agent_display = _p.name

    modules_filter: Optional[List[str]] = None
    if args.modules:
        modules_filter = [m.strip() for m in args.modules.split(",") if m.strip()]

    entries = build_module_list(
        source_root, target_root, args.tier, modules_filter
    )

    src_modules_map = find_module_dirs(source_root)

    module_results: List[Dict] = []
    for name, src_path, tgt_path in entries:
        if name not in src_modules_map:
            # New module: only exists in target — build entry directly
            tgt_files = scan_source_files(tgt_path) if tgt_path else {}
            tgt_count = len(tgt_files)
            result = {
                "name": name,
                "source_path": None,
                "target_path": tgt_path.relative_to(target_root).as_posix() if tgt_path else None,
                "source_file_count": 0,
                "target_file_count": tgt_count,
                "added": tgt_count,
                "removed": 0,
                "modified": 0,
                "change_rate": 1.0,
                "category": "new",
                "source_summary_exists": False,
                "target_summary_exists": (tgt_kdir / "modules" / f"{name}.md").is_file(),
                "subsystems": [],
            }
        else:
            result = classify_module(
                name,
                src_path,
                tgt_path,
                src_kdir,
                tgt_kdir,
                source_root,
                target_root,
            )
        module_results.append(result)

    # Build summary counts
    categories = ["unchanged", "minor", "major", "rewritten", "new", "removed"]
    summary: Dict = {"total": len(module_results)}
    for cat in categories:
        summary[cat] = sum(1 for m in module_results if m["category"] == cat)

    output = {
        "source_engine": source_root.as_posix(),
        "source_agent_dir": src_agent_display,
        "source_knowledge_dir": src_kdir.as_posix(),
        "target_engine": target_root.as_posix(),
        "target_agent_dir": _tgt_agent,
        "target_knowledge_dir": tgt_kdir.as_posix(),
        "generated_at": date.today().isoformat(),
        "filters": {
            "tier": args.tier,
            "modules": modules_filter,
        },
        "summary": summary,
        "modules": module_results,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
