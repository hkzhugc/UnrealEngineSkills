"""Shared path resolution for UE knowledge-graph scripts.

Auto-detects the agent config directory name (e.g. '.claude', '.windsurf',
'.cursor') from the script's location, with an env-var override.

Exports:
    agent_dir_name()  -> str   e.g. '.claude'
    find_engine_root() -> Path  engine repo root containing Engine/Source/
    knowledge_dir()   -> Path  Engine/<agent>/<knowledge>
    skills_dir()      -> Path  Engine/<agent>/skills
"""

import os
from pathlib import Path

_cached_agent_dir: str | None = None


def agent_dir_name() -> str:
    """Return the agent config directory name (e.g. '.claude').

    Priority:
        1. AGENT_DIR_NAME env var
        2. Auto-detect from this file's location
        3. Fallback to '.claude'
    """
    global _cached_agent_dir
    if _cached_agent_dir is not None:
        return _cached_agent_dir

    env = os.environ.get("AGENT_DIR_NAME", "").strip()
    if env:
        _cached_agent_dir = env
        return _cached_agent_dir

    # Auto-detect: walk up from __file__ to find 'skills' parent,
    # then its parent should be Engine/<agent_dir>.
    p = Path(__file__).resolve()
    for parent in p.parents:
        if parent.name == "skills":
            candidate = parent.parent  # Engine/<agent_dir>
            # Validate: Engine/Source/ should exist as a sibling
            engine_dir = candidate.parent  # Engine/
            if (engine_dir / "Source").is_dir() and candidate.name.startswith("."):
                _cached_agent_dir = candidate.name
                return _cached_agent_dir
            break

    _cached_agent_dir = ".claude"
    return _cached_agent_dir


def find_engine_root(reference_file: str | None = None) -> Path:
    """Walk up from *reference_file* (default: this module) to find the
    engine repository root — the directory that contains ``Engine/Source/``.
    """
    start = Path(reference_file).resolve() if reference_file else Path(__file__).resolve()
    for parent in [start] + list(start.parents):
        if (parent / "Engine" / "Source").is_dir():
            return parent
    return Path.cwd()


def knowledge_dir(engine_root: Path | None = None) -> Path:
    """Return ``<engine_root>/Engine/<agent_dir>/knowledge``."""
    if engine_root is None:
        engine_root = find_engine_root()
    return engine_root / "Engine" / agent_dir_name() / "knowledge"


def skills_dir(engine_root: Path | None = None) -> Path:
    """Return ``<engine_root>/Engine/<agent_dir>/skills``."""
    if engine_root is None:
        engine_root = find_engine_root()
    return engine_root / "Engine" / agent_dir_name() / "skills"
