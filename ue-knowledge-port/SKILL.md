---
name: ue-knowledge-port
description: >
  Port the Unreal Engine knowledge graph (module summaries + submodule summaries)
  from an original engine build to a heavily-modified fork. Uses file-structure
  comparison (not git diff) to compute per-module change rates, classifies each
  module into unchanged/minor/major/rewritten/new/removed, then dispatches
  sub-agents to copy, update, or regenerate summaries accordingly. Use when
  migrating an existing knowledge graph to a modded engine, when the target engine
  diverges too much for git-based tracking, or when the user says "port knowledge",
  "migrate knowledge graph", or "update summaries for my mod".
allowed-tools: Read Write Edit Bash(python*) Glob Grep Task
---

# UE Knowledge Graph — Port to Modified Engine

> **Note**: Paths below use `.claude` as the agent config directory. If your AI
> assistant uses a different directory (`.windsurf`, `.cursor`, etc.), substitute
> accordingly. Python scripts auto-detect the correct directory; set env var
> `AGENT_DIR_NAME` to override.

Ports an existing knowledge graph from a **source engine** (original UE4.26) to a
**target engine** (your modified fork). Because the fork may not track changes via
git, the tool uses file-structure and size comparison to estimate how much each
module has changed, then applies the appropriate update strategy.

## Pre-flight

1. Confirm target engine: `Engine/Source/Runtime/Core/Core.Build.cs` must exist
2. Confirm source engine's knowledge has been generated:
   `{source}/.claude/knowledge/modules/` must contain `.md` files
3. Ensure Python 3.6+: `python --version`

## Sub-Agent Dispatch Pattern

Phases 1 and 2 use the same dispatch pattern:

1. Run `port_classify.py` → prints a JSON plan to stdout
2. Parse the JSON — it contains a `modules` array with `category` per module
3. For each module, read the matching prompt template from
   `Engine/.claude/skills/ue-knowledge-port/references/port-prompt.md`
4. Fill in `{placeholders}` with values from the JSON entry
5. Launch a **sub-agent** (Task tool) with the filled prompt
6. **Sequential dispatch within a batch**: verify `.md` files exist before next batch

## Phase 1: Classify Modules (No LLM)

```bash
python Engine/.claude/skills/ue-knowledge-port/scripts/port_classify.py \
  --source /path/to/source-engine

# Tier 1 only (Core, Engine, Renderer, RHI, …)
python Engine/.claude/skills/ue-knowledge-port/scripts/port_classify.py \
  --source /path/to/source-engine --tier 1

# Specific modules
python Engine/.claude/skills/ue-knowledge-port/scripts/port_classify.py \
  --source /path/to/source-engine --modules Core,Engine,Renderer

# Explicit target and agent dirs
python Engine/.claude/skills/ue-knowledge-port/scripts/port_classify.py \
  --source /path/to/source-engine \
  --target /path/to/target-engine \
  --source-agent-dir .claude \
  --target-agent-dir .codebuddy
```

**Source agent dir**: auto-scanned (looks for hidden dir with `knowledge/` under
`{source}/Engine/`); override with `--source-agent-dir`.

**Target agent dir**: resolved via `_resolve.py`'s `agent_dir_name()` (auto-detects
from script location or `AGENT_DIR_NAME` env var); override with `--target-agent-dir`.

**Output**: JSON to stdout. Redirect to file if needed:
```bash
python ... > port_plan.json
```

### Classification categories

| Category | Condition | Strategy |
|----------|-----------|----------|
| `unchanged` | change_rate < 5% | Copy source summary, update paths + date |
| `minor` | 5% ≤ rate < 30% | Edit affected sections of source summary |
| `major` | 30% ≤ rate < 70% | Use source summary as context, regenerate |
| `rewritten` | rate ≥ 70% or no source summary | Regenerate from scratch (init flow) |
| `new` | Module only in target | Regenerate from scratch (init flow) |
| `removed` | Module only in source | Skip |

### JSON output structure

```json
{
  "source_engine": "/path/to/source",
  "source_agent_dir": ".claude",
  "source_knowledge_dir": "/path/to/source/Engine/.claude/knowledge",
  "target_engine": "/path/to/target",
  "target_agent_dir": ".claude",
  "target_knowledge_dir": "/path/to/target/Engine/.claude/knowledge",
  "generated_at": "2026-03-09",
  "summary": { "total": 10, "unchanged": 3, "minor": 2, "major": 2,
               "rewritten": 1, "new": 1, "removed": 1 },
  "modules": [
    {
      "name": "Core",
      "source_path": "Engine/Source/Runtime/Core",
      "target_path": "Engine/Source/Runtime/Core",
      "source_file_count": 1309, "target_file_count": 1320,
      "added": 15, "removed": 4, "modified": 2,
      "change_rate": 0.016,
      "category": "unchanged",
      "source_summary_exists": true,
      "target_summary_exists": false,
      "submodules": [
        { "name": "Containers", "category": "unchanged", "change_rate": 0.0 },
        { "name": "Math", "category": "minor", "change_rate": 0.08 }
      ]
    }
  ]
}
```

