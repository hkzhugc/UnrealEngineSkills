# Port Prompts — Sub-Agent Prompt Templates

> **Note**: Paths below use `.claude` as the agent config directory. If your AI
> assistant uses a different directory (`.windsurf`, `.cursor`, etc.), substitute
> accordingly. Python scripts auto-detect the correct directory; set env var
> `AGENT_DIR_NAME` to override.

Prompt templates used by `ue-knowledge-port` Phase 2 to update module/subsystem
summaries based on their classification category.

## How to Use

1. Read the classification JSON produced by `port_classify.py`
2. For each module (or subsystem), pick the template matching its `category`
3. Fill in `{placeholders}` with values from the JSON
4. Append the **Common Rules** block from
   `ue-knowledge-init/references/summary-generation-prompt.md` verbatim
5. Launch a sub-agent (Task tool) with the filled prompt

---

## Common Rules (copy from ue-knowledge-init)

See `Engine/.claude/skills/ue-knowledge-init/references/summary-generation-prompt.md`
→ **Common Rules** section. Append it verbatim to every prompt below.

---

## Port-Unchanged Prompt

Use when `category == "unchanged"` (change_rate < 5%).
No code reading needed — pure file copy with metadata update.
Includes a lightweight verification step to catch stale summaries.

```
Port the module summary for "{Name}" from source to target engine.

Source summary: {source_knowledge_dir}/modules/{Name}.md
Target module path: {target_path}
Target write path: {target_knowledge_dir}/modules/{Name}.md

Before copying:
1. Read the source summary at {source_knowledge_dir}/modules/{Name}.md
2. Note 2-3 key class names listed in the "Key Concepts" section
3. Grep those class names in {target_path}/Public/ and {target_path}/Private/
4. If ALL class names are found in the target → proceed to copy:
   a. Replace any occurrences of the source engine path ({source_engine}) with
      the target engine path ({target_engine}) in file references
   b. Update "Last Updated" to {today}
   c. Write the result to {target_knowledge_dir}/modules/{Name}.md
      (create parent directories if needed)
5. If ANY key class name is missing, or new classes appear that are absent from
   the source summary → escalate: treat this module as Port-Minor instead and
   follow the Port-Minor steps below

Do NOT change any technical content when copying — Purpose, Key Concepts,
Entry Points, Architecture, and Modification Guide sections must remain
identical to the source summary (only paths and date are updated).
```

### Port-Unchanged Batch Variant

For multiple unchanged modules in one agent turn:

```
Port module summaries for these {N} unchanged modules from source to target engine.

Source knowledge dir: {source_knowledge_dir}
Target knowledge dir: {target_knowledge_dir}
Source engine path: {source_engine}
Target engine path: {target_engine}
Today's date: {today}

Modules to port:
{- Name1 | target: {target_path1}}
{- Name2 | target: {target_path2}}
...

For EACH module:
1. Read {source_knowledge_dir}/modules/{Name}.md
2. Note 2-3 key class names from the "Key Concepts" section
3. Grep those class names in {target_path}/Public/ and {target_path}/Private/
4. If ALL found → replace source engine path with target engine path, update
   "Last Updated" to {today}, write to {target_knowledge_dir}/modules/{Name}.md
5. If ANY missing → mark that module for Port-Minor treatment and skip copying
```

---

## Port-Minor Prompt

Use when `category == "minor"` (change_rate 5–30%).
Uses `changed_files` from the classify JSON to pinpoint exactly what changed,
minimising unnecessary file reads.

```
Update the module summary for "{Name}" to reflect minor changes in the target engine.

Source summary: {source_knowledge_dir}/modules/{Name}.md
Target module path: {target_path}
Target write path: {target_knowledge_dir}/modules/{Name}.md
Changed files (from classify JSON):
{changed_files_json}

Steps:
1. Read the source summary: {source_knowledge_dir}/modules/{Name}.md
2. Process changed_files in priority order:
   a. Files where "added_symbols" or "removed_symbols" is non-empty:
      These represent confirmed API surface changes. Record every symbol name
      listed — no file reading needed for these.
   b. Files where "changed_symbols" is non-empty:
      Grep each symbol name in {target_path}/Public/ and {target_path}/Private/,
      then read 30 lines of context around each match to understand what changed.
   c. Files with status "added":
      Read the first 200 lines of {target_path}/{file.path} to understand new
      classes or entry points introduced.
3. Determine which summary sections are affected:
   - Key Concepts: update if classes were added or removed
   - Entry Points: update if new public functions appeared or were removed
   - Architecture: update if structural relationships changed
   - Modification Guide: update if extension points changed
4. Copy the source summary to {target_knowledge_dir}/modules/{Name}.md
5. Edit ONLY the affected sections identified in step 3
6. Update "Last Updated" to {today}
7. Write the updated summary to {target_knowledge_dir}/modules/{Name}.md

Constraints:
- Sections NOT touched by changed_files must remain verbatim from the source summary
- Do not read files absent from changed_files unless a symbol grep returns no results
- Do not fabricate content; all class names and function names must come from
  files you actually read or from the changed_files symbol lists
```

