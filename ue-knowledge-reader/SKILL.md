---
name: ue-knowledge-reader
description: >
  Navigate and understand Unreal Engine code using the pre-built knowledge graph.
  Use this skill whenever working with UE source code, trying to understand module
  relationships, planning cross-module changes, investigating shader-to-C++ bindings,
  or when the user asks about UE architecture. Also use when the user opens an
  engine source file and needs context about which module it belongs to, what that
  module does, and how it connects to other modules. Activate for any question
  involving UE module dependencies, rendering pipeline, engine subsystems, or
  "how does X work in UE".
allowed-tools: Read Write Bash(python*) Glob Grep Task
---

# UE Knowledge Graph - Reader & Navigator

You have access to a structured knowledge graph in `Engine/.claude/knowledge/`.
Use it to provide informed, accurate context when working with Unreal Engine code.

## Available Data

```
Engine/.claude/knowledge/
├── module_graph.json      # Module dependency graph (~1274 modules, ~727KB)
├── shader_map.json        # .usf/.ush ↔ C++ mappings
├── subsystem_index.json   # Subsystem detection index (optional)
├── changelog.md           # Update history
└── modules/
    ├── Core.md            # Per-module summaries
    ├── Renderer.md
    ├── Renderer/           # Subsystem summaries (for large modules)
    │   ├── PostProcess.md
    │   ├── Mobile.md
    │   └── ...
    └── ...
```

## Module Graph Query Tool

**NEVER read `module_graph.json` directly** — it is ~27K lines and will overflow
your context. Instead, use the query tool:

```bash
QUERY="python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py"

# Get info for specific module(s)
$QUERY info Core
$QUERY info Core,Engine,RHI

# What does a module depend on (upstream)?
$QUERY deps Renderer

# What depends on a module (downstream)?
$QUERY rdeps Core

# List all modules at a specific layer
$QUERY layer 0

# Find module by source path
$QUERY path Engine/Source/Runtime/Renderer

# Dependency tree (depth-limited)
$QUERY tree RHI --depth 2

# Graph-wide statistics
$QUERY stats

# Layer-by-layer overview (compact)
$QUERY overview
```

All commands return **small JSON** (typically <50 lines) suitable for LLM context.

## When to Load What

### User opens a source file
1. Identify the module from the path:
   - `Engine/Source/Runtime/Renderer/Private/Foo.cpp` → module = "Renderer"
   - `Engine/Plugins/FX/Niagara/Source/Niagara/Private/Bar.h` → module = "Niagara"
2. Query module info: `$QUERY info Renderer`
3. Load `modules/Renderer.md`
4. Provide a brief context header:

> **[Renderer]** Layer 15 Runtime — Deferred/forward rendering pipeline
> This file is in the private implementation. Key entry: `FSceneRenderer::Render()`

### User asks "how does X work"
1. Query by path or grep to identify which module(s) own feature X
2. Load the relevant `modules/{Name}.md` summary(ies)
3. Trace the call chain using Entry Points from the summary
4. If cross-module, query deps/rdeps to show the dependency path

### User plans a modification
1. Load the target module's summary → read "Modification Guide"
2. Query deps + rdeps to find upstream and downstream modules:
   ```bash
   $QUERY deps Renderer
   $QUERY rdeps Renderer
   ```
3. For each potentially affected module, load its summary
4. Present a change impact analysis:

```
Target: Renderer
Direct impact: MobileBasePassRendering.cpp, MobileBasePassRendering.h
Upstream (may need changes): RHI (if new RHI commands), Engine (if new proxy data)
Downstream (may break): no direct dependents modify this path
Shader impact: MobileBasePassVertexShader.usf (check shader_map.json)
```

### User asks about dependencies
1. Use the query tool:
   - "What does X depend on?" → `$QUERY deps X`
   - "What depends on X?" → `$QUERY rdeps X`
   - "Show dependency tree" → `$QUERY tree X --depth 2`
2. For "why does A depend on B", load both summaries and check the
   "Module Relationships" section

### User works with shaders
1. Read `shader_map.json` (this file is small enough to load directly,
   or grep for the specific shader name)
2. Find the shader entry and its C++ counterpart
3. Load the owning module's summary for shader binding details
4. Present the CPU ↔ GPU data flow

