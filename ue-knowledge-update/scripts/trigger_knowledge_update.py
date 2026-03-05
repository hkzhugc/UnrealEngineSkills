#!/usr/bin/env python3
"""
Git hook trigger: analyzes commit changes and invokes Claude to update
the UE knowledge graph incrementally.

Usage:
  As a post-commit hook:
    python scripts/trigger_knowledge_update.py

  Manually with a specific commit range:
    python scripts/trigger_knowledge_update.py HEAD~3..HEAD

  Dry run (show what would be updated, don't invoke Claude):
    python scripts/trigger_knowledge_update.py --dry-run
"""

import subprocess
import sys
import os
import json
from pathlib import Path

# Resolve paths relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent.parent  # scripts/ → ue-knowledge-update/ → skills/ → .claude/ → Engine/
# Adjust: we want the actual repo root, not Engine/
# The repo root is one level above Engine/
REPO_ROOT = REPO_ROOT.parent

KNOWLEDGE_DIR = REPO_ROOT / "Engine" / ".claude" / "knowledge"
MODULE_GRAPH = KNOWLEDGE_DIR / "module_graph.json"

# Modules in these paths are typically not worth updating knowledge for
SKIP_PATTERNS = [
    "Engine/Binaries/",
    "Engine/Intermediate/",
    "Engine/Saved/",
    "Engine/Documentation/",
    "Engine/.claude/knowledge/",  # Don't trigger on our own output
]


def run_git(args, cwd=None):
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"[knowledge-update] git error: {result.stderr}", file=sys.stderr)
        return ""
    return result.stdout.strip()


def get_changed_files(commit_range=None):
    """Get list of changed files from the most recent commit or a range."""
    if commit_range:
        return run_git(["diff", "--name-only", commit_range]).split("\n")
    else:
        return run_git(["diff", "--name-only", "HEAD~1", "HEAD"]).split("\n")


def get_commit_info():
    """Get current commit hash and message."""
    hash_short = run_git(["rev-parse", "--short", "HEAD"])
    message = run_git(["log", "-1", "--pretty=%s"])
    return hash_short, message


def should_skip(filepath):
    """Check if a file should be ignored."""
    for pattern in SKIP_PATTERNS:
        if filepath.startswith(pattern):
            return True
    return False


def classify_file(filepath):
    """Classify a changed file into module and change type."""
    if should_skip(filepath):
        return None, None

    path = Path(filepath)
    parts = path.parts

    # Determine change type
    if filepath.endswith(".Build.cs"):
        change_type = "dependency"
        module_name = path.stem
        return module_name, change_type

    if filepath.endswith(".uplugin"):
        return path.stem, "plugin"

    if filepath.endswith((".usf", ".ush")):
        return path.stem, "shader"

    if filepath.endswith((".h", ".hpp")):
        for i, part in enumerate(parts):
            if part == "Public" or part == "Classes":
                if i >= 1:
                    return parts[i - 1], "api"
        # Private header
        for i, part in enumerate(parts):
            if part == "Private":
                if i >= 1:
                    return parts[i - 1], "implementation"

    if filepath.endswith((".cpp", ".c")):
        for i, part in enumerate(parts):
            if part in ("Private", "Public"):
                if i >= 1:
                    return parts[i - 1], "implementation"

    # Fallback: try to extract module from Source/<Type>/<Module>/ pattern
    for i, part in enumerate(parts):
        if part == "Source" and i + 2 < len(parts):
            candidate = parts[i + 1]
            if candidate in ("Runtime", "Editor", "Developer", "ThirdParty", "Programs"):
                return parts[i + 2], "implementation"
            else:
                return candidate, "implementation"

    return None, None


def analyze_changes(changed_files):
    """Analyze all changed files and group by module."""
    modules = {}  # module_name → set of change_types
    build_cs_changed = False
    shader_changed = False

    for f in changed_files:
        if not f.strip():
            continue
        module, change_type = classify_file(f)
        if module and change_type:
            if module not in modules:
                modules[module] = set()
            modules[module].add(change_type)
            if change_type == "dependency":
                build_cs_changed = True
            if change_type == "shader":
                shader_changed = True

    return modules, build_cs_changed, shader_changed


def build_prompt(modules, build_cs_changed, shader_changed, commit_hash, commit_msg):
    """Build the prompt for Claude."""
    lines = [
        "Run the /ue-knowledge-update skill.",
        "",
        f"Git commit: {commit_hash} - {commit_msg}",
        "",
        "Affected modules and change types:",
    ]

    for module, change_types in sorted(modules.items()):
        types_str = ", ".join(sorted(change_types))
        lines.append(f"  - {module}: {types_str}")

    if build_cs_changed:
        lines.append("")
        lines.append("Build.cs files changed - regenerate dependency entries in module_graph.json.")

    if shader_changed:
        lines.append("")
        lines.append("Shader files changed - update shader_map.json.")

    return "\n".join(lines)


def invoke_claude(prompt, dry_run=False):
    """Invoke Claude Code in non-interactive mode."""
    if dry_run:
        print("[knowledge-update] DRY RUN - would send prompt:")
        print("-" * 60)
        print(prompt)
        print("-" * 60)
        return True

    cmd = [
        "claude",
        "-p", prompt,
        "--allowedTools", "Read,Write,Edit,Bash(git diff:*),Bash(git log:*),Bash(git rev-parse:*),Glob,Grep",
        "--max-turns", "30",
    ]

    print(f"[knowledge-update] Invoking Claude...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )

    if result.returncode != 0:
        print(f"[knowledge-update] Claude error: {result.stderr}", file=sys.stderr)
        return False

    # Print a summary of what Claude did
    if result.stdout:
        # Truncate long output
        output = result.stdout
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        print(f"[knowledge-update] Claude output:\n{output}")

    return True


def main():
    dry_run = "--dry-run" in sys.argv
    commit_range = None

    for arg in sys.argv[1:]:
        if arg != "--dry-run" and not arg.startswith("-"):
            commit_range = arg

    # Check if knowledge graph exists
    if not MODULE_GRAPH.exists():
        print("[knowledge-update] module_graph.json not found.")
        print("[knowledge-update] Run /ue-knowledge-init first to bootstrap the knowledge graph.")
        sys.exit(0)

    # Get changed files
    changed_files = get_changed_files(commit_range)
    if not changed_files or changed_files == [""]:
        print("[knowledge-update] No changed files detected.")
        sys.exit(0)

    # Analyze
    modules, build_cs_changed, shader_changed = analyze_changes(changed_files)
    if not modules:
        print("[knowledge-update] No module-relevant changes detected, skipping.")
        sys.exit(0)

    # Get commit info
    commit_hash, commit_msg = get_commit_info()

    print(f"[knowledge-update] Commit {commit_hash}: {commit_msg}")
    print(f"[knowledge-update] Affected modules: {', '.join(sorted(modules.keys()))}")
    print(f"[knowledge-update] Build.cs changed: {build_cs_changed}")
    print(f"[knowledge-update] Shaders changed: {shader_changed}")

    # Build prompt and invoke
    prompt = build_prompt(modules, build_cs_changed, shader_changed, commit_hash, commit_msg)
    success = invoke_claude(prompt, dry_run=dry_run)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
