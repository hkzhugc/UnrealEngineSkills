# Module Graph JSON Schema

> **Note**: Paths below use `.claude` as the agent config directory. If your AI
> assistant uses a different directory (`.windsurf`, `.cursor`, etc.), substitute
> accordingly. Python scripts auto-detect the correct directory; set env var
> `AGENT_DIR_NAME` to override.

Quick reference for the structure of `Engine/.claude/knowledge/module_graph.json`.

> **Warning**: This file is ~727KB / 27K lines. **Never read it directly** in
> LLM context. Use the query tool instead:
> ```
> python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py info Core
> python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py deps Renderer
> python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py rdeps Core
> python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py overview
> ```

## Top Level

```json
{
  "metadata": {
    "engine_version": "string (e.g. '4.26')",
    "generated_at": "string (ISO date)",
    "total_modules": "number",
    "git_commit": "string (short hash)"
  },
  "modules": {
    "ModuleName": { ... }
  }
}
```

## Module Entry

```json
{
  "path": "Engine/Source/Runtime/ModuleName",
  "type": "Runtime | Editor | Developer | ThirdParty | Plugin | Program",
  "public_deps": ["Core", "CoreUObject"],
  "private_deps": ["RHI", "RenderCore"],
  "circular_deps": ["SomeModule"],
  "dynamic_deps": ["OptionalModule"],
  "layer": 3,
  "conditions": "optional note about platform-conditional deps",
  "last_updated": "2026-03-04"
}
```

## Layer Semantics

| Layer | Typical Modules | Description |
|-------|----------------|-------------|
| 0 | Core, TraceLog, BuildSettings | No engine dependencies |
| 1 | CoreUObject, Json | Depends only on Layer 0 |
| 2 | ApplicationCore, RHI, SlateCore | Platform & rendering foundation |
| 3 | Slate, InputCore, Engine | Major frameworks |
| 4 | Renderer, NavigationSystem, AIModule | Submodules |
| 5 | UnrealEd, Kismet, BlueprintGraph | Editor tools |
| 6+ | Game-specific plugins | Project-level |

## Querying Patterns

Use the query tool for all of these — do not parse the JSON manually:

```bash
QUERY="python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py"

# Find all modules that depend on X (downstream):
$QUERY rdeps X

# Find what X depends on (upstream):
$QUERY deps X

# Find modules at the same layer (peers):
$QUERY layer 3

# Full info for a module:
$QUERY info ModuleName

# Dependency tree:
$QUERY tree ModuleName --depth 2
```
