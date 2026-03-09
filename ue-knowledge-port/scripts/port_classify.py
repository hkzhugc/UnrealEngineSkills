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
import hashlib
import json
import os
import re
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
SIZE_DIFF_THRESHOLD = 0.10          # 10% size difference → modified (fallback)
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

HASH_BLOCK_SIZE = 65536
MAX_SYMBOL_FILE_SIZE = 512 * 1024  # skip symbol extraction above this size
MAX_CHANGED_FILES_PER_MODULE = 50  # JSON output truncation
MAX_SYMBOLS_PER_FILE = 200         # cap symbol extraction per file


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
# File hashing
# ---------------------------------------------------------------------------

def file_md5(path: Path) -> str:
    """Return hex MD5 of a file, or '' on read error."""
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            while chunk := f.read(HASH_BLOCK_SIZE):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------

# Matches class/struct declarations: class Foo / struct Foo (optional API macro)
_CLASS_RE = re.compile(r'^\s*(?:class|struct)\s+(?:\w+_API\s+)?(\w+)\s*')
# Matches function definitions: return_type (Namespace::)FuncName(
_FUNC_RE = re.compile(r'^\s*[\w\*&:<>\s]+\s+(\w+::)?(\w+)\s*\(')


def extract_symbols_with_hashes(path: Path) -> Dict[str, str]:
    """Return {symbol_name: body_md5} by brace-depth tracking.

    Returns {} if the file is too large, unreadable, or has no symbols.
    Caps output at MAX_SYMBOLS_PER_FILE entries.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return {}

    if size > MAX_SYMBOL_FILE_SIZE:
        return {}

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    lines = text.splitlines()
    result: Dict[str, str] = {}
    brace_depth = 0
    current_symbol: Optional[str] = None
    symbol_lines: List[str] = []
    pending_symbol: Optional[str] = None  # matched but brace not yet seen

    for line in lines:
        stripped = line.strip()

        # Count braces in this line
        open_count = line.count('{')
        close_count = line.count('}')

        if brace_depth == 0 and current_symbol is None:
            # Skip preprocessor and pure comment lines
            if stripped.startswith('#') or stripped.startswith('//'):
                continue

            # Try class/struct match
            m_class = _CLASS_RE.match(line)
            if m_class and '{' in line:
                pending_symbol = m_class.group(1)
            elif m_class:
                pending_symbol = m_class.group(1)
                # brace may come on a later line; handled below
            else:
                # Try function signature
                m_func = _FUNC_RE.match(line)
                if m_func:
                    sym = m_func.group(2)
                    if sym and '{' in line:
                        pending_symbol = sym
                    elif sym:
                        pending_symbol = sym

            if pending_symbol and open_count > 0:
                current_symbol = pending_symbol
                pending_symbol = None
                symbol_lines = [line]
                brace_depth += open_count
                brace_depth -= close_count
                continue

        elif brace_depth == 0 and current_symbol is None and pending_symbol:
            # We had a match last line; check if brace appears now
            if '{' in line:
                current_symbol = pending_symbol
                pending_symbol = None
                symbol_lines = [line]
                brace_depth += open_count
                brace_depth -= close_count
                continue
            else:
                pending_symbol = None

        if current_symbol is not None:
            symbol_lines.append(line)
            brace_depth += open_count
            brace_depth -= close_count

            if brace_depth <= 0:
                brace_depth = 0
                body = "\n".join(symbol_lines)
                result[current_symbol] = hashlib.md5(
                    body.encode("utf-8", errors="replace")
                ).hexdigest()
                current_symbol = None
                symbol_lines = []

                if len(result) >= MAX_SYMBOLS_PER_FILE:
                    break
        else:
            # Not inside a symbol yet; update depth for any stray braces
            brace_depth += open_count
            brace_depth -= close_count
            if brace_depth < 0:
                brace_depth = 0

    return result


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def scan_source_files(module_path: Path) -> Dict[str, Tuple[int, str]]:
    """Return {relative_path: (file_size, md5_hex)} for all source files.

    Only walks Public/, Private/, and Classes/ sub-directories.
    On OSError, size=0 and md5=''.
    """
    files: Dict[str, Tuple[int, str]] = {}
    for subdir in SOURCE_SUBDIRS:
        sub = module_path / subdir
        if not sub.is_dir():
            continue
        for p in sub.rglob("*"):
            if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS:
                rel = p.relative_to(module_path).as_posix()
                try:
                    size = p.stat().st_size
                    md5 = file_md5(p)
                except OSError:
                    size = 0
                    md5 = ""
                files[rel] = (size, md5)
    return files


def classify_file_changes(
    src_files: Dict[str, Tuple[int, str]],
    tgt_files: Dict[str, Tuple[int, str]],
    src_module_path: Path,
    tgt_module_path: Path,
) -> Tuple[int, int, int, int, List[Dict]]:
    """Return (added, removed, modified, unchanged_count, changed_files_detail).

    added    — file in target but not source
    removed  — file in source but not target
    modified — file in both but md5 differs (falls back to size diff if both md5s empty)
    unchanged_count — file in both, content identical
    changed_files_detail — list of dicts describing each changed file
    """
    src_set = set(src_files)
    tgt_set = set(tgt_files)

    changed_files_detail: List[Dict] = []

    # Added files
    added_paths = sorted(tgt_set - src_set)
    for rel in added_paths:
        tgt_size, _ = tgt_files[rel]
        tgt_syms = extract_symbols_with_hashes(tgt_module_path / rel)
        changed_files_detail.append({
            "path": rel,
            "status": "added",
            "src_size": 0,
            "tgt_size": tgt_size,
            "added_symbols": sorted(tgt_syms.keys()),
            "removed_symbols": [],
            "changed_symbols": [],
        })

    # Removed files
    removed_paths = sorted(src_set - tgt_set)
    for rel in removed_paths:
        src_size, _ = src_files[rel]
        src_syms = extract_symbols_with_hashes(src_module_path / rel)
        changed_files_detail.append({
            "path": rel,
            "status": "removed",
            "src_size": src_size,
            "tgt_size": 0,
            "added_symbols": [],
            "removed_symbols": sorted(src_syms.keys()),
            "changed_symbols": [],
        })

    # Common files — check for modifications
    modified = 0
    unchanged_count = 0
    for rel in sorted(src_set & tgt_set):
        src_size, src_md5 = src_files[rel]
        tgt_size, tgt_md5 = tgt_files[rel]

        if src_md5 and tgt_md5:
            is_modified = src_md5 != tgt_md5
        else:
            # Fallback to size-based comparison when MD5 unavailable
            if src_size == 0 and tgt_size == 0:
                is_modified = False
            else:
                denom = max(src_size, tgt_size)
                diff_ratio = abs(src_size - tgt_size) / denom if denom else 0.0
                is_modified = diff_ratio > SIZE_DIFF_THRESHOLD

        if not is_modified:
            unchanged_count += 1
            continue

        modified += 1

        # Symbol-level diff for modified files
        src_syms = extract_symbols_with_hashes(src_module_path / rel)
        tgt_syms = extract_symbols_with_hashes(tgt_module_path / rel)

        if src_syms or tgt_syms:
            src_sym_set = set(src_syms.keys())
            tgt_sym_set = set(tgt_syms.keys())
            added_syms = sorted(tgt_sym_set - src_sym_set)
            removed_syms = sorted(src_sym_set - tgt_sym_set)
            changed_syms = sorted(
                s for s in src_sym_set & tgt_sym_set
                if src_syms[s] != tgt_syms[s]
            )
        else:
            added_syms = []
            removed_syms = []
            changed_syms = []

        changed_files_detail.append({
            "path": rel,
            "status": "modified",
            "src_size": src_size,
            "tgt_size": tgt_size,
            "added_symbols": added_syms,
            "removed_symbols": removed_syms,
            "changed_symbols": changed_syms,
        })

    return len(added_paths), len(removed_paths), modified, unchanged_count, changed_files_detail


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
    src_files: Dict[str, Tuple[int, str]] = {}
    tgt_files: Dict[str, Tuple[int, str]] = {}

    for subdir_name in SOURCE_SUBDIRS:
        src_root = src_module / subdir_name / subsystem_name
        tgt_root = tgt_module / subdir_name / subsystem_name
        for root, files_dict in [
            (src_root, src_files),
            (tgt_root, tgt_files),
        ]:
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS:
                    rel = p.relative_to(root).as_posix()
                    try:
                        size = p.stat().st_size
                        md5 = file_md5(p)
                    except OSError:
                        size = 0
                        md5 = ""
                    files_dict[rel] = (size, md5)

    # Use the subsystem dirs as module roots for symbol extraction
    src_sub_root = src_module  # symbols extracted relative to module root
    tgt_sub_root = tgt_module

    added, removed, modified, _, changed_files = classify_file_changes(
        src_files, tgt_files, src_sub_root, tgt_sub_root
    )
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
        "changed_files": changed_files[:20],
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
            "changed_files": [],
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
            "changed_files": [],
        }

    added, removed, modified, _, changed_files_detail = classify_file_changes(
        src_files, tgt_files, src_path, tgt_path
    )
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
        "changed_files": changed_files_detail[:MAX_CHANGED_FILES_PER_MODULE],
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
                "changed_files": [],
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
