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

```
Port the module summary for "{Name}" from source to target engine.

Source summary: {source_knowledge_dir}/modules/{Name}.md
Target write path: {target_knowledge_dir}/modules/{Name}.md

Steps:
1. Read the source summary at {source_knowledge_dir}/modules/{Name}.md
2. Replace any occurrences of the source engine path ({source_engine}) with
   the target engine path ({target_engine}) in file references.
3. Update "Last Updated" to {today}.
4. Write the result to {target_knowledge_dir}/modules/{Name}.md
   (create parent directories if needed).

Do NOT change any technical content — Purpose, Key Concepts, Entry Points,
Architecture, or Modification Guide sections must remain identical.
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
{- Name1}
{- Name2}
...

For EACH module:
1. Read {source_knowledge_dir}/modules/{Name}.md
2. Replace source engine path with target engine path in any file references
3. Update "Last Updated" to {today}
4. Write to {target_knowledge_dir}/modules/{Name}.md
```

---

## Port-Minor Prompt

Use when `category == "minor"` (change_rate 5–30%).
Read source summary + scan changed files → edit affected sections only.

```
Update the module summary for "{Name}" to reflect minor changes in the target engine.

Source summary: {source_knowledge_dir}/modules/{Name}.md
Target module path: {target_path}
Target write path: {target_knowledge_dir}/modules/{Name}.md
Changed files (added/modified in target): {changed_files_list}

Steps:
1. Read the source summary: {source_knowledge_dir}/modules/{Name}.md
2. For each file in the changed list (at most 3 files, first 200 lines each):
   - Read the file header to understand what changed
   - Note any new classes, removed APIs, or changed entry points
3. Copy the source summary to {target_knowledge_dir}/modules/{Name}.md
4. Edit only the sections that are affected by the changes:
   - Purpose: update if the module's core role changed
   - Key Concepts: add/remove classes that were added/removed
   - Entry Points: update file paths if renamed; add new entry points
   - Modification Guide: update if new extension points were added
5. Update "Last Updated" to {today}
6. Write the updated summary to {target_knowledge_dir}/modules/{Name}.md

Constraint: Keep unchanged sections verbatim. Only edit what the code diff
actually warrants. Do not fabricate new content.
```

### Port-Minor Batch Variant

For up to 3 minor modules per agent turn:

```
Update module summaries for these {N} minor-changed modules.

Source knowledge dir: {source_knowledge_dir}
Target knowledge dir: {target_knowledge_dir}
Today's date: {today}

Modules:
- {Name1} | target: {target_path1} | changed files: {files1}
- {Name2} | target: {target_path2} | changed files: {files2}
- {Name3} | target: {target_path3} | changed files: {files3}

For EACH module, follow the Port-Minor steps above.
Process modules sequentially (read source summary → edit → write).
```

---

## Port-Major Prompt

Use when `category == "major"` (change_rate 30–70%).
Source summary is context only — regenerate from target code.

```
Regenerate the module summary for "{Name}" for the target (modified) engine.

Context (source summary — use for structure reference only, do not copy content):
  {source_knowledge_dir}/modules/{Name}.md

Target module:
- Name: {Name}
- Path: {target_path}
- Type: {type}, Layer: {layer}
- Public deps: {public_deps}
- Private deps: {private_deps}

Target write path: {target_knowledge_dir}/modules/{Name}.md

Steps:
1. Read the source summary for structural context (section names, format).
   Do NOT copy technical content — the module has changed significantly.
2. Glob target Public/ headers: {target_path}/Public/**/*.h
3. Read at most 3 important headers (first 200 lines each; prioritize
   UCLASS/USTRUCT definitions or the main module header)
4. Grep for IMPLEMENT_MODULE in {target_path}/Private/ to find the main .cpp
5. Read the summary template:
   Engine/.claude/skills/ue-knowledge-init/references/summary-template.md
6. Generate a new summary describing the target engine's version of this module
7. Update "Last Updated" to {today}
8. Write to {target_knowledge_dir}/modules/{Name}.md

Quality: All class names and file paths must come from files you actually read.
```

### Port-Major Batch Variant

For up to 3 major modules per agent turn:

```
Regenerate module summaries for these {N} significantly-changed modules.

Source knowledge dir: {source_knowledge_dir} (context only)
Target knowledge dir: {target_knowledge_dir}
Today's date: {today}

Modules:
- {Name1} | target: {target_path1} | type: {type1} | layer: {layer1}
- {Name2} | target: {target_path2} | type: {type2} | layer: {layer2}
- {Name3} | target: {target_path3} | type: {type3} | layer: {layer3}

For EACH module, follow the Port-Major steps above.
Read the source summary for context, then regenerate from target code.
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
- Write to `{target_knowledge_dir}/modules/{ModuleName}/{SubsystemName}.md`
- Use the subsystem template:
  `Engine/.claude/skills/ue-knowledge-init/references/subsystem-template.md`
