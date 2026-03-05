---
name: ue-knowledge-init
description: >
  Cold-start generator for the Unreal Engine knowledge graph. Uses Python
  scripts for deterministic work (Build.cs parsing, shader mapping) and
  sub-agent dispatch for summary generation. Use when setting up a new
  engine version, switching branches, or when the knowledge directory is
  empty. Also use when the user says "initialize knowledge", "generate
  module graph", "bootstrap knowledge", or asks to set up AI-assisted
  engine understanding.
allowed-tools: Read Write Edit Bash(python*,git*) Glob Grep Task
---

# UE Knowledge Graph — Cold Start Generator

Bootstraps the structured knowledge graph at `Engine/.claude/knowledge/`.

## Pre-flight

1. Confirm engine root: `Engine/Source/Runtime/Core/Core.Build.cs` must exist
2. Check if `Engine/.claude/knowledge/module_graph.json` already exists
   - If yes, ask user: **regenerate** or **resume** (skip to missing summaries)?
3. Ensure Python 3.6+ is available: `python --version`

## Phase 1: Module Graph (No LLM)

**Script**: `Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py`

Parses all `*.Build.cs` files, extracts dependencies (6 API patterns),
classifies module types from paths, and computes topological layers.

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py
```

**Output**: `Engine/.claude/knowledge/module_graph.json` (~1200+ modules, ~727KB)
**Schema**: See `ue-knowledge-reader/references/graph-schema.md`
**Query**: Never read this file directly. Use `scripts/query_module_graph.py` (see below).

## Phase 2: Module Summaries (Sub-Agent Dispatch)

Phase 2 is a two-step process: a Python planner computes the batch plan,
then you dispatch a sub-agent for each batch.

### Step 2a: Generate the batch plan

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --resume --tier 1
```

This prints a JSON plan to stdout. Parse the JSON. It contains:
```json
{
  "engine_root": "...",
  "modules_dir": "...",
  "total_modules": 10,
  "total_batches": 2,
  "batch_size": 5,
  "skipped": [],
  "batches": [
    [
      {"name": "Core", "path": "Engine/Source/Runtime/Core", "type": "Runtime",
       "layer": 1, "public_deps": ["TraceLog"], "private_deps": ["BuildSettings", ...]}
    ]
  ]
}
```

Options:
- `--tier 1` / `--tier 2` / `--tier 3` / `--tier 4`: filter by tier
- `--modules Core,Engine,RHI`: specific modules
- `--batch-size 3`: smaller batches (default 5)
- `--resume`: skip modules that already have `.md` files (default on)

### Step 2b: Dispatch sub-agents, one per batch

For each batch in the plan, launch a **sub-agent** (via the Task tool or
equivalent in your LLM client):

1. Read the **batch prompt template** from
   `Engine/.claude/skills/ue-knowledge-init/references/summary-generation-prompt.md`
   (use the "Batch Prompt" section)
2. Fill in `{placeholders}` with the module info from the batch plan JSON
3. Launch the sub-agent with the filled prompt

**Important**: Launch batches **sequentially**, not in parallel. After each
batch completes, verify the `.md` files were created before moving to the next.

### Tier priority

| Tier | Modules | Description |
|------|---------|-------------|
| 1 | Core, CoreUObject, Engine, RHI, RenderCore, Renderer, ApplicationCore, SlateCore, Slate, InputCore | Core infrastructure |
| 2 | NavigationSystem, AIModule, PhysicsCore, Chaos, AnimationCore, AnimGraphRuntime, Landscape, Niagara, UMG, MovieScene | Key systems |
| 3 | UnrealEd, BlueprintGraph, Kismet, PropertyEditor, GraphEditor, ContentBrowser, Sequencer, Persona | Editor |
| 4 | Everything else | Alphabetical |

**Output**: `Engine/.claude/knowledge/modules/{ModuleName}.md`
**Template**: `references/summary-template.md`
**Resumability**: The planner skips modules that already have `.md` files.

## Phase 3: Shader Map (No LLM)

**Script**: `Engine/.claude/skills/ue-knowledge-init/scripts/generate_shader_map.py`

Scans `Engine/Shaders/` for `.usf`/`.ush`, extracts `#include` graphs,
and matches each shader to C++ counterparts via filename and
`IMPLEMENT_GLOBAL_SHADER` grep.

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_shader_map.py
```

**Output**: `Engine/.claude/knowledge/shader_map.json`

## Quick Start (Full Pipeline)

```bash
# Phase 1 & 3 (deterministic, no LLM)
python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_shader_map.py

# Phase 2 (get the plan, then dispatch sub-agents per batch)
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --resume --tier 1
# → parse JSON output → dispatch sub-agents for each batch
```

Or use the master script (runs phases 1 & 3, prints phase 2 plan):
```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py --resume
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py --phase 2 --tier 1
```

## Manual Fallback

If the Python scripts are unavailable, generate summaries manually
with **strict batching rules**:

1. Process **at most 5 modules** per conversation turn
2. Read **at most 3 headers** per module (first 200 lines only)
3. Use the template from `references/summary-template.md`
4. **STOP after completing the batch** — do not continue to additional modules
5. Write each summary to `Engine/.claude/knowledge/modules/{ModuleName}.md`
6. Process tiers in order: tier 1 first, then 2, then 3, then 4

## Querying the Module Graph

`module_graph.json` is ~727KB / 27K lines — **never read it directly** in LLM
context. Use the query tool instead:

```bash
QUERY="python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py"

$QUERY info Core,Engine         # full info for specific modules
$QUERY deps Renderer            # what Renderer depends on
$QUERY rdeps Core               # what depends on Core
$QUERY layer 0                  # all layer-0 modules
$QUERY path Engine/Source/Runtime/Renderer  # find module by path
$QUERY tree RHI --depth 2       # dependency tree
$QUERY stats                    # graph-wide statistics
$QUERY overview                 # compact layer-by-layer view
```

## Output Structure

```
Engine/.claude/knowledge/
├── module_graph.json      ← Phase 1
├── shader_map.json        ← Phase 3
├── changelog.md           ← Created by ue-knowledge-update
└── modules/
    ├── Core.md            ← Phase 2
    ├── CoreUObject.md
    ├── Engine.md
    └── ...
```
