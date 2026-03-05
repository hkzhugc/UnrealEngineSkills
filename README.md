# Unreal Engine Skills for AI Coding Assistants

[中文版](README_CN.md)

A set of [Claude Code skills](https://docs.anthropic.com/en/docs/claude-code) (also compatible with other LLM coding clients) that give AI assistants deep understanding of the Unreal Engine 4.26 codebase.

## What This Does

Working with UE source is hard for AI — 1,200+ modules, 40M+ lines of C++, and no map. These skills build and maintain a **structured knowledge graph** so the AI can:

- Understand module dependencies and layering before suggesting changes
- Generate accurate summaries of what each module does
- Trace shader-to-C++ bindings for rendering work
- Plan cross-module modifications in the correct dependency order
- Discover and compose Blueprint-callable Python snippets via a catalog

## Skills

### `ue-knowledge-init` — Cold-Start Generator

Bootstraps the full knowledge graph from scratch. Deterministic Python scripts handle the heavy lifting (parsing 1,274 Build.cs files, mapping 595 shaders), while LLM sub-agents generate human-readable module summaries in controlled batches.

| Phase | Script | LLM? | Output |
|-------|--------|------|--------|
| 1. Module graph | `parse_module_graph.py` | No | `module_graph.json` (~1,274 modules, topological layers 0-23) |
| 2. Summaries | `generate_summaries.py` | Yes (batched sub-agents) | `modules/{Name}.md` per module |
| 3. Shader map | `generate_shader_map.py` | No | `shader_map.json` (595 shaders → C++ counterparts) |

Quick start:

```bash
# Run everything (phases 1 & 3 automatic, phase 2 outputs a batch plan)
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py

# Or run phases individually
python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_shader_map.py
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --tier 1 --resume
```

### `ue-knowledge-reader` — Navigator & Query Tool

The primary skill for day-to-day use. When you open a UE source file or ask "how does X work", this skill:

1. Identifies the module from the file path
2. Queries the dependency graph via `query_module_graph.py` (never loads the 727KB JSON directly)
3. Loads the module summary for context
4. Provides a compact orientation header and cross-module navigation

If a module summary doesn't exist, it **generates one on demand** via a sub-agent — the knowledge graph fills itself progressively as you work.

### `ue-knowledge-update` — Incremental Updater

Keeps the knowledge graph in sync after code changes. Classifies changed files by type (dependency / API / implementation / shader), then:

- Re-runs `parse_module_graph.py` if Build.cs files changed
- Edits affected module summaries (or generates missing ones via sub-agents)
- Updates `shader_map.json` if shaders changed
- Appends to `changelog.md`

### `ue-script-catalog` — Script Discovery & Execution

Connects to a pre-built catalog of every Blueprint-callable function in the engine. Supports discovering functions by intent, composing Python snippets, and executing them in the editor via MCP.

## Architecture

```
Engine/.claude/skills/                    ← this repo
├── ue-knowledge-init/
│   ├── SKILL.md                          ← skill instructions
│   ├── scripts/
│   │   ├── parse_module_graph.py         ← Phase 1: Build.cs → module_graph.json
│   │   ├── generate_shader_map.py        ← Phase 3: shaders → shader_map.json
│   │   ├── generate_summaries.py         ← Phase 2: batch planner (JSON output)
│   │   ├── query_module_graph.py         ← CLI query tool for the graph
│   │   └── init_all.py                   ← master orchestrator
│   └── references/
│       ├── summary-template.md           ← output format for module summaries
│       └── summary-generation-prompt.md  ← shared sub-agent prompt (single + batch)
├── ue-knowledge-reader/
│   ├── SKILL.md
│   └── references/
│       └── graph-schema.md               ← module_graph.json schema docs
├── ue-knowledge-update/
│   ├── SKILL.md
│   └── scripts/
│       └── trigger_knowledge_update.py
└── ue-script-catalog/
    ├── SKILL.md
    └── references/
        └── safety-protocol.md

Engine/.claude/knowledge/                 ← generated output (not in this repo)
├── module_graph.json
├── shader_map.json
├── changelog.md
└── modules/
    ├── Core.md
    ├── Engine.md
    └── ...
```

## Design Decisions

**Why Python scripts instead of pure LLM?**
Parsing 1,279 Build.cs files and 595 shaders is deterministic text extraction — wasting LLM tokens on it causes context overflow. Python scripts finish in <30 seconds with zero hallucination risk. The LLM is reserved for tasks that need intelligence: reading headers and writing useful summaries.

**Why a query tool instead of reading module_graph.json directly?**
The generated `module_graph.json` is ~727KB / 27K lines. Loading it into any LLM context window is impractical. `query_module_graph.py` loads it in Python and returns only the requested slice (typically <50 lines).

**Why sub-agent dispatch instead of `claude` CLI?**
The summary generation originally invoked `claude -p` as a subprocess. This was changed to sub-agent dispatch (via the Task tool) so the skills work with any LLM client — Claude Code, Cursor, Cline, Copilot, etc.

**Why on-demand summary generation in reader/update?**
If `ue-knowledge-init` only generates tier-1 summaries (10 modules), the other 1,264 modules would have no summaries forever. The reader and updater can now fill gaps as they encounter them, making the knowledge graph progressively self-completing.

**Why a shared prompt template?**
Three skills (init, reader, update) all need to generate summaries via sub-agents. The prompt was duplicated three times (~30 lines each). Extracting it to `summary-generation-prompt.md` means changes to generation logic only need to happen in one place.

## Setup

1. Clone this repo into `Engine/.claude/skills/`:
   ```bash
   cd /path/to/UnrealEngine/Engine/.claude
   git clone https://github.com/hkzhugc/UnrealEngineSkills.git skills
   ```

2. Run the knowledge graph initialization:
   ```bash
   cd /path/to/UnrealEngine
   python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py
   ```

3. The skills are automatically picked up by Claude Code (or any compatible LLM client that reads `SKILL.md` files from the `.claude/skills/` directory).

## Requirements

- Python 3.6+
- Unreal Engine 4.26 source tree
- An LLM coding assistant that supports skill files (Claude Code, etc.)

## License

MIT
