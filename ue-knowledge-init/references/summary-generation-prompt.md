# Summary Generation — Sub-Agent Prompt

Shared prompt template used by `ue-knowledge-init`, `ue-knowledge-reader`,
and `ue-knowledge-update` when generating module SUMMARY.md files via sub-agents.

## How to Use

1. Query module info: `python Engine/.claude/skills/ue-knowledge-init/scripts/query_module_graph.py info {Name}`
2. Read this file to get the prompt template
3. Fill in `{placeholders}` with actual values from the query result
4. Launch a sub-agent (Task tool) with the filled prompt

## Single-Module Prompt

Use when generating a summary for **one** module (on-demand from reader/update):

```
Generate a SUMMARY.md file for the Unreal Engine 4.26 module "{Name}".

Module info:
- Path: {path}
- Type: {type}, Layer: {layer}
- Public deps: {public_deps}
- Private deps: {private_deps}

Steps:
1. Glob its Public/ headers: {path}/Public/**/*.h
2. Read at most 3 important headers (first 200 lines each)
   - Prioritize files with UCLASS, USTRUCT, or the module's main header
3. Grep for IMPLEMENT_MODULE to find the module's main .cpp
4. Read the template: Engine/.claude/skills/ue-knowledge-init/references/summary-template.md
5. Generate the summary following that template
6. Write it to Engine/.claude/knowledge/modules/{Name}.md

Context limits:
- Read at most 3 headers per module (first 200 lines only)
- Use Glob/Grep to identify key files, do NOT read every file
- STOP after completing this one module

Quality rules:
- Purpose is one sentence
- Key Concepts lists actual classes from headers you read
- Entry Points have verified file paths (confirmed via Glob)
- 60-150 lines total
- No fabricated class names or file paths
- Set "Last Updated" to {today's date}
```

## Batch Prompt

Use when generating summaries for **multiple** modules (init batch dispatch):

```
Generate SUMMARY.md files for these {N} Unreal Engine 4.26 modules.

Modules to process:
- {Name} (type: {type}, layer: {layer})
  Path: {path}
  Public deps: {public_deps}
  Private deps: {private_deps}
[repeat for each module in batch]

For EACH module:
1. Glob its Public/ headers: {path}/Public/**/*.h
2. Read at most 3 important headers (first 200 lines each)
   - Prioritize files with UCLASS, USTRUCT, or the module's main header
3. Grep for IMPLEMENT_MODULE to find the module's main .cpp
4. Read the template: Engine/.claude/skills/ue-knowledge-init/references/summary-template.md
5. Generate the summary following that template
6. Write it to {modules_dir}/{Name}.md

Context limits:
- Read at most 3 headers per module (first 200 lines only)
- Use Glob/Grep to identify key files, do NOT read every file
- STOP after completing all {N} modules in this batch

Quality rules:
- Purpose is one sentence
- Key Concepts lists actual classes from headers you read
- Entry Points have verified file paths (confirmed via Glob)
- 60-150 lines per summary
- No fabricated class names or file paths
- Set "Last Updated" to {today's date}
```
