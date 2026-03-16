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

## Architecture

```
AI Agent <--MCP/stdio--> Python MCP Server (~120行) <--TCP/JSON--> C++ UnrealAgentBridge (~840行) <--> UE Editor
                                                                          |
                                                              exec_python / describe_object / generate_catalog
```

Three layers, all independent of the existing UnrealMCP plugin:

| Layer | Location | Role |
|-------|----------|------|
| C++ Plugin | `Engine/Plugins/UnrealAgentBridge/` | TCP server inside UE editor, executes commands on GameThread |
| Python MCP | `Engine/.claude/skills/ue-script-catalog/mcp_server/` | Translates MCP tool calls to TCP JSON messages |
| MCP Config | `Engine/.mcp.json` | Registers the Python server with Claude Code |

## File Structure

```
Engine/
├── .mcp.json                                          # MCP server registration
├── .claude/skills/ue-script-catalog/
│   ├── SKILL.md                                       # This file
│   └── mcp_server/
│       ├── pyproject.toml                             # Dependency: mcp[cli]>=1.4.1
│       └── unreal_agent_bridge_mcp.py                 # 3 MCP tools → TCP bridge
├── .claude/knowledge/callable_catalog/                # Generated output (not checked in)
│   ├── catalog_index.json
│   └── classes/*.json
└── Plugins/UnrealAgentBridge/
    ├── UnrealAgentBridge.uplugin                      # Editor plugin, optional PythonScriptPlugin dep
    └── Source/UnrealAgentBridge/
        ├── UnrealAgentBridge.Build.cs                 # 6 deps: Core, CoreUObject, Sockets, Networking, Json, JsonUtilities
        ├── Public/UnrealAgentBridgeModule.h            # IModuleInterface + FBridgeRunnable
        └── Private/UnrealAgentBridgeModule.cpp         # TCP server, GameThread dispatch, 3 commands + catalog gen
```

## Installation / Porting to Another Engine Build

### Step 1: Copy the C++ Plugin

Copy `Engine/Plugins/UnrealAgentBridge/` to the target engine's `Plugins/` directory.

Requirements:
- UE 4.26+ (uses `UProperty`, `TFieldIterator`, `TPromise/TFuture`)
- 6 module dependencies only: `Core`, `CoreUObject`, `Sockets`, `Networking`, `Json`, `JsonUtilities`
- PythonScriptPlugin is a **soft dependency** (headers resolved via `PrivateIncludePaths` + `#if __has_include`). The plugin compiles and runs without Python — `exec_python` will return an error, but `describe_object` and `generate_catalog` work fine.

Then regenerate project files and rebuild the editor:
```
# Windows
GenerateProjectFiles.bat
# Then build via Visual Studio
```

On startup, verify the log shows:
```
UnrealAgentBridge: Listening on 127.0.0.1:13090
```

Custom port: launch with `-AgentBridgePort=14000`.

### Step 2: Copy the Skill + MCP Server

Copy `Engine/.claude/skills/ue-script-catalog/` to the target engine's `.claude/skills/` directory.

Install the Python dependency:
```bash
cd Engine/.claude/skills/ue-script-catalog/mcp_server
uv sync          # preferred (uses pyproject.toml)
# or: pip install "mcp[cli]>=1.4.1"
```

### Step 3: Configure MCP

Copy or merge `Engine/.mcp.json` into the target engine's `Engine/.mcp.json`:

```json
{
  "mcpServers": {
    "unreal-agent-bridge": {
      "command": "uv",
      "args": ["run", "--directory", "Engine/.claude/skills/ue-script-catalog/mcp_server", "unreal_agent_bridge_mcp.py"],
      "env": { "AGENT_BRIDGE_PORT": "13090" }
    }
  }
}
```

If the port was changed in Step 1, update `AGENT_BRIDGE_PORT` to match.

### Step 4: Generate the Catalog

With the editor running, call `generate_catalog()` via MCP (or ask the AI to do it).
This populates `Engine/.claude/knowledge/callable_catalog/` with the JSON files.

### Verification Checklist

1. Editor log: `UnrealAgentBridge: Listening on 127.0.0.1:13090`
2. TCP test: `{"command":"ping","params":{}}\n` → `{"success":true,"message":"pong"}\n`
3. MCP tools: Claude Code shows `exec_python`, `describe_object`, `generate_catalog` in available tools
4. Catalog: `catalog_index.json` exists with 50+ classes after generation

---

## MCP Tools

