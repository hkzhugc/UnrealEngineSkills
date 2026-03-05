# Summary Generation — Sub-Agent Prompt

Shared prompt template used by `ue-knowledge-init`, `ue-knowledge-reader`,
and `ue-knowledge-update` when generating summaries via sub-agents.

## How to Use

1. Query module/subsystem info (see each prompt below)
2. Pick the matching prompt template (Single-Module / Batch / Single-Subsystem / Batch-Subsystem)
3. Fill in `{placeholders}` with actual values
4. Append the **Common Rules** section verbatim to the end
5. Launch a sub-agent (Task tool) with the filled prompt

---

## Common Rules

Append this block to every prompt below:

```
Context limits:
- Read at most 3 headers (first 200 lines only)
- Use Glob/Grep to identify key files, do NOT read every file
- STOP after completing the assigned scope

Quality rules:
- Purpose is one sentence
- Key Concepts lists actual classes from headers you read
- Entry Points have verified file paths (confirmed via Glob)
- No fabricated class names or file paths
- Set "Last Updated" to {today's date}
```

Additional rules **for module summaries**: 60-150 lines total.
Additional rules **for subsystem summaries**: 30-80 lines total; "Internal Architecture" describes how pieces connect within the subsystem; Purpose is scoped to the subsystem, not the whole module.

---

## Single-Module Prompt

Use for **one** module (on-demand from reader/update):

```
Generate a SUMMARY.md file for the Unreal Engine 4.26 module "{Name}".

Module info:
- Path: {path}
- Type: {type}, Layer: {layer}
- Public deps: {public_deps}
- Private deps: {private_deps}

Steps:
1. Glob its Public/ headers: {path}/Public/**/*.h
2. Read at most 3 important headers (prioritize UCLASS/USTRUCT or main header)
3. Grep for IMPLEMENT_MODULE to find the module's main .cpp
4. Read the template: Engine/.claude/skills/ue-knowledge-init/references/summary-template.md
5. Generate the summary following that template
6. Write it to Engine/.claude/knowledge/modules/{Name}.md
```

## Batch-Module Prompt

Use for **multiple** modules (init Phase 2 batch dispatch):

```
Generate SUMMARY.md files for these {N} Unreal Engine 4.26 modules.

Modules to process:
- {Name} (type: {type}, layer: {layer})
  Path: {path}
  Public deps: {public_deps}
  Private deps: {private_deps}
[repeat for each module in batch]

For EACH module, follow the same steps as Single-Module above.
Write each to {modules_dir}/{Name}.md.
```

## Single-Subsystem Prompt

Use for **one** subsystem (on-demand from reader/update):

```
Generate a subsystem summary for "{SubsystemName}" within the UE4.26 module "{ModuleName}".

Parent module summary: {modules_dir}/{ModuleName}.md (read it first for context)

Subsystem info:
- Detection method: {detection}
- File count: {file_count}
- Source dirs: {source_dirs}
- Key files: {key_files}

Steps:
1. Read the parent module summary: Engine/.claude/knowledge/modules/{ModuleName}.md
2. Glob the subsystem's files: {module_path}/{source_dirs}/**/*.h and **/*.cpp
3. Read at most 3 important headers (prioritize UCLASS/USTRUCT or main header)
4. Read the subsystem template: Engine/.claude/skills/ue-knowledge-init/references/subsystem-template.md
5. Generate the summary following that template
6. Write it to Engine/.claude/knowledge/modules/{ModuleName}/{SubsystemName}.md
```

## Batch-Subsystem Prompt

Use for **multiple** subsystems of one parent module (init Phase 2b):

```
Generate subsystem summaries for these {N} subsystems of the UE4.26 module "{ModuleName}".

Parent module:
- Name: {ModuleName}
- Path: {module_path}
- Summary: {modules_dir}/{ModuleName}.md (read it ONCE, reuse for all)

Subsystems to process:
- {SubsystemName} (detection: {detection}, files: {file_count})
  Source dirs: {source_dirs}
  Key files: {key_files}
[repeat for each subsystem in batch]

For EACH subsystem, follow the same steps as Single-Subsystem above.
Read the parent module summary ONCE, reuse for all subsystems.
Write each to {modules_dir}/{ModuleName}/{SubsystemName}.md.
```
