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

## Sub-Agent Dispatch Pattern

Phases 2 and 2b use the same dispatch pattern:

1. Run the planner script → it prints a JSON batch plan to stdout
2. Parse the JSON — it contains an array of `batches`
3. For each batch, read the matching prompt template from
   `Engine/.claude/skills/ue-knowledge-init/references/summary-generation-prompt.md`
4. Fill in `{placeholders}` with info from the batch plan JSON
5. Launch a **sub-agent** (Task tool) with the filled prompt
6. **Sequential dispatch**: verify `.md` files were created before the next batch

## Phase 1: Module Graph (No LLM)

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py
```

Parses all `*.Build.cs` files, extracts dependencies, classifies module types, computes topological layers.

**Output**: `Engine/.claude/knowledge/module_graph.json` (~1200+ modules, ~727KB)
**Query**: Never read this file directly. Use `scripts/query_module_graph.py` (see below).

## Phase 2: Module Summaries (Sub-Agent Dispatch)

### Generate the batch plan

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --resume --tier 1
```

Options: `--tier 1-4`, `--modules Core,Engine,RHI`, `--batch-size 3`, `--resume`

### Dispatch

Use the **Batch-Module Prompt** from `references/summary-generation-prompt.md`.
See [Sub-Agent Dispatch Pattern](#sub-agent-dispatch-pattern) above.

### Tier priority

| Tier | Modules | Description |
|------|---------|-------------|
| 1 | Core, CoreUObject, Engine, RHI, RenderCore, Renderer, ApplicationCore, SlateCore, Slate, InputCore | Core infrastructure |
| 2 | NavigationSystem, AIModule, PhysicsCore, Chaos, AnimationCore, AnimGraphRuntime, Landscape, Niagara, UMG, MovieScene | Key systems |
| 3 | UnrealEd, BlueprintGraph, Kismet, PropertyEditor, GraphEditor, ContentBrowser, Sequencer, Persona | Editor |
| 4 | Everything else | Alphabetical |

**Output**: `Engine/.claude/knowledge/modules/{ModuleName}.md`
**Template**: `references/summary-template.md`

## Phase 2b: Subsystem Summaries (Sub-Agent Dispatch)

Large modules (100+ files) have internal subsystems detected by `scripts/detect_subsystems.py`.

### Generate the subsystem batch plan

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --subsystems --auto --min-files 100 --resume
# Or for a specific module:
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --subsystems --module Renderer --resume
```

Options: `--module Renderer`, `--auto --min-files 100`, `--only PostProcess,Mobile`, `--batch-size 4`, `--resume`

### Dispatch

Use the **Batch-Subsystem Prompt** from `references/summary-generation-prompt.md`.
See [Sub-Agent Dispatch Pattern](#sub-agent-dispatch-pattern) above.

### Subsystem detection

Two methods: subdirectories (>=5 files) and filename prefix clusters (>=6 files).

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/detect_subsystems.py Renderer
python Engine/.claude/skills/ue-knowledge-init/scripts/detect_subsystems.py --auto --min-files 100 --save-index
```

`--save-index` writes `Engine/.claude/knowledge/subsystem_index.json`.

**Output**: `Engine/.claude/knowledge/modules/{ModuleName}/{SubsystemName}.md`
**Template**: `references/subsystem-template.md`

## Phase 3: Shader Map (No LLM)

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_shader_map.py
```

**Output**: `Engine/.claude/knowledge/shader_map.json`

## Master Script

```bash
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py            # all phases
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py --resume   # skip completed
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py --phase 2 --tier 1
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py --phase 2b
```

## Manual Fallback

If Python scripts are unavailable:
1. Process **at most 5 modules** per turn, **at most 3 headers** per module (200 lines)
2. Use template from `references/summary-template.md`
3. Write to `Engine/.claude/knowledge/modules/{ModuleName}.md`
4. Process tiers in order: 1 → 2 → 3 → 4

## Querying the Module Graph

`module_graph.json` is ~727KB — **never read it directly**. Use the query tool:

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
$QUERY subsystems Renderer      # list subsystems for a module
```

## Output Structure

```
Engine/.claude/knowledge/
├── module_graph.json      ← Phase 1
├── shader_map.json        ← Phase 3
├── subsystem_index.json   ← Phase 2b (optional, from --save-index)
├── changelog.md           ← Created by ue-knowledge-update
└── modules/
    ├── Core.md            ← Phase 2
    ├── Renderer.md
    ├── Renderer/           ← Phase 2b
    │   ├── PostProcess.md
    │   ├── Mobile.md
    │   └── HairStrands.md
    └── ...
```
