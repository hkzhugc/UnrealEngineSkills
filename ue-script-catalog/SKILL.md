---
name: ue-script-catalog
description: >
  Discover and execute Unreal Engine callable functions via a pre-built JSON catalog.
  Use this skill when the user wants to: run Python code in the editor, find which UE
  functions/classes are available for a task, compose Python snippets for editor automation,
  introspect UObjects, or generate/refresh the callable catalog. Also use when the user
  asks "how do I do X in Python/script" in the context of Unreal Engine.
---

# UE Script Catalog — Discover & Execute Engine Functions

You have access to a **callable catalog** that describes every Blueprint-callable function
in the engine, plus MCP commands to execute Python code directly inside the Unreal Editor.

## Available Data

```
Engine/.claude/knowledge/callable_catalog/
├── catalog_index.json       # Master index: classes, categories, metadata
├── classes/                  # Per-class JSON with full function signatures
│   ├── Actor.json
│   ├── EditorAssetLibrary.json
│   └── ...
├── commandlets.json          # All available commandlets
├── execution_channels.json   # How to route execution (MCP, commandlet, file)
└── module_functions.json     # Module → function count cross-reference
```

## Workflow

### 1. Discover: Find the right function

When the user asks "how do I do X", follow this process:

1. **Load `catalog_index.json`** — scan the `categories` section to identify relevant categories
2. **Narrow by category** — look at the class list in the matching category
3. **Load per-class JSON** from `classes/{ClassName}.json` for detailed function signatures
4. **Search by keyword** — match the user's intent against function names and descriptions

Example: User asks "how do I get all actors of a specific class?"
→ Category: `actor_management`
→ Class: `GameplayStatics`
→ Function: `GetAllActorsOfClass` / `get_all_actors_of_class`

### 2. Compose: Build the Python snippet

Use the catalog's `python_snippet` field as a starting point, then fill in the parameters:

```python
# From catalog: unreal.GameplayStatics.get_all_actors_of_class(...)
import unreal
actors = unreal.GameplayStatics.get_all_actors_of_class(
    unreal.EditorLevelLibrary.get_editor_world(),
    unreal.StaticMeshActor
)
print(f"Found {len(actors)} static mesh actors")
```

### 3. Execute: Run via MCP

Use the `exec_python` MCP tool to run the composed code:

```json
{"type": "exec_python", "params": {"code": "import unreal; print(unreal.EditorLevelLibrary.get_all_level_actors())"}}
```

For multi-line scripts, use `exec_python_file`:
1. Write a .py file to a temp location
2. Call `exec_python_file` with the file path

### 4. Introspect: Explore unknown objects

Use `describe_object` to get live reflection data for any UClass:

```json
{"type": "describe_object", "params": {"object_path": "EditorAssetLibrary"}}
```

This returns all callable functions and Blueprint-visible properties.

## Safety Protocol

**Always check the `safety_level` field before executing:**

| Level | Behavior |
|-------|----------|
| `read_only` | Execute automatically — no side effects (Get, Find, Is, Has, Count) |
| `editor_modify` | Inform the user what will change, then execute |
| `destructive` | **Require explicit user confirmation** before executing (Delete, Destroy, Remove, Clear) |

See `references/safety-protocol.md` for the full protocol.

## When the Editor is Not Running

If the MCP connection is unavailable:
- **Catalog search** still works (reads local JSON files)
- **Code composition** still works (use catalog data to build snippets)
- **Execution** falls back to suggesting a commandlet:
  ```
  UE4Editor-Cmd.exe <Project> -run=GenerateCallableCatalog
  ```
- Inform the user that execution requires the editor to be open

## Catalog Refresh

The catalog can become stale if new plugins or modules are added. To refresh:

1. **Via MCP** (editor running):
   ```json
   {"type": "generate_catalog", "params": {}}
   ```

2. **Via commandlet** (no editor needed):
   ```
   UE4Editor-Cmd.exe ProjectPath -run=GenerateCallableCatalog
   ```

## Cross-Reference with Knowledge Graph

The catalog's `module_functions.json` maps modules to their exported function counts.
Cross-reference this with `Engine/.claude/knowledge/module_graph.json` from the
`ue-knowledge-reader` skill to understand both the dependency structure AND the
callable API surface of each module.

## Tips

- **Static functions** (like `EditorAssetLibrary.load_asset`) can be called directly on the class
- **Instance functions** require an object reference — use `get_all_level_actors()` or similar to obtain one
- **Editor-only classes** (marked `editor_only: true`) are only available in the editor, not in packaged builds
- **Pure functions** (`is_pure: true`) have no side effects and are safe to call repeatedly
- Prefer `EvaluateStatement` mode for single expressions that return a value
- Use `ExecuteFile` mode for multi-statement scripts