## Phase 2: Execute Port (Sub-Agent Dispatch)

Read the classification JSON and process each module by category.

### Category dispatch table

| Category | Prompt template | Batch size |
|----------|----------------|------------|
| `unchanged` | Port-Unchanged (Batch Variant) | 10 per turn |
| `minor` | Port-Minor (Batch Variant) | 3 per turn |
| `major` | Port-Major (Batch Variant) | 3 per turn |
| `rewritten` / `new` | Single-Module Prompt from `ue-knowledge-init` | 5 per turn |
| `removed` | Skip | — |

All prompt templates are in:
`Engine/.claude/skills/ue-knowledge-port/references/port-prompt.md`

For `rewritten` / `new`, use the **Single-Module Prompt** (or Batch-Module Prompt)
from `Engine/.claude/skills/ue-knowledge-init/references/summary-generation-prompt.md`,
writing to the **target** knowledge directory.

### Submodule handling

**REQUIRED** — after every module's top-level summary is written, you MUST also
process its submodules. Do not proceed to the next module until all submodules of
the current module are done.

For each module entry whose `submodules` array is non-empty:

1. Collect all submodule entries from `module.submodules`
2. Group them into batches of up to 4
3. For each batch, dispatch a sub-agent using the **Submodule Variants** section
   of `port-prompt.md`, with:
   - `{ModuleName}` = the parent module name
   - `{SubmoduleName}` = the submodule name
   - `{changed_files_json}` = the submodule's own `changed_files` array
   - Write path: `{target_knowledge_dir}/modules/{ModuleName}/{SubmoduleName}.md`
4. Verify each `.md` file exists before dispatching the next batch

If a module has zero submodules (`submodules: []`), skip this step and move on.

### Processing order

Process modules in tier order (to respect dependencies):
1. Tier 1: Core, CoreUObject, Engine, RHI, RenderCore, Renderer, …
2. Tier 2: NavigationSystem, AIModule, PhysicsCore, …
3. Tiers 3–4: Editor and everything else

Within each tier, process by category: `unchanged` first (fast), then
`minor`, `major`, `rewritten`/`new` last (most LLM work).

For each module, the mandatory execution sequence is:
```
1. Dispatch module top-level summary sub-agent
2. Verify {target_knowledge_dir}/modules/{Name}.md was written
3. For each submodule batch → dispatch submodule sub-agent (see Submodule handling)
4. Verify each submodule .md was written
5. Move to next module
```
Do NOT skip step 3 even if the module category is `unchanged`.

## Phase 3: Validate and Report

After all modules are processed:

1. Count `.md` files in target knowledge dir
2. Compare against expected count from the classification JSON
3. List any modules that were expected but not written
4. Write a port report:

```bash
# The report is written to:
{target_knowledge_dir}/port_report.md
```

Report format:

```markdown
# Knowledge Port Report

Generated: {today}
Source: {source_engine} ({source_agent_dir})
Target: {target_engine} ({target_agent_dir})

## Summary
- Total modules classified: N
- unchanged: N  | minor: N  | major: N
- rewritten: N  | new: N    | removed: N (skipped)

## Missing Summaries
(modules expected but not written — rerun Phase 2 for these)
- ModuleName (category: major)

## Completed
- All other modules listed with their category
```

## Manual Fallback

If Python is unavailable, manually inspect modules:
1. Compare `ls Engine/Source/Runtime/{Module}/Public/` between source and target
2. Estimate change rate visually
3. Apply the appropriate prompt template from `references/port-prompt.md`
4. Write to `{target_knowledge_dir}/modules/{Name}.md`
5. Process at most 3 modules per turn

## Relationship to Other Skills

- `port_classify.py` imports `_resolve.py` from `ue-knowledge-init/scripts/` for
  path resolution on the target side
- `rewritten`/`new` modules use the init skill's `summary-generation-prompt.md`
  directly — no duplication
- Does **not** modify any existing skill files
- Does **not** require `module_graph.json` to be present (though if it exists in
  source, it can provide tier/type/dep info via `query_module_graph.py`)
