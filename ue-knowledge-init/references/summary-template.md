# Module SUMMARY.md Template

Use this exact structure when generating a new module summary.
Sections marked `<!-- optional -->` should be omitted if not applicable.

```markdown
# Module: {ModuleName}

## Purpose
{One sentence: what this module does and why it exists in the engine}

## Key Concepts
- **{ClassName}**: {What it represents, one line}
- **{ClassName}**: {What it represents, one line}
<!-- List 3-10 most important classes/structs. Prioritize UCLASS/USTRUCT types. -->

## Entry Points
- `{Private/File.cpp}` → `{Class::Function()}`: {When this is called}
<!-- List 2-5 primary entry points that a developer would start reading from. -->

## Modification Guide
- **{Task description}**: {Which files, what pattern to follow}
<!-- List 2-5 common modification scenarios for this module. -->

## Module Relationships
### Uses (upstream dependencies)
- **{ModuleName}**: {What API/feature is consumed, one line}

### Used By (downstream dependents)
- **{ModuleName}**: {What they take from this module}

<!-- optional -->
## Shader Bindings
- `{ShaderFile.usf}` ↔ `{CppFile.cpp}`: {What data flows, what parameters}

<!-- optional -->
## Console Variables
- `{prefix.CvarName}`: {What it controls} (`{DeclaredIn.cpp}`)

<!-- optional -->
## Key Patterns
- **{Pattern name}**: {Brief explanation of a UE-specific pattern used here}
<!-- Examples: Proxy pattern, Mesh processor registration, dynamic delegate binding -->

## Last Updated
{YYYY-MM-DD} - {Brief note: "initial generation" or "updated X section"}
```

## Quality Checklist

Before writing a summary, verify:
- [ ] Purpose is one sentence, not a paragraph
- [ ] Key Concepts lists actual classes from the Public/ headers
- [ ] Entry Points have real file paths (verified via Glob/Read)
- [ ] Modification Guide is actionable (not "modify the source code")
- [ ] Module Relationships match what's in module_graph.json
- [ ] Total length is 60-150 lines (trim if longer, expand if <40)
- [ ] No fabricated class names or file paths