### User asks about architecture / overview
1. Query for the overview: `$QUERY overview`
2. Or query specific layers: `$QUERY layer 0`, `$QUERY layer 1`, etc.
3. For stats: `$QUERY stats`
4. Present a layered view from the results

### When a question targets a specific area of a large module

Large modules (Renderer, Engine, Core, UnrealEd) have optional **subsystem summaries**
at `modules/{Module}/{Subsystem}.md` (30-80 lines each). Use these for targeted questions.

1. **Identify parent module** from the question or file path
2. **Check for subsystem summaries**: `Glob modules/{Module}/*.md`
3. **Match the relevant subsystem** via one of these methods:
   - **Keyword match**: question contains subsystem name (case-insensitive)
     - "mobile base pass" → Module=Renderer, Subsystem=Mobile
   - **File path match**: user's open file belongs to a subsystem's source dirs
     - `Renderer/Private/PostProcess/PostProcessBokehDOF.cpp` → Subsystem=PostProcess
   - **Semantic keywords**: consult `Engine/.claude/skills/ue-knowledge-reader/references/subsystem-keywords.json`
     - "bloom" → Renderer/PostProcess
     - "DXR" → Renderer/RayTracing
     - "montage" → Engine/Animation
4. **Load the subsystem summary** (+ optionally the top-level module summary for broader context)
5. If no subsystem summary exists, **generate on-demand** via sub-agent (see below)

**Query subsystems**: `$QUERY subsystems Renderer` — lists detected subsystems and whether summaries exist.

#### Context limits for subsystem loading
- Load **at most 2 subsystem summaries** per question
- Subsystem (30-80 lines) + top-level (~100 lines) = ~180 lines budget max
- Prefer subsystem summary over full module summary for targeted questions

## Response Format

When providing module context, always include this compact header:

> **[Module: {Name}]** (Layer {N}, {Type})
> {One-line purpose}
> Uses: {top 3 deps} | Used by: {top 3 dependents}
> Entry: `{primary_entry_point}`

This gives the user (and yourself) instant orientation.

## Cross-Module Navigation

When a task spans multiple modules, present a dependency-ordered plan:

```
Task: Add a new fog parameter to mobile rendering

1. Engine (Layer 15) - Add property to UFogComponent
   → Engine/Source/Runtime/Engine/Classes/Components/FogComponent.h
2. Renderer (Layer 15) - Read new property in fog pass
   → Engine/Source/Runtime/Renderer/Private/FogRendering.cpp
3. Shader (no layer) - Use new parameter in shader
   → Engine/Shaders/Private/HeightFogCommon.ush
```

Always order changes from lowest layer to highest - modify the foundation
before the consumers.

## Graceful Degradation

- If `module_graph.json` doesn't exist: tell the user to run `/ue-knowledge-init`
  and fall back to Glob/Grep-based exploration
- If a module's or subsystem's summary doesn't exist: **generate on demand** (see below)
- If shader_map.json doesn't exist: grep for shader references manually
- Never refuse to help just because the knowledge graph is incomplete.

### On-Demand Generation

When a summary is needed but the `.md` file doesn't exist:

1. **Module summary** (`modules/{Name}.md` missing):
   - Query: `$QUERY info {Name}`
   - Prompt: use "Single-Module Prompt" from `references/summary-generation-prompt.md`
2. **Subsystem summary** (`modules/{Module}/{Subsystem}.md` missing):
   - Query: `$QUERY subsystems {Module}`
   - Prompt: use "Single-Subsystem Prompt" from `references/summary-generation-prompt.md`

In both cases: fill in `{placeholders}`, launch a **sub-agent** (Task tool),
then read the generated summary and continue.

## Keeping Context Lean

- **NEVER load module_graph.json directly** — it is ~727KB / 27K lines
- Use `query_module_graph.py` for all dependency/layer/info queries
- Only load SUMMARY.md files that are directly relevant to the current question
- For dependency queries, the query tool output is usually sufficient — don't
  load summaries unless the user needs to understand WHY a dependency exists
- For large modules (>100 line summaries), mention the relevant section rather
  than quoting the entire file
- shader_map.json (~189KB) is also large; grep for specific entries rather than
  loading the full file when possible
