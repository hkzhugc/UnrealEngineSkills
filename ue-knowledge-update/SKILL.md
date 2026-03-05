---
name: ue-knowledge-update
description: >
  Incrementally updates the Unreal Engine knowledge graph when code changes.
  Use this skill whenever modules are modified by a git commit, Build.cs
  dependencies change, new modules or plugins are added, or shaders are
  modified. Designed to be invoked automatically via git hooks or CI, but
  can also be triggered manually. Use when the user says "update knowledge",
  "sync knowledge graph", or after any significant code change.
allowed-tools: Read Write Edit Bash(git:*,python*) Glob Grep Task
---

# UE Knowledge Graph - Incremental Updater

You are incrementally updating an existing knowledge graph for an Unreal Engine
codebase. The graph lives in `Engine/.claude/knowledge/`.

## Pre-flight Check

1. Verify `Engine/.claude/knowledge/module_graph.json` exists. If not, tell the
   user to run `ue-knowledge-init` first and stop.
2. Determine the diff scope:
   - If invoked with a module list in the prompt, use that
   - Otherwise, run `git diff --name-only HEAD~1` to discover changed files

## Step 1: Classify Changes

Map changed files to modules and categorize:

```
changed_file → module_name → change_type
```

Change types:
| Pattern | Type | Action |
|---------|------|--------|
| `*.Build.cs` | dependency | Update module_graph.json + SUMMARY relationships |
| `Public/*.h` | api | Update SUMMARY key concepts / entry points |
| `Private/*.cpp` | implementation | Update SUMMARY only if significant (new class, new system) |
| `*.usf` / `*.ush` | shader | Update shader_map.json + SUMMARY shader bindings |
| `Classes/*.h` | api | Same as Public/*.h (legacy UE convention) |
| `*.uplugin` | plugin | Update module_graph.json metadata |

**Skip these:**
- Changes only to comments or whitespace
- Test modules (`*Tests*`, `*Test*`) unless they are the explicit target
- Build configs (`.ini`, `.xml`) unless they introduce new CVars

## Step 2: Update module_graph.json (if dependency changes)

**NEVER read `module_graph.json` directly** — it is ~727KB / 27K lines.

For dependency queries, use the query tool:
```bash
QUERY="python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py"
$QUERY info ModuleName          # get current deps for a module
$QUERY deps ModuleName          # upstream deps
$QUERY rdeps ModuleName         # downstream dependents
```

If Build.cs files changed, the simplest and safest approach is to **re-run
the parser** which regenerates the full graph deterministically:

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py
```

This takes <30 seconds and avoids the risk of partial in-context JSON edits
on a 27K-line file.

## Step 3: Update affected SUMMARY.md files

For each affected module, determine what needs updating:

### Minimal update (implementation changes only)
- Only update "Last Updated" section
- Add a one-line note about what changed

### Moderate update (API changes)
- Read the changed Public/ headers
- Update "Key Concepts" if new UCLASS/USTRUCT/UENUM added
- Update "Entry Points" if new public functions added
- Update "Last Updated"

### Full update (dependency changes)
- Update "Module Relationships" (Uses / Used by)
- Propagate: if module A now depends on module B, also update B's SUMMARY
  to note that A is a new downstream dependent
- Update "Last Updated"

### Shader update
- Read the changed .usf/.ush file
- Read its C++ counterpart
- Update "Shader Bindings" section
- Update shader_map.json

### Rules
- **NEVER rewrite a summary from scratch** unless the module was fundamentally
  restructured (>50% of public headers changed)
- Use Edit tool to modify specific sections, not Write to overwrite
- Preserve all human-edited content (look for `<!-- manual -->` markers)
- If a SUMMARY.md doesn't exist yet, **generate it on demand** via a sub-agent:
  1. Query the module info via the query tool
  2. Read the single-module prompt from
     `Engine/.claude/skills/ue-knowledge-init/references/summary-generation-prompt.md`
  3. Fill in placeholders and launch a sub-agent (Task tool) with the filled prompt

  For >5 missing summaries, use the batch planner instead:
  `python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --modules A,B,C`
  and dispatch one sub-agent per batch from its JSON output (use the batch prompt
  from the same reference file).

## Step 4: Update shader_map.json (if shader changes)

For each changed .usf/.ush:
1. Read current shader_map.json
2. Re-analyze the shader file (includes, what module it belongs to)
3. Search for C++ counterpart via filename matching and `IMPLEMENT_GLOBAL_SHADER` grep
4. Update or add the entry

## Step 5: Append to changelog.md

Append an entry:

```markdown
## {Date} - {git commit hash short}
**Trigger**: {automatic/manual}
**Affected modules**: {comma-separated list}
**Changes**:
- {ModuleName}: {What was updated in the knowledge graph and why}
```

## Efficiency Guidelines

- **NEVER load module_graph.json directly** — use the query tool for reads
  and re-run `parse_module_graph.py` for dependency updates
- Only read SUMMARY.md files for modules that actually need updating
- For implementation-only changes to stable modules, a one-line "Last Updated"
  edit is sufficient - don't over-update
- Batch all writes at the end rather than writing after each module
- If >20 modules are affected (rare, e.g. core API change), prioritize Tier 1-2
  modules and note the rest as "pending review" in changelog
- If >20 modules need new summaries, use the batch generator:
  `python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --modules A,B,C`
  rather than generating summaries inline

## Error Recovery

- If a SUMMARY.md is malformed, regenerate it from scratch using the
  ue-knowledge-init template
- If module_graph.json is corrupted, note the error in changelog and re-run
  `python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py`
- Never manually edit module_graph.json — always use the parser script