### Port-Minor Batch Variant

For up to 3 minor modules per agent turn:

```
Update module summaries for these {N} minor-changed modules.

Source knowledge dir: {source_knowledge_dir}
Target knowledge dir: {target_knowledge_dir}
Today's date: {today}

Modules:
- {Name1} | target: {target_path1} | changed_files: {changed_files_json1}
- {Name2} | target: {target_path2} | changed_files: {changed_files_json2}
- {Name3} | target: {target_path3} | changed_files: {changed_files_json3}

For EACH module, follow the Port-Minor steps above.
Process modules sequentially (read source summary → analyse changed_files → edit → write).
```

---

## Port-Major Prompt

Use when `category == "major"` (change_rate 30–70%).
The source summary is used only as structural scaffolding; all technical content
must come from the target codebase. `changed_files` drives the read order.

```
Regenerate the module summary for "{Name}" for the target (modified) engine.

Source summary (structure reference only — do NOT copy technical content):
  {source_knowledge_dir}/modules/{Name}.md

Target module:
- Name: {Name}
- Path: {target_path}
- Type: {type}, Layer: {layer}
- Public deps: {public_deps}
- Private deps: {private_deps}

Changed files (from classify JSON — drives reading priority):
{changed_files_json}

Target write path: {target_knowledge_dir}/modules/{Name}.md

Steps:
1. Read the source summary for:
   - Section structure (use the same section names and format)
   - Subsystem names listed in the summary (verify each still exists in target)
   Do NOT carry over any class names, function names, or file paths from the
   source summary — the module has changed significantly.

2. Read target code in this priority order:
   a. Files from changed_files where "added_symbols" is non-empty — these
      expose the new API surface; read the full file (up to 300 lines)
   b. Files from changed_files where "changed_symbols" is non-empty — grep
      each changed symbol in {target_path}, read 40 lines of context
   c. Glob {target_path}/Public/**/*.h and pick at most 3 headers not already
      read above (prefer files with UCLASS/USTRUCT or the main module header);
      read first 200 lines each

3. Grep for IMPLEMENT_MODULE in {target_path}/Private/ to confirm the module
   entry point

4. Read the summary template:
   Engine/.claude/skills/ue-knowledge-init/references/summary-template.md

5. Generate a new summary describing the target engine's version of this module.
   All class names, function names, and file paths must come from target files
   you actually read in steps 2–3.

6. Update "Last Updated" to {today}

7. Write to {target_knowledge_dir}/modules/{Name}.md

Quality: never reference a symbol or path from the source summary unless you
confirmed it exists in the target by reading target code.
```

### Port-Major Batch Variant

For up to 3 major modules per agent turn:

```
Regenerate module summaries for these {N} significantly-changed modules.

Source knowledge dir: {source_knowledge_dir} (structure reference only)
Target knowledge dir: {target_knowledge_dir}
Today's date: {today}

Modules:
- {Name1} | target: {target_path1} | type: {type1} | layer: {layer1} | changed_files: {changed_files_json1}
- {Name2} | target: {target_path2} | type: {type2} | layer: {layer2} | changed_files: {changed_files_json2}
- {Name3} | target: {target_path3} | type: {type3} | layer: {layer3} | changed_files: {changed_files_json3}

For EACH module, follow the Port-Major steps above.
Read the source summary for structure only, then regenerate from target code
using changed_files to prioritise which files to read.
```

---

## Subsystem Variants

For each subsystem entry in the module's `subsystems` array, use the same
category logic but scope to the subsystem directory:

**Subsystem-Unchanged**: Same as Port-Unchanged but with path
  `modules/{ModuleName}/{SubsystemName}.md`

**Subsystem-Minor / Major**: Same as module variants but:
- Read parent module summary first (once, reuse for all subsystems)
- Scope file reads to `{target_path}/{subdir}/{SubsystemName}/`
- Use `changed_files` from the subsystem's classify entry (truncated to 20)
- Write to `{target_knowledge_dir}/modules/{ModuleName}/{SubsystemName}.md`
- Use the subsystem template:
  `Engine/.claude/skills/ue-knowledge-init/references/subsystem-template.md`