| Tool | Purpose |
|------|---------|
| `exec_python(code)` | Execute Python code in the running UE editor. Single expressions auto-return values; multi-line uses file-execution mode. |
| `describe_object(class_name)` | Live UHT reflection: all BlueprintCallable functions + properties for a UClass. Accepts short names ("Actor") or full paths. |
| `generate_catalog(output_dir?)` | Scan all UClasses and write catalog JSON to `Engine/.claude/knowledge/callable_catalog/`. |

## 3-Level Discovery Workflow

### Level 0: Category Index
Read `Engine/.claude/knowledge/callable_catalog/catalog_index.json` to find relevant categories:
- `actor_management`, `asset_management`, `level_management`, `rendering`,
  `blueprint_editing`, `mesh_geometry`, `animation`, `physics`, `ui_umg`, `general`

Each category lists its classes and function count.

### Level 1: Class Details
Read `Engine/.claude/knowledge/callable_catalog/classes/{ClassName}.json` for full function signatures:
- `name`, `python_name`, `is_static`, `is_pure`, `safety_level`
- `params` with types, `return_type`, `python_snippet`

### Level 2: Live Introspection
Call `describe_object("ClassName")` for real-time detail:
- All functions including inherited ones (Level 1 only has class-own functions)
- All BlueprintVisible properties with types
- Parameter details with python types

**Example flow:** User asks "how do I get all static mesh actors?"
1. Read catalog_index.json -> category `actor_management` -> class `GameplayStatics`
2. Read classes/GameplayStatics.json -> function `get_all_actors_of_class`
3. Compose and execute:
```python
import unreal
actors = unreal.GameplayStatics.get_all_actors_of_class(
    unreal.EditorLevelLibrary.get_editor_world(),
    unreal.StaticMeshActor
)
print(f"Found {len(actors)} static mesh actors")
```

## Safety Protocol

Check the `safety_level` field in the catalog before executing:

| Level | Action |
|-------|--------|
| `read_only` | Execute immediately (Get, Find, Is, Has, Count, Check, Query) |
| `editor_modify` | Inform the user what will change, then execute. Remind about Ctrl+Z. |
| `destructive` | **Require explicit user confirmation** (Delete, Destroy, Remove, Clear, Reset, Purge) |

**Escalation rules:**
- When in doubt, treat as the higher risk level
- Batch operations on many objects always require confirmation, even for `editor_modify`
- Never retry destructive operations automatically on failure

## When the Editor is Not Running

If MCP connection fails (`ConnectionRefusedError`):
- **Catalog search** still works (read local JSON files)
- **Code composition** still works (build snippets from catalog data)
- **Execution** is unavailable — inform the user the editor must be running
- For catalog generation without editor: `UE4Editor-Cmd.exe <Project> -run=GenerateCallableCatalog`

## Catalog Refresh

Call `generate_catalog()` via MCP when:
- New plugins or modules have been added
- The catalog files are missing or outdated
- The user explicitly requests a refresh

Output goes to `Engine/.claude/knowledge/callable_catalog/` by default.

## C++ Plugin Technical Details

**Module type:** `IModuleInterface` (not `UEditorSubsystem`) — avoids `EditorSubsystem` module dependency.

**TCP protocol:** Newline-delimited JSON on port 13090.
- Request: `{"command":"X","params":{...}}\n`
- Response: `{"success":true,...}\n`

**Thread model:** TCP listener thread accepts connections. Commands are dispatched to GameThread via `TPromise/TFuture` + `AsyncTask(ENamedThreads::GameThread)`, blocking the TCP thread until the result is ready. This ensures all UE API calls (reflection, Python execution) happen on the correct thread.

**Python soft dependency:** Uses `#if __has_include("IPythonScriptPlugin.h")` to compile with or without PythonScriptPlugin headers. At runtime, `IPythonScriptPlugin::Get()` returns null if the plugin is not loaded.

**Catalog generation:** Inline implementation (~200 lines) that scans `TObjectIterator<UClass>`, filters out internal classes (SKEL_, REINST_, DEPRECATED, etc.), iterates `TFieldIterator<UFunction>` for BlueprintCallable functions, and writes per-class JSON + category index.

## Tips

- **Static functions** can be called directly: `unreal.EditorAssetLibrary.load_asset(...)`
- **Instance functions** need an object reference first
- **Editor-only classes** (`editor_only: true`) only work in the editor, not packaged builds
- **Pure functions** (`is_pure: true`) have no side effects and are safe to call repeatedly
- Single expressions are auto-detected and evaluated for return values
- Multi-line scripts, imports, and control flow use file-execution mode
